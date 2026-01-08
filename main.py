import decky

from pathlib import Path
import os
import asyncio

from settings import SettingsManager
from sunshine import SunshineController

class Plugin:
    sunshineController = None
    settingManager = None
    _last_state = None
    _last_is_running = None
    _last_are_credentials_valid = None
    _last_version_info = None

    async def set_setting(self, key, value):
        return self.settingManager.setSetting(key, value)

    async def get_setting(self, key, default):
        return self.settingManager.getSetting(key, default)

    async def isSunshineRunning(self):
        current_is_running = self.sunshineController.isSunshineRunning()
        if self._last_is_running != current_is_running:
            decky.logger.info(f"Sunshine running state changed: {self._last_is_running if self._last_is_running is not None else 'unknown'} → {current_is_running if current_is_running is not None else 'unknown'}")
            self._last_is_running = current_is_running
        return current_is_running

    async def areCredentialsValid(self):
        current_are_credentials_valid = await self.sunshineController.areCredentialsValid_async()
        if self._last_are_credentials_valid != current_are_credentials_valid:
            decky.logger.info(f"Credentials valid state changed: {self._last_are_credentials_valid if self._last_are_credentials_valid is not None else 'unknown'} → {current_are_credentials_valid if current_are_credentials_valid is not None else 'unknown'}")
            self._last_are_credentials_valid = current_are_credentials_valid
        return current_are_credentials_valid

    async def startSunshine(self):
        decky.logger.info("Starting sunshine...")
        res = await self.sunshineController.start_async()
        if res:
            decky.logger.info("Sunshine started")
            self.settingManager.setSetting("lastRunState", "start")
        else:
            decky.logger.info("Couldn't start Sunshine")
            self.settingManager.setSetting("lastRunState", "stop")
        return res

    async def stopSunshine(self):
        decky.logger.info("Stopping sunshine...")
        res = await self.sunshineController.stop_async()
        if res:
            decky.logger.info("Sunshine stopped")
            self.settingManager.setSetting("lastRunState", "stop")
        else:
            decky.logger.info("Couldn't stop Sunshine")
            self.settingManager.setSetting("lastRunState", "start")
        return res

    async def pair(self, pin, client_name):
        if not pin or not client_name:
            decky.logger.info("No pin or client name provided for pairing")
            return False
        decky.logger.info(f"Trying to pair with PIN {pin} for client {client_name}")
        send = await self.sunshineController.pair_async(pin, client_name)
        decky.logger.info(f"Pairing returned {send}")
        return send

    async def setCredentials(self, username, password):
        if not username or not password:
            decky.logger.info("Invalid username or password provided for setting credentials")
            return None
        decky.logger.info("Setting credentials...")
        authHeader = self.sunshineController.setCredentials(username, password)
        self.settingManager.setSetting("lastAuthHeader", authHeader)
        decky.logger.info("Credentials set")
        return await self.areCredentialsValid(self)

    async def getCredentials(self):
        decky.logger.info("Getting credentials...")
        credentials = self.sunshineController.getCredentials()
        if not credentials:
            decky.logger.info("No credentials found")
            return None
        decky.logger.info(f"Credentials found")
        return credentials

    async def getSunshineVersionInfo(self):
        versionInfo = self.sunshineController.getSunshineVersionInfo()
        if versionInfo:
            last_current_version = self._last_version_info["current_version"] or 'unknown' if self._last_version_info else 'unknown'
            last_update_version = self._last_version_info["update_version"] or 'unknown' if self._last_version_info else 'unknown'

            current_current_version = versionInfo["current_version"] or 'unknown'
            current_update_version = versionInfo["update_version"] or 'unknown'
            if last_current_version != current_current_version:
                decky.logger.info(f"Sunshine version info changed: {last_current_version} → {current_current_version}")
            if last_update_version != current_update_version:
                decky.logger.info(f"Sunshine update version info changed: {last_update_version} → {current_update_version}")
            self._last_version_info = versionInfo
        return versionInfo

    async def updateSunshine(self):
        decky.logger.info("Updating Sunshine...")
        res = await self.sunshineController.updateSunshine_async()
        if res:
            decky.logger.info("Sunshine updated successfully")
        else:
            decky.logger.info("Couldn't update Sunshine")
        return res

    async def _main(self):
        decky.logger.info(f"Decky Sunshine version: {decky.DECKY_PLUGIN_VERSION}")
        if self.sunshineController is None:
            self.sunshineController = SunshineController(decky.logger)

        if self.settingManager is None:
            decky.logger.info("Reading settings...")
            self.settingManager = SettingsManager(name = "decky-sunshine", settings_directory=os.environ["DECKY_PLUGIN_SETTINGS_DIR"])
            self.settingManager.read()
            decky.logger.info(f"Read settings")
            self._log_settings(self)

        if not await self.sunshineController.ensureDependencies_async():
            decky.logger.error("Couldn't ensure dependencies")
            return

        # If an authHeader is set in the controller, this means that
        # Sunshine was just installed with default credentials. Thus,
        # we need to store these credentials for future use.
        authHeader = self.sunshineController.authHeader
        if authHeader:
            self.settingManager.setSetting("lastAuthHeader", authHeader)
            decky.logger.info("Stored newly created credentials")
        else:
            lastAuthHeader = self.settingManager.getSetting("lastAuthHeader", "")
            if not lastAuthHeader:
                decky.logger.error("No lastAuthHeader found in settings")
            else:
                decky.logger.info("Setting auth header from settings")
                self.sunshineController.authHeader = lastAuthHeader

        lastRunState = self.settingManager.getSetting("lastRunState", "")
        if lastRunState in ("start", ""):
            decky.logger.info("Starting Sunshine")
            await self.sunshineController.start_async()

        decky.logger.info("Decky Sunshine loaded")

    async def _unload(self):
        decky.logger.info("Decky Sunshine unloaded")

    async def _migration(self):
        decky.migrate_settings(str(Path(decky.DECKY_HOME) / "settings" / "decky-sunshine.json"))

    def _log_settings(self):
        """
        Log all settings in a pretty format, masking sensitive values.
        """
        try:
            if not self.settingManager.settings:
                decky.logger.info("Settings: [EMPTY]")
                return

            decky.logger.info("Current settings:")
            for key in sorted(self.settingManager.settings.keys()):
                value = self.settingManager.settings[key]
                if key == "lastAuthHeader":
                    status = f"[SET - {len(str(value))} characters]" if value else "[EMPTY]"
                else:
                    status = "[EMPTY]" if (value is None or value == "") else f"'{value}'"

                decky.logger.info(f"  {key}: {status}")

        except Exception as e:
            decky.logger.error(f"Error logging settings: {e}")
