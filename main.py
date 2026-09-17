import decky

from pathlib import Path
import asyncio
import os
import time

from settings import SettingsManager
from sunshine import SunshineController

class Plugin:
    # Crash watchdog (#112): how often to look whether Sunshine is still there
    # while it should be running, how many restarts to attempt before giving
    # up, and how long a restarted Sunshine has to survive for the next crash
    # to get a fresh set of attempts again. The stable window answers "did the
    # restart actually bring Sunshine back?", not "has this user had trouble
    # today" - two minutes of running is a clear yes, while the crash loop the
    # limit exists for never gets anywhere near it.
    CRASH_WATCH_INTERVAL = 20
    CRASH_RESTART_LIMIT = 3
    CRASH_STABLE_WINDOW = 120

    def __init__(self):
        self.sunshineController = None
        self.settingManager = None
        self._last_is_running = None
        self._last_are_credentials_valid = None
        self._last_version_info = None
        self._crash_watch_task = None
        self._crash_watch_wakeup = None

    async def set_setting(self, key, value):
        return self.settingManager.setSetting(key, value)

    async def get_setting(self, key, default):
        return self.settingManager.getSetting(key, default)

    async def is_sunshine_running(self):
        current_is_running = await self.sunshineController.isSunshineRunning_async()
        if self._last_is_running != current_is_running:
            decky.logger.info(f"Sunshine running state changed: {self._last_is_running if self._last_is_running is not None else 'unknown'} → {current_is_running if current_is_running is not None else 'unknown'}")
            self._last_is_running = current_is_running
        if current_is_running is False:
            self._nudge_crash_watch()
        return current_is_running

    async def are_credentials_valid(self):
        current_are_credentials_valid = await self.sunshineController.areCredentialsValid_async()
        if self._last_are_credentials_valid != current_are_credentials_valid:
            decky.logger.info(f"Credentials valid state changed: {self._last_are_credentials_valid if self._last_are_credentials_valid is not None else 'unknown'} → {current_are_credentials_valid if current_are_credentials_valid is not None else 'unknown'}")
            self._last_are_credentials_valid = current_are_credentials_valid
        return current_are_credentials_valid

    async def start_sunshine(self):
        decky.logger.info("Starting sunshine...")
        res = await self._start_sunshine(record_intent = True)
        decky.logger.info("Sunshine started" if res else "Couldn't start Sunshine")
        return res

    async def restart_sunshine(self):
        """
        Stop and start Sunshine in one backend call. Stopping it from a
        streaming client cuts the very connection the user needs to reach the
        start button again (#97), so the two steps must not be separate
        actions; it is also the one operation that makes a running Sunshine
        pick up config changes the plugin wrote (see get_web_ui_info).
        A failed stop leaves the running instance alone and reports failure.
        """
        decky.logger.info("Restarting sunshine...")
        # The watchdog must not see the intentional gap and restart into it.
        await self._cancel_crash_watch()
        if not await self.sunshineController.stop_async():
            decky.logger.info("Couldn't stop Sunshine for the restart")
            # It is still running and still wanted, so keep watching it.
            self._ensure_crash_watch()
            return False
        res = await self._start_sunshine(record_intent = True)
        decky.logger.info("Sunshine restarted" if res else "Couldn't start Sunshine again after stopping it")
        return res

    async def _start_sunshine(self, record_intent):
        """
        The shared start path of the manual start, the restart and the
        auto-start on load: allow the current LAN origin before Sunshine reads
        its config, track whether the running instance has loaded it, and
        watch a started Sunshine for going away.
        :param record_intent: Whether the outcome becomes the user's run
                              intent (lastRunState). False for starts that
                              only carry out an intent that is already
                              recorded - the auto-start on load and the crash
                              watchdog - so a failed attempt cannot silently
                              turn the auto-start off.
        :return: True if Sunshine is running afterwards, False otherwise
        """
        # Sunshine may have survived a plugin_loader restart; then this is an
        # ensure-only pass and the running instance keeps enforcing the
        # allowances from its own start (see _ensure_csrf_allowed_origin).
        starting = not await self.sunshineController.isSunshineRunning_async()
        added_now = await self._ensure_csrf_allowed_origin()
        res = await self.sunshineController.start_async()
        if starting and res:
            self.settingManager.setSetting("csrfRestartPending", False)
        elif added_now:
            self.settingManager.setSetting("csrfRestartPending", True)
        if record_intent:
            self.settingManager.setSetting("lastRunState", "start" if res else "stop")
        if res:
            self._ensure_crash_watch()
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
        # Stopping is an intent, not a crash - end the watchdog before the
        # process goes away so it cannot restart what the user just stopped.
        await self._cancel_crash_watch()
        res = await self.sunshineController.stop_async()
        if res:
            decky.logger.info("Sunshine stopped")
            self.settingManager.setSetting("lastRunState", "stop")
        else:
            decky.logger.info("Couldn't stop Sunshine")
            self.settingManager.setSetting("lastRunState", "start")
        return res

    def _ensure_crash_watch(self):
        """
        Start the crash watchdog for a Sunshine that is running now, unless it
        is already watching. Called from every path that (re)starts Sunshine,
        including from within the watchdog itself - hence the done() check
        rather than an unconditional create_task.
        """
        if self._crash_watch_task is None or self._crash_watch_task.done():
            self._crash_watch_task = asyncio.get_event_loop().create_task(self._watch_for_crash())

    def _nudge_crash_watch(self):
        """
        Tell the watchdog to look now instead of at the end of its interval.
        The open panel polls every 5 s and therefore notices a gone Sunshine
        long before the watchdog's own tick does - without this the panel sits
        at "Stopped" for up to CRASH_WATCH_INTERVAL while the restart that is
        already decided has not happened yet. Ignored while a failed start is
        being backed off (the watchdog does not listen then), so the panel
        cannot poll the retry limit away.
        """
        if (self._crash_watch_task is not None and not self._crash_watch_task.done()
                and self._crash_watch_wakeup is not None):
            self._crash_watch_wakeup.set()

    async def _cancel_crash_watch(self):
        """
        End the watchdog and wait until it is really gone, so a stop that
        follows cannot race a restart the watchdog already started. Never call
        this from inside the watchdog itself - it would await its own task.
        """
        task = self._crash_watch_task
        self._crash_watch_task = None
        self._crash_watch_wakeup = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _watch_for_crash(self):
        """
        Restart a Sunshine that went away although it should be running (#112).
        There is no toggle for this: lastRunState already records whether the
        user wants Sunshine up, and every intentional stop (stop_sunshine,
        restart_sunshine, update_sunshine) cancels this watcher for the
        duration of the gap it creates. So anything seen here is Sunshine
        dying on its own.

        Restarts are capped: a Sunshine that cannot stay up (a broken
        installation, a missing display) would otherwise be restarted forever,
        each attempt spawning flatpak and re-doing the setuid dance. After
        CRASH_RESTART_LIMIT attempts the watchdog gives up and leaves the
        panel showing "Stopped". Surviving CRASH_STABLE_WINDOW seconds counts
        as recovered, so an unrelated crash hours later gets the full budget
        again.

        Two counters, because they answer different questions: `attempts`
        caps how often we may act inside the stable window, `failures` counts
        only starts that did NOT bring Sunshine up and stretches the wait
        before retrying those. A restart that worked must not slow the next
        check down - the crash after it is a new event, not a retry.
        """
        attempts = 0
        failures = 0
        last_attempt = 0.0
        self._crash_watch_wakeup = asyncio.Event()
        while True:
            self._crash_watch_wakeup.clear()
            if failures:
                await asyncio.sleep(self.CRASH_WATCH_INTERVAL * (2 ** failures))
            else:
                try:
                    await asyncio.wait_for(self._crash_watch_wakeup.wait(), self.CRASH_WATCH_INTERVAL)
                except asyncio.TimeoutError:
                    pass

            # "" is the intent of a fresh install, which _main starts too
            if self.settingManager.getSetting("lastRunState", "") not in ("start", ""):
                return

            if await self.sunshineController.isSunshineRunning_async():
                if attempts and time.monotonic() - last_attempt >= self.CRASH_STABLE_WINDOW:
                    decky.logger.info("Sunshine has been stable since the last restart - resetting the restart count")
                    attempts = 0
                continue

            if attempts >= self.CRASH_RESTART_LIMIT:
                decky.logger.error(
                    f"Sunshine went away again after {attempts} restart attempts - giving up. "
                    "Start it from the plugin panel once the cause is fixed."
                )
                return

            attempts += 1
            last_attempt = time.monotonic()
            decky.logger.warning(f"Sunshine is gone although it should be running - restarting it ({attempts}/{self.CRASH_RESTART_LIMIT})")
            if await self._start_sunshine(record_intent = False):
                failures = 0
                decky.logger.info("Sunshine restarted after it went away")
            else:
                failures += 1
                decky.logger.error("Couldn't restart Sunshine after it went away")

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

    async def get_sunshine_version_info(self):
        versionInfo = await self.sunshineController.getSunshineVersionInfo_async()
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
        # The update stops Sunshine on purpose - the watchdog must not restart
        # it into the running installation.
        await self._cancel_crash_watch()
        res = await self.sunshineController.updateSunshine_async()
        if res:
            self.settingManager.setSetting("csrfRestartPending", False)
            decky.logger.info("Sunshine updated successfully")
        else:
            if added_now:
                self.settingManager.setSetting("csrfRestartPending", True)
            decky.logger.info("Couldn't update Sunshine")
        # Only watch what is actually up: after a failed update Sunshine may be
        # stopped, and restarting a half-updated installation helps nobody.
        if await self.sunshineController.isSunshineRunning_async():
            self._ensure_crash_watch()
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
            # The intent is already recorded, so a failure here must not
            # rewrite it - see _start_sunshine.
            await self._start_sunshine(record_intent = False)

        decky.logger.info("Decky Sunshine loaded")

    async def _unload(self):
        decky.logger.info("Decky Sunshine unloaded")

    async def _uninstall(self):
        """
        Called by the loader when the plugin is being uninstalled (after
        _unload). The loader SIGKILLs the plugin process at the latest ~5 s
        after its stop request, and on the Deck the event loop was observed
        to stop mid-uninstall: a coroutine parked at an await was never
        resumed. Hence the body must not contain a single await - without
        suspension points it runs as one uninterruptible block that needs
        nothing but a live process (blocking the loop is fine, the plugin
        is going away) - and the work is ordered by cost: first dispatch
        the detached helper that stops Sunshine and releases the
        composition override (survives this process, ~2 ms), then remove
        the setuid bwrap copies. Deliberately no in-process stop_async: it
        never ran to completion in the field. A running Sunshine keeps its
        already-exec'd binary, so removing the copy while the helper is
        still stopping it is safe.
        """
        decky.logger.info("Uninstalling Decky Sunshine...")
        try:
            self.sunshineController.dispatchUninstallCleanup(
                os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "uninstall-cleanup.log")
            )
        except Exception as e:
            decky.logger.error(f"Error dispatching the uninstall cleanup: {e}")
        try:
            self.sunshineController.removeBwrapCopy()
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
