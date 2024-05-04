import decky_plugin

from pathlib import Path
import os
import time

from settings import SettingsManager
from sunshine import SunshineController

class Plugin:
    sunshineController = None
    settingManager = None
    freshInstallation = False
    
    async def set_setting(self, key, value):
        return self.settingManager.setSetting(key, value)

    async def get_setting(self, key, default):
        return self.settingManager.getSetting(key, default)
        
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
            self.settingManager.setSetting("lastRunState", "start")
        return res
        
    async def sunshineStop(self):
        decky_plugin.logger.info("Stopping sunshine...")
        self.sunshineController.stop()
        self.settingManager.setSetting("lastRunState", "stop")
        return True
    
    async def sunshineIsFreshInstallation(self):
        return self.freshInstallation
    
    async def sunshineSetUser(self, newUsername, newPassword, confirmNewPassword, currentUsername = None, currentPassword = None):
        decky_plugin.logger.info("Set Sunshine User...")
        result = self.sunshineController.setUser(newUsername, newPassword, confirmNewPassword, currentUsername, currentPassword)
        decky_plugin.logger.info("User changed: " + str(result))
        return result
    
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
        self.settingManager.setSetting("lastAuthHeader", str(res))
        decky_plugin.logger.info("AuthHeader set " + res)

    async def _main(self):
        if self.sunshineController is None:
            self.sunshineController = SunshineController()
        if self.settingManager is None:
            decky_plugin.logger.info("Reading settings...")
            self.settingManager = SettingsManager(name = "decky-sunshine", settings_directory=os.environ["DECKY_PLUGIN_SETTINGS_DIR"])
            self.settingManager.read()
            decky_plugin.logger.info(str(self.settingManager))
        if not self.sunshineController.isInstalled():
            decky_plugin.logger.info("Sunshine is not installed. Installing...")
            installed = self.sunshineController.install()
            if installed:
                self.freshInstallation = True
                decky_plugin.logger.info("Sunshine installed")
                self.sunshineController.start()
                triesLeft = 5
                time.sleep(2)
                while not self.sunshineController.isRunning() or triesLeft < 1:
                    triesLeft -= 1
                    time.sleep(1)
                self.sunshineController.setUser("decky_sunshine", "decky_sunshine", "decky_sunshine")
                self.sunshineController.setAuthHeader("decky_sunshine", "decky_sunshine")
        else:
            lastAuthHeader = self.settingManager.getSetting("lastAuthHeader", "")
            decky_plugin.logger.info("lastAuthHeader: " + str(lastAuthHeader))
            if(len(lastAuthHeader) > 0):
                self.sunshineController.setAuthHeaderRaw(lastAuthHeader)
            decky_plugin.logger.info("Sunshine is installed")
        lastRunState = self.settingManager.getSetting("lastRunState", "")
        if(lastRunState == "start"):
            time.sleep(60)
            self.sunshineController.start()
        decky_plugin.logger.info("Decky Sunshine loaded")

    async def _unload(self):
        decky_plugin.logger.info("Decky Sunshine unloaded")

    async def _migration(self):
        decky_plugin.migrate_settings(str(Path(decky_plugin.DECKY_HOME) / "settings" / "decky-sunshine.json"))