import decky

from pathlib import Path
import os

from settings import SettingsManager
from sunshine import SunshineController

class Plugin:
    def __init__(self):
        self.sunshineController = None
        self.settingManager = None
        self._last_is_running = None
        self._last_are_credentials_valid = None
        self._last_version_info = None

    async def set_setting(self, key, value):
        return self.settingManager.setSetting(key, value)

    async def get_setting(self, key, default):
        return self.settingManager.getSetting(key, default)

    async def is_sunshine_running(self):
        current_is_running = await self.sunshineController.isSunshineRunning_async()
        if self._last_is_running != current_is_running:
            decky.logger.info(f"Sunshine running state changed: {self._last_is_running if self._last_is_running is not None else 'unknown'} → {current_is_running if current_is_running is not None else 'unknown'}")
            self._last_is_running = current_is_running
        return current_is_running

    async def are_credentials_valid(self):
        current_are_credentials_valid = await self.sunshineController.areCredentialsValid_async()
        if self._last_are_credentials_valid != current_are_credentials_valid:
            decky.logger.info(f"Credentials valid state changed: {self._last_are_credentials_valid if self._last_are_credentials_valid is not None else 'unknown'} → {current_are_credentials_valid if current_are_credentials_valid is not None else 'unknown'}")
            self._last_are_credentials_valid = current_are_credentials_valid
        return current_are_credentials_valid

    async def start_sunshine(self):
        decky.logger.info("Starting sunshine...")
        starting = not await self.sunshineController.isSunshineRunning_async()
        added_now = await self._ensure_csrf_allowed_origin()
        res = await self.sunshineController.start_async()
        if starting and res:
            self.settingManager.setSetting("csrfRestartPending", False)
        elif added_now:
            self.settingManager.setSetting("csrfRestartPending", True)
        if res:
            decky.logger.info("Sunshine started")
            self.settingManager.setSetting("lastRunState", "start")
        else:
            decky.logger.info("Couldn't start Sunshine")
            self.settingManager.setSetting("lastRunState", "stop")
        return res

    async def set_force_composition(self, enabled):
        """
        Persist the "force gamescope composition while streaming" toggle. The
        controller applies it on its next start_async and clears it on
        stop_async; also reconcile immediately if Sunshine is already running.
        The override only takes effect while an external display is connected
        (the controller watches for dock changes). Fixes the docked capture
        glitch where the image is squeezed into part of the screen with the
        right side stretched across the rest.
        """
        self.settingManager.setSetting("forceComposition", enabled)
        self.sunshineController.force_composition = enabled
        if await self.sunshineController.isSunshineRunning_async():
            await self.sunshineController.applyCompositionPreference_async()
        decky.logger.info(f"forceComposition set to {enabled}")
        return enabled

    async def get_force_composition(self):
        return self.settingManager.getSetting("forceComposition", False)

    async def stop_sunshine(self):
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

    async def set_credentials(self, username, password):
        if not username or not password:
            decky.logger.info("Invalid username or password provided for setting credentials")
            return None
        decky.logger.info("Setting credentials...")
        authHeader = self.sunshineController.setCredentials(username, password)
        self.settingManager.setSetting("lastAuthHeader", authHeader)
        decky.logger.info("Credentials set")
        return await self.are_credentials_valid()

    async def get_credentials(self):
        decky.logger.info("Getting credentials...")
        credentials = self.sunshineController.getCredentials()
        if not credentials:
            decky.logger.info("No credentials found")
            return None
        decky.logger.info(f"Credentials found")
        return credentials

    async def get_web_ui_info(self):
        """
        The LAN IP other devices reach the Web UI under (None without a
        network route) and whether changing settings from that address works:
        the current LAN origin must be covered by csrf_allowed_origins in
        sunshine.conf (read live, so entries that were already there - from a
        user or an earlier run - count), and no config change may be pending
        that the running instance has not loaded (csrfRestartPending; Sunshine
        reads its config only at startup). When not ready, the frontend offers
        the one restart that fixes it.
        """
        ip = self.sunshineController.getLanIp()
        editing_ready = False
        if ip is not None:
            origin = f"https://{ip}:{self.sunshineController.WebUiPort}"
            editing_ready = (
                await self.sunshineController.isCsrfOriginAllowed_async(origin)
                and not self.settingManager.getSetting("csrfRestartPending", False)
            )
        return {
            "ip": ip,
            "editing_ready": editing_ready,
        }

    async def _ensure_csrf_allowed_origin(self):
        """
        Keep the Web UI usable (not just viewable) from other devices: have
        the controller allow the current LAN origin in Sunshine's config and
        persist which entry the plugin manages (csrfManagedOrigin), so a later
        run can replace it after an IP change without touching user-added
        entries. Must run before Sunshine starts; it reads the config only
        then.
        :return: Whether the allowance was missing and added just now. The
                 caller must translate that into the csrfRestartPending
                 setting: set it when Sunshine kept running (the instance has
                 not loaded the new entry), clear it once an actual
                 (re)start happened.
        """
        managed_old = self.settingManager.getSetting("csrfManagedOrigin", "")
        managed_new, added_now = await self.sunshineController.ensureCsrfAllowedOrigin_async(managed_old)
        if managed_new != managed_old:
            self.settingManager.setSetting("csrfManagedOrigin", managed_new)
        return added_now

    async def get_sunshine_version_info(self, refresh_appstream = True):
        versionInfo = await self.sunshineController.getSunshineVersionInfo_async(refresh_appstream)
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

    async def update_sunshine(self):
        decky.logger.info("Updating Sunshine...")
        # The update flow restarts Sunshine, so it picks up the origin ensured
        # here; on failure the old instance may keep running without it.
        added_now = await self._ensure_csrf_allowed_origin()
        res = await self.sunshineController.updateSunshine_async()
        if res:
            self.settingManager.setSetting("csrfRestartPending", False)
            decky.logger.info("Sunshine updated successfully")
        else:
            if added_now:
                self.settingManager.setSetting("csrfRestartPending", True)
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
            self._log_settings()

        await self.sunshineController.logEnvironment_async()

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

        # Carry the persisted "force composition while streaming" preference into
        # the controller so the auto-start below (and any later start) applies it.
        self.sunshineController.force_composition = self.settingManager.getSetting("forceComposition", False)

        lastRunState = self.settingManager.getSetting("lastRunState", "")
        if lastRunState in ("start", ""):
            decky.logger.info("Starting Sunshine")
            # Sunshine may have survived a plugin_loader restart; then this is
            # an ensure-only pass and the running instance keeps enforcing the
            # allowances from its own start (see _ensure_csrf_allowed_origin).
            starting = not await self.sunshineController.isSunshineRunning_async()
            added_now = await self._ensure_csrf_allowed_origin()
            started = await self.sunshineController.start_async()
            if starting and started:
                self.settingManager.setSetting("csrfRestartPending", False)
            elif added_now:
                self.settingManager.setSetting("csrfRestartPending", True)

        decky.logger.info("Decky Sunshine loaded")

    async def _unload(self):
        decky.logger.info("Decky Sunshine unloaded")

    async def _uninstall(self):
        """
        Called by the loader when the plugin is being uninstalled (after
        _unload). The plugin process can die at any moment from here on (the
        loader SIGKILLs it at the latest ~5 s after its stop request; on the
        Deck it was observed dying even earlier), so the work is ordered by
        cost: first dispatch the detached helper that stops Sunshine and
        releases the composition override (survives this process, ~2 ms),
        then remove the setuid bwrap copies. Deliberately no in-process
        stop_async: it never ran to completion in the field. A running
        Sunshine keeps its already-exec'd binary, so removing the copy while
        the helper is still stopping it is safe.
        """
        decky.logger.info("Uninstalling Decky Sunshine...")
        try:
            self.sunshineController.dispatchUninstallCleanup(
                os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "uninstall-cleanup.log")
            )
        except Exception as e:
            decky.logger.error(f"Error dispatching the uninstall cleanup: {e}")
        try:
            await self.sunshineController.removeBwrapCopy_async()
        except Exception as e:
            decky.logger.error(f"Error removing the bwrap copy during uninstall: {e}")
        decky.logger.info("Decky Sunshine uninstall cleanup done")

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
