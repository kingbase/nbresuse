import os
import json
import psutil
from traitlets import Float, Int, default
from traitlets.config import Configurable
from notebook.utils import url_path_join
from notebook.base.handlers import IPythonHandler


# slow on windows but much faster on linux
def get_pid_via_connection_file(connection_file):
    for p in psutil.process_iter():
        try:
            cmdline = p.cmdline()
        except psutil.AccessDenied:
            continue
        if connection_file in ",".join(cmdline):
            return p.pid
    return None


class MetricsHandler(IPythonHandler):
    def get(self):
        """
        Calculate and return current resource usage metrics
        """
        config = self.settings['nbresuse_display_config']
        cur_process = psutil.Process()
        all_processes = [cur_process] + cur_process.children(recursive=True)
        rss = sum([p.memory_info().rss for p in all_processes])

        this_kernel_rss = None
        if "kernel_id" in self.request.arguments:
            kernel_id = self.request.arguments["kernel_id"]
            kernel_id = kernel_id[0].decode("utf-8")
            kernel_pid = get_pid_via_connection_file(kernel_id)

            if not kernel_pid is None:
                kernel_process = psutil.Process(kernel_pid)
                kernel_all_processes = [kernel_process] + kernel_process.children(recursive=True)
                this_kernel_rss = sum([p.memory_info().rss for p in kernel_all_processes])

        limits = {}

        if config.mem_limit != 0:
            limits['memory'] = {
                'rss': config.mem_limit
            }
            if config.mem_warning_threshold != 0:
                limits['memory']['warn'] = (config.mem_limit - rss) < (config.mem_limit * config.mem_warning_threshold)
        metrics = {
            'rss': rss,
            'limits': limits,
            'this_kernel_rss': this_kernel_rss,
        }
        self.write(json.dumps(metrics))


def _jupyter_server_extension_paths():
    """
    Set up the server extension for collecting metrics
    """
    return [{
        'module': 'nbresuse',
    }]

def _jupyter_nbextension_paths():
    """
    Set up the notebook extension for displaying metrics
    """
    return [{
        "section": "notebook",
        "dest": "nbresuse",
        "src": "static",
        "require": "nbresuse/main"
    }]

class ResourceUseDisplay(Configurable):
    """
    Holds server-side configuration for nbresuse
    """

    mem_warning_threshold = Float(
        0.1,
        help="""
        Warn user with flashing lights when memory usage is within this fraction
        memory limit.

        For example, if memory limit is 128MB, `mem_warning_threshold` is 0.1,
        we will start warning the user when they use (128 - (128 * 0.1)) MB.

        Set to 0 to disable warning.
        """,
        config=True
    )

    mem_limit = Int(
        0,
        config=True,
        help="""
        Memory limit to display to the user, in bytes.

        Note that this does not actually limit the user's memory usage!

        Defaults to reading from the `MEM_LIMIT` environment variable. If
        set to 0, no memory limit is displayed.
        """
    )

    @default('mem_limit')
    def _mem_limit_default(self):
        return int(os.environ.get('MEM_LIMIT', 0))

def load_jupyter_server_extension(nbapp):
    """
    Called during notebook start
    """
    resuseconfig = ResourceUseDisplay(parent=nbapp)
    nbapp.web_app.settings['nbresuse_display_config'] = resuseconfig
    route_pattern = url_path_join(nbapp.web_app.settings['base_url'], '/metrics')
    nbapp.web_app.add_handlers('.*', [(route_pattern, MetricsHandler)])
