import decky_plugin
import os

from sunshine import SunshineController

class Plugin:
    sunshineController = None
    freshInstallation = False
        
    async def sunshineIsRunning(self):
        isRunning = self.sunshineController.isRunning()
        decky_plugin.logger.info("Is Sunshine running: " + str(isRunning))
        return isRunning
    
    async def sunshineIsAuthorized(self):
        isAuthorized = self.sunshineController.isAuthorized()
        decky_plugin.logger.info("Is Decky Sunshine authorized: " + str(isAuthorized))
        return isAuthorized
    
    async def sunshineStart(self):
        decky_plugin.logger.info("Starting sunshine...")
        res = self.sunshineController.start()
        if res:
            decky_plugin.logger.info("Sunshine started")
        return res
        
    async def sunshineStop(self):
        decky_plugin.logger.info("Stopping sunshine...")
        self.sunshineController.stop()
        return True
    
    async def sunshineIsFreshInstallation(self):
        return self.freshInstallation
    
    async def sunshineSetUser(self, newUsername, newPassword, confirmNewPassword, currentUsername = None, currentPassword = None):
        # TODO: implement
        pass
    
    async def sendPin(self, pin):
        decky_plugin.logger.info("Sending PIN..." + pin)
        send = self.sunshineController.sendPin(pin)
        decky_plugin.logger.info("PIN send " + str(send))
        return send
    
    async def setAuthHeader(self, username, password):
        if len(username) + len(password) < 1:
            decky_plugin.logger.info("No AuthHeader to set")
            return
        decky_plugin.logger.info("Set AuthHeader...")
        res = self.sunshineController.setAuthHeader(username, password)
        decky_plugin.logger.info("AuthHeader set " + res)

    async def _main(self):
        if self.sunshineController is None:
            self.sunshineController = SunshineController()
        if not self.sunshineController.isInstalled():
            decky_plugin.logger.info("Sunshine is not installed. Installing...")
            installed = self.sunshineController.install()
            if installed:
                self.freshInstallation = True
                decky_plugin.logger.info("Sunshine installed")
                self.sunshineController.start()
                self.sunshineController.setUser("decky_sunshine", "decky_sunshine", "decky_sunshine")
                self.sunshineController.setAuthHeader("decky_sunshine", "decky_sunshine")
        else:
            decky_plugin.logger.info("Sunshine is installed")
        decky_plugin.logger.info("Decky Sunshine loaded")

    async def _unload(self):
        decky_plugin.logger.info("Decky Sunshine unloaded")
        pass

    async def _migration(self):
        # - `~/homebrew/settings/sunshine.json` is migrated to `decky_plugin.DECKY_PLUGIN_SETTINGS_DIR/sunshine.json`
        # - `~/.config/decky-sunshine/` all files and directories under this root are migrated to `decky_plugin.DECKY_PLUGIN_SETTINGS_DIR/`
        decky_plugin.migrate_settings(
            os.path.join(decky_plugin.DECKY_HOME, "settings", "sunshine.json"),
            os.path.join(decky_plugin.DECKY_USER_HOME, ".config", "decky-sunshine"))