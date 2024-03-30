import decky_plugin
import os

from py_modules.sunshine import SunshineController

class Plugin:
    sunshineController = SunshineController()
        
    async def _main(self):
        decky_plugin.logger.info("Decky Sunshine loaded")

    async def sunshineIsRunning(self):
        isRunning = sunshineController.isRunning()
        decky_plugin.logger.info("Is Sunshine running: " + str(isRunning))
        return isRunning
    
    async def sunshineIsAuthorized(self):
        isAuthorized = sunshineController.isAuthorized()
        decky_plugin.logger.info("Is Decky Sunshine authorized: " + str(isAuthorized))
        return isAuthorized
    
    async def sunshineStart(self):
        decky_plugin.logger.info("Starting sunshine...")
        res = sunshineController.start()
        decky_plugin.logger.info("Sunshine " + (res and "NOT ") + "started")
        return res
        
    async def sunshineStop(self):
        decky_plugin.logger.info("Stopping sunshine...")
        sunshineController.stop()
        return True
    
    async def sendPin(self, pin):
        decky_plugin.logger.info("Sending PIN...")
        send = sunshineController.sendPin(pin)
        decky_plugin.logger.info("PIN " + (send and "NOT ") + "send")
        return send

    async def _unload(self):
        decky_plugin.logger.info("Decky Sunshine unloaded")
        pass

    async def _migration(self):
        # TODO: check if installed or install sunshine ? :)

        # - `~/homebrew/settings/sunshine.json` is migrated to `decky_plugin.DECKY_PLUGIN_SETTINGS_DIR/sunshine.json`
        # - `~/.config/decky-sunshine/` all files and directories under this root are migrated to `decky_plugin.DECKY_PLUGIN_SETTINGS_DIR/`
        decky_plugin.migrate_settings(
            os.path.join(decky_plugin.DECKY_HOME, "settings", "sunshine.json"),
            os.path.join(decky_plugin.DECKY_USER_HOME, ".config", "decky-sunshine"))