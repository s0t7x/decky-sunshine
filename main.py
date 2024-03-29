import decky_plugin

import os
import subprocess
import signal

from urllib.request import urlopen, Request

def find_process_ids_by_name(name):
    child = subprocess.Popen(['pgrep', '-f', name], stdout=subprocess.PIPE, shell=False)
    response = child.communicate()[0]
    return [int(pid) for pid in response.split()]

class Plugin:
    sunshine_pipe = None

    # A normal method. It can be called from JavaScript using call_plugin_function("method_1", argument1, argument2)
    async def test(self):
        return 3
    
    async def sunshineIsOnline(self):
        decky_plugin.logger.info("Checking if Sunshine is running")
        pid = find_process_ids_by_name("sunshine")
        decky_plugin.logger.info("len(pid): " + str(len(pid)))
        if (len(pid) > 0):
            return True
        return False
    
    async def sunshineStart(self):
        decky_plugin.logger.info("Starting sunshine...")
        if self.sunshine_pipe is not None:
            self.sunshineStop()
        try:
            self.sunshine_pipe = subprocess.Popen("sh -c 'flatpak run dev.lizardbyte.app.Sunshine -0'", user=0, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, preexec_fn=os.setsid)
        except:
            decky_plugin.logger.info("exception thrown in subprocess.Popen... :c")
            self.sunshine_pipe = None
            return False
        else:
            decky_plugin.logger.info("started PID: " + str(self.sunshine_pipe.pid))
            return True
    
    async def sunshineStop(self):
        decky_plugin.logger.info("Stoping sunshine...")
        try:
            os.killpg(os.getpgid(self.sunshine_pipe.pid), signal.SIGTERM)
            pids = find_process_ids_by_name("sunshine")
            for pid in pids:
                try:
                    decky_plugin.logger.info("kill: " + str(pid))
                    os.kill(pid, signal.SIGTERM)
                except:
                    decky_plugin.logger.info("error killing: " + str(pid))
        except:
            decky_plugin.logger.info("exception thrown in subprocess.terminate... :c")
            return False
        self.sunshine_pipe = None
        return True
    
    async def sendPin(self, pin):
        decky_plugin.logger.info("Sending PIN...")
        try:
            request = Request("http://localhost:47989/pin/" + pin)
            with urlopen(request) as response:
                json = response.read().decode()
            decky_plugin.logger.info("PIN send")
            return str(json)
        except:
            decky_plugin.logger.info("Error sending PIN")
            return ""

    # Asyncio-compatible long-running code, executed in a task when the plugin is loaded
    async def _main(self):
        decky_plugin.logger.info("Decky Sunshine loaded")

    # Function called first during the unload process, utilize this to handle your plugin being removed
    async def _unload(self):
        decky_plugin.logger.info("Decky Sunshine unloaded")
        pass

    # Migrations that should be performed before entering `_main()`.
    async def _migration(self):
        # check if installed or install sunshine

        decky_plugin.logger.info("Migrating Decky Sunshine data")
        # Here's a migration example for logs:
        # - `~/.config/decky-sunshine/sunshine.log` will be migrated to `decky_plugin.DECKY_PLUGIN_LOG_DIR/sunshine.log`
        decky_plugin.migrate_logs(os.path.join(decky_plugin.DECKY_USER_HOME,
                                               ".config", "decky-sunshine", "sunshine.log"))
        # Here's a migration example for settings:
        # - `~/homebrew/settings/sunshine.json` is migrated to `decky_plugin.DECKY_PLUGIN_SETTINGS_DIR/sunshine.json`
        # - `~/.config/decky-sunshine/` all files and directories under this root are migrated to `decky_plugin.DECKY_PLUGIN_SETTINGS_DIR/`
        decky_plugin.migrate_settings(
            os.path.join(decky_plugin.DECKY_HOME, "settings", "sunshine.json"),
            os.path.join(decky_plugin.DECKY_USER_HOME, ".config", "decky-sunshine"))
        # Here's a migration example for runtime data:
        # - `~/homebrew/sunshine/` all files and directories under this root are migrated to `decky_plugin.DECKY_PLUGIN_RUNTIME_DIR/`
        # - `~/.local/share/decky-sunshine/` all files and directories under this root are migrated to `decky_plugin.DECKY_PLUGIN_RUNTIME_DIR/`
        decky_plugin.migrate_runtime(
            os.path.join(decky_plugin.DECKY_HOME, "sunshine"),
            os.path.join(decky_plugin.DECKY_USER_HOME, ".local", "share", "decky-sunshine"))
