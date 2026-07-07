import shlex
import subprocess
import os
import base64
import json
import ssl
import asyncio
import secrets
import glob
import socket
import pwd
import re

from typing import Sequence
from urllib.error import URLError
from urllib.request import Request, HTTPError, HTTPRedirectHandler, build_opener, HTTPSHandler
from http.client import OK, UNAUTHORIZED
from enum import Enum
from dataclasses import dataclass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class RequestError(Enum):
    UNAUTHORIZED = "unauthorized"
    UNREACHABLE = "unreachable"
    OTHER = "other"

@dataclass(frozen=True)
class RequestResult:
    ok: bool
    data: dict | None
    error: RequestError | None

    @classmethod
    def success(cls, data: dict) -> "RequestResult":
        return cls(ok=True, data=data, error=None)

    @classmethod
    def failure(cls, error: RequestError) -> "RequestResult":
        return cls(ok=False, data=None, error=error)

    def is_unauthorized(self) -> bool:
        return self.error == RequestError.UNAUTHORIZED

    def is_unreachable(self) -> bool:
        return self.error == RequestError.UNREACHABLE

class SunshineController:
    SunshineFlatpakAppId = "dev.lizardbyte.app.Sunshine"
    logger = None

    authHeader = ""

    # Whether the socket-discovery fallback warning has already been logged;
    # kept as state so the retry loop in start_async does not repeat it every second
    _socket_fallback_warned = False

    def __init__(self, logger) -> None:
        """
        Initialize the SunshineController instance.
        """
        assert logger is not None
        self.logger = logger

        # Whether to force gamescope composition (vs direct scanout) while
        # streaming. Applied at the end of start_async and cleared in stop_async,
        # so every start/stop path is covered regardless of caller. See
        # setCompositionForce() for the why.
        self.force_composition = False

        # Watcher task re-asserting the composition override after boot,
        # see _applyCompositionForce()
        self._composition_watch_task = None

        sslContext = ssl.create_default_context()
        sslContext.check_hostname = False
        sslContext.verify_mode = ssl.CERT_NONE

        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=sslContext))

        self.environment_variables = os.environ.copy()
        # A PULSE_SERVER present in the inherited environment can only have been
        # configured deliberately (e.g. via a systemd drop-in for the Decky
        # loader service), so respect it and skip socket discovery entirely.
        external_pulse_server = os.environ.get("PULSE_SERVER")
        if external_pulse_server:
            self.logger.info(f"Using externally configured PULSE_SERVER: {external_pulse_server}")
        else:
            self.environment_variables["PULSE_SERVER"] = f"unix:{self._findPulseAudioSocketPath()}"
        self.environment_variables["DISPLAY"] = ":0"
        # bwrap must be setuid root (Sunshine needs CAP_SYS_ADMIN for KMS/DRM
        # capture, which the setuid copy grants inside the flatpak sandbox) and
        # it is executed by the root plugin. It must therefore live in a
        # directory that (a) sits on a suid-capable filesystem and (b) is
        # writable by root only - otherwise any process running as the deck user
        # could swap the binary and have it executed as root.
        # DECKY_PLUGIN_RUNTIME_DIR is owned by (and writable to) deck, and
        # /run + /tmp are mounted nosuid, so none of those work. /var/lib is
        # root-owned on a suid-capable ext4 mount, so we use a directory there.
        self.environment_variables["FLATPAK_BWRAP"] = "/var/lib/decky-sunshine/bwrap"
        self.environment_variables["LD_LIBRARY_PATH"] = "/usr/lib/:" + self.environment_variables.get("LD_LIBRARY_PATH", "")

    def setCredentials(self, username, password) -> str:
        """
        Set the authentication header for the controller.
        :param username: The username for authentication
        :param password: The password for authentication
        :return: The generated authentication header, or an empty string if username or password is missing
        """
        if not username or not password:
            self.logger.info("No username or password provided for setting AuthHeader")
            return ""

        credentials = f"{username}:{password}"
        base64_credentials = base64.b64encode(credentials.encode('utf-8'))
        auth_header = f"Basic {base64_credentials.decode('utf-8')}"
        self.authHeader = auth_header
        return auth_header

    def getCredentials(self) -> dict | None:
        """
        Get the current username and password from the authHeader.
        :return: A dictionary with 'username' and 'password' keys, or None if authHeader is not set or invalid
        """
        if not self.authHeader.startswith("Basic "):
            self.logger.info("AuthHeader is not set or invalid")
            return None

        base64_credentials = self.authHeader[len("Basic "):]
        try:
            credentials = base64.b64decode(base64_credentials).decode('utf-8')
            username, password = credentials.split(":", 1)
            return {"username": username, "password": password}
        except Exception as e:
            self.logger.exception("An error occurred when decoding credentials from AuthHeader", exc_info=e)
            return None

    def isSunshineRunning(self) -> bool:
        """
        Determine if Sunshine is running by inspecting 'flatpak ps'.
        :return: True if Sunshine is running, False otherwise
        """
        result = self._run_and_capture_stdout(
            ["flatpak", "ps", "--columns=application"],
            context="checking whether Sunshine is running"
        )
        return any(line.strip() == self.SunshineFlatpakAppId for line in (result or "").splitlines())

    async def isSunshineRunning_async(self) -> bool:
        """
        Async variant of isSunshineRunning that doesn't block the event loop.
        :return: True if Sunshine is running, False otherwise
        """
        return await self._to_thread(self.isSunshineRunning)

    async def areCredentialsValid_async(self) -> bool | None:
        """
        Check whether the current credentials are valid by making a request to the Sunshine server.
        :return: True if credentials are valid, False if invalid, None if Sunshine is not running or another error occurred
        """
        if not await self.isSunshineRunning_async():
            return None
        res = await self._request_async("/api/apps")
        if res.ok:
            return True
        elif res.is_unauthorized():
            return False
        return None

    async def ensureDependencies_async(self) -> bool:
        """
        Ensure that Sunshine and the environment are set up as expected, installing Sunshine if necessary.
        :return: True if Sunshine is installed and ready, False otherwise
        """
        if self._wasBwrapCopied():
            self.logger.info("Decky Sunshine's copy of bwrap was already obtained.")
        else:
            self.logger.info("Decky Sunshine's copy of bwrap is missing. Obtaining now...")
            installed = await self._to_thread(self._copyBwrap)
            if not installed:
                self.logger.error("Decky Sunshine's copy of bwrap could not be obtained.")
                return False
            self.logger.info("Decky Sunshine's copy of bwrap obtained successfully.")

        if await self._to_thread(self._isSunshineInstalled):
            self.logger.info("Sunshine already installed.")
            return True
        else:
            self.logger.info("Sunshine not installed. Installing...")
            installed = await self._to_thread(self._installOrUpdateSunshine)
            if not installed:
                self.logger.error("Sunshine could not be installed.")
                return False
            self.logger.info("Sunshine was installed successfully.")
            return await self._initSunshine()

    async def start_async(self) -> bool:
        """
        Start the Sunshine process.
        :return: True if Sunshine was started successfully or is already running, False otherwise
        """
        if await self.isSunshineRunning_async():
            # Already running (e.g. it survived a plugin_loader restart via setsid):
            # still (re)apply the composition override so the atom matches the setting.
            if self.force_composition:
                self.logger.info("Forcing gamescope composition for streaming")
                await self._applyCompositionForce()
            return True

        retry_count = 60
        wait_time = 1

        # If Sunshine is started too early in the boot process, it won't find a display to connect to
        # or the audio subsystem may not be ready. Thus, we check whether both are available before
        # starting Sunshine.
        while retry_count > 0:
            display_available = await self._to_thread(self._isDisplayAvailable)
            audio_available = await self._to_thread(self._isAudioAvailable)

            if display_available and audio_available:
                break

            retry_count -= 1
            if retry_count == 0:
                if not display_available:
                    self.logger.error("Aborting wait for display.")
                    return False
                if not audio_available:
                    self.logger.warning("Audio subsystem not available after waiting. Starting Sunshine anyway...")
                break

            if not display_available:
                self.logger.info(f"Display not available yet. Checking again in {wait_time} {'second' if wait_time == 1 else 'seconds'}")
            if not audio_available:
                self.logger.info(f"Audio subsystem not available yet. Checking again in {wait_time} {'second' if wait_time == 1 else 'seconds'}")

            await asyncio.sleep(wait_time)

        if display_available and audio_available:
            self.logger.info("Display and audio subsystem available")
        elif display_available:
            self.logger.info("Display available")

        bwrap_path = self.environment_variables["FLATPAK_BWRAP"]

        # Re-copy bwrap from the trusted system binary on every start (this also
        # picks up bwrap updates from the OS) and make it setuid root, which
        # Sunshine needs for KMS/DRM capture. This is safe because the target
        # directory is writable by root only (see __init__).
        if not await self._to_thread(self._copyBwrap):
            return False

        if not await self._to_thread(lambda: self._run_and_check(['chown', '0:0', bwrap_path], context="setting owner on bwrap to root")):
            return False

        if not await self._to_thread(lambda: self._run_and_check(['chmod', 'u+s', bwrap_path], context="setting setuid on bwrap")):
            return False

        # Run Sunshine
        try:
            subprocess.Popen(["flatpak", "run", "--system", "--socket=wayland", self.SunshineFlatpakAppId],
                             env=self.environment_variables,
                             start_new_session=True)
        except Exception as e:
            self.logger.exception("An error occurred when starting Sunshine", exc_info=e)
            return False

        # Wait for Sunshine to start
        retry_count = 20
        wait_time = 0.25
        while not await self.isSunshineRunning_async() and retry_count > 0:
            retry_count -= 1
            if retry_count == 0:
                self.logger.error("Aborting wait for Sunshine process to start.")
                return False
            self.logger.info(f"Sunshine process not found yet. Checking again in {wait_time} {'second' if wait_time == 1 else 'seconds'}")
            await asyncio.sleep(wait_time)

        if self.force_composition:
            self.logger.info("Forcing gamescope composition for streaming")
            await self._applyCompositionForce()

        return True

    async def stop_async(self) -> bool:
        """
        Stop the Sunshine process.
        :return: True if Sunshine was stopped successfully or wasn't running, False otherwise
        """
        # Stop the watcher before releasing the override, so it cannot
        # re-assert the old value concurrently to the release below.
        if self._composition_watch_task is not None:
            self._composition_watch_task.cancel()
            try:
                await self._composition_watch_task
            except asyncio.CancelledError:
                pass
            self._composition_watch_task = None

        # Release the gamescope composition override when stopping, so the
        # direct-scanout power optimization is restored once we're not streaming.
        # Only when the override is active: otherwise every stop would spawn a
        # su/xprop subprocess (and log an error on systems where that fails)
        # even though the feature was never enabled. Disabling the toggle while
        # Sunshine is running is already handled live in setForceComposition.
        if self.force_composition:
            await self.setCompositionForce_async(False)

        if not await self.isSunshineRunning_async():
            return True

        await self._to_thread(lambda: self._run_and_check(["flatpak", "kill", self.SunshineFlatpakAppId], context="killing Sunshine via flatpak"))

        retry_count = 20
        wait_time = 0.25
        while await self.isSunshineRunning_async() and retry_count > 0:
            retry_count -= 1
            if retry_count == 0:
                self.logger.error("Aborting wait for Sunshine process to end.")
                return False
            self.logger.info(f"Sunshine process not ended yet. Checking again in {wait_time} {'second' if wait_time == 1 else 'seconds'}")

            await asyncio.sleep(wait_time)

        return True

    def setCompositionForce(self, enabled: bool) -> bool:
        """
        Force gamescope to always composite instead of using its direct-scanout
        (single-plane) optimization, by setting the GAMESCOPE_COMPOSITE_FORCE
        root-window atom on its XWayland display.

        Why this exists: in Game Mode (embedded gamescope) the `--force-composition`
        flag and gamescopectl convars are ignored — root-window atoms override them.
        When gamescope drops to direct scanout of a smaller buffer (e.g. when the
        mouse cursor auto-hides), Sunshine's KMS capture streams that stretched and
        mis-scaled — most visibly when docked, where the image is squeezed into part
        of the external screen with the right side stretched across the rest.
        Forcing composition keeps the captured geometry consistent.

        It is applied on stream start and cleared on stop, so gamescope's
        power-saving direct scanout is only disabled while actually streaming.

        Sunshine runs as root, so the atom must be set as the session user
        on DISPLAY :0.
        """
        value = "1" if enabled else "0"
        username = self._getSessionUsername()
        if not username:
            self.logger.warning(f"No session user found for setting GAMESCOPE_COMPOSITE_FORCE={value}")
            return False
        cmd = [
            "su", username, "-c",
            "DISPLAY=:0 xprop -root -f GAMESCOPE_COMPOSITE_FORCE 32c "
            "-set GAMESCOPE_COMPOSITE_FORCE " + value,
        ]
        return self._run_and_check(
            cmd, context=f"setting GAMESCOPE_COMPOSITE_FORCE={value}"
        )

    def _getSessionUsername(self) -> str | None:
        """
        Determine the user owning the gamescope session. On the Steam Deck this
        is 'deck', but as in the audio socket discovery it must not be
        hardcoded: other systems may use a different user, so fall back to the
        owner of the first regular user's runtime directory.
        :return: The username, or None if no regular user was found
        """
        try:
            return pwd.getpwnam("deck").pw_name
        except KeyError:
            pass

        # Sort numerically by UID for a reproducible search order, as in
        # _expandSocketPattern
        uid_matches = (re.match(r"^/run/user/(\d+)$", path) for path in glob.glob("/run/user/*"))
        uids = sorted(int(match.group(1)) for match in uid_matches if match)
        for uid in uids:
            if uid < 1000:
                continue
            try:
                return pwd.getpwuid(uid).pw_name
            except KeyError:
                continue
        return None

    async def setCompositionForce_async(self, enabled: bool) -> bool:
        """
        Async variant of setCompositionForce that doesn't block the event loop.
        """
        return await self._to_thread(lambda: self.setCompositionForce(enabled))

    async def _applyCompositionForce(self) -> None:
        """
        Apply the composition override and watch it for a bounded window.
        On a cold boot the plugin can win the race against gamescope's own
        session initialization, which (re)creates the GAMESCOPE_COMPOSITE_FORCE
        atom with value 0 and thereby undoes an earlier write. A single write
        is therefore not trustworthy shortly after boot; re-check the atom for
        a while and re-assert it if it was reset.
        """
        await self.setCompositionForce_async(True)
        if self._composition_watch_task is None or self._composition_watch_task.done():
            loop = asyncio.get_event_loop()
            self._composition_watch_task = loop.create_task(self._watchCompositionForce())

    async def _watchCompositionForce(self) -> None:
        # 12 checks every 10 seconds: covers the window between the plugin
        # applying the override early in the boot process and the gamescope
        # session finishing its initialization.
        for _ in range(12):
            await asyncio.sleep(10)
            if not self.force_composition or not await self.isSunshineRunning_async():
                return
            value = await self._to_thread(self._getCompositionForce)
            if value is not None and value != 1:
                self.logger.info("GAMESCOPE_COMPOSITE_FORCE was reset (likely by gamescope session initialization) - re-asserting")
                await self.setCompositionForce_async(True)

    def _getCompositionForce(self) -> int | None:
        """
        Read the current value of the GAMESCOPE_COMPOSITE_FORCE atom.
        :return: The value, 0 if the atom does not exist, or None if it could not be read
        """
        username = self._getSessionUsername()
        if not username:
            return None
        result = self._run_and_capture_stdout(
            ["su", username, "-c", "DISPLAY=:0 xprop -root GAMESCOPE_COMPOSITE_FORCE"],
            context="reading GAMESCOPE_COMPOSITE_FORCE"
        )
        if result is None:
            return None
        value_match = re.search(r"=\s*(\d+)", result)
        # A missing atom means gamescope (re)started without the override
        return int(value_match.group(1)) if value_match else 0

    async def pair_async(self, pin, client_name) -> bool:
        """
        Send a PIN and client name to the Sunshine server.
        :param pin: The PIN to send
        :param client_name: The client_name to send
        :return: True if the Sunshine reported a successful pairing, False otherwise
        """
        if not pin or not client_name:
            self.logger.info("No pin or client name provided for pairing")
            return False

        # /api/pin always returns true when there is a pairing request
        # (https://github.com/LizardByte/Sunshine/issues/3944)
        # Thus, as a workaround, we check whether the client_name
        # is now in the list of clients. As these names
        # do not have to be unique, i.e. a client with the given
        # client_name could already have been in that list, we check
        # whether there now is one more client with that name.
        count_before = await self._getCountOfClientName_async(client_name)
        if count_before is None:
            self.logger.error("Could not get client count before pairing")
            return False

        res = await self._request_async("/api/pin", { "pin": pin, "name": client_name })
        if not res.ok or not res.data.get("status"):
            self.logger.error("Failed to send PIN and client name to Sunshine")
            return False

        # It seems Sunshine needs a moment to update the client list,
        # so we need to wait shortly before checking the client list again
        await asyncio.sleep(1)
        count_after = await self._getCountOfClientName_async(client_name)
        if count_after is None:
            self.logger.error("Could not get client count after pairing")
            return False

        return count_after == count_before + 1

    async def getSunshineVersionInfo_async(self, refresh_appstream: bool = True) -> dict | None:
        """
        Async variant of getSunshineVersionInfo that doesn't block the event loop.
        """
        return await self._to_thread(lambda: self.getSunshineVersionInfo(refresh_appstream))

    def getSunshineVersionInfo(self, refresh_appstream: bool = True) -> dict | None:
        """
        Get the current and available update version of Sunshine.
        :param refresh_appstream: Whether to refresh the Flatpak appstream data (requires network access
                                  and can take a while) before checking for an update
        :return: A dict with keys 'current_version' and 'update_version', or None if an error occurred
        """
        info_result = self._run_and_capture_stdout(
            ["flatpak", "info", self.SunshineFlatpakAppId],
            context="getting Sunshine version info"
        )

        current_version = None
        if info_result:
            for (_, version) in (line.split(":", 1) for line in info_result.splitlines() if "Version:" in line):
                current_version = version.strip()

        if refresh_appstream:
            self._run_and_check(['flatpak', 'update', '--appstream'], context="refreshing Flatpak appstream data")

        result = self._run_and_capture_stdout(
            ["flatpak", "remote-ls", "--app", "--updates", "--system", "--columns=application,version"],
            context="checking for Sunshine updates"
        )

        update_version = None
        if result:
            # The version column can be empty, in which case the line only contains the application id
            for columns in (line.split() for line in result.splitlines() if self.SunshineFlatpakAppId in line):
                update_version = columns[1] if len(columns) > 1 else None

        return {
            "current_version": current_version,
            "update_version": update_version
        }

    async def updateSunshine_async(self) -> bool:
        """
        Update Sunshine to the latest version.
        :return: True if the update was successful, False otherwise
        """
        stopped = await self.stop_async()
        if not stopped:
            self.logger.error("Couldn't stop Sunshine for update")
            return False
        self.logger.info("Sunshine stopped for update. Installing update now...")
        installed = await self._to_thread(self._installOrUpdateSunshine)
        if not installed:
            self.logger.error("Couldn't update Sunshine")
            return False
        self.logger.info("Sunshine updated successfully. Starting Sunshine now...")
        started = await self.start_async()
        if not started:
            self.logger.error("Couldn't start Sunshine after update")
            return False
        self.logger.info("Sunshine started after update")
        return True

    def _run(self, args: Sequence[str], context: str | None = None) -> subprocess.CompletedProcess | None:
        """
        Fire-and-forget wrapper returning CompletedProcess on success (return code == 0), else None.
        Captures stdout/stderr for callers that parse output.
        :param args: The command and its arguments to run
        :param context: A description of the context in which the command is run (for logging purposes)
        :return: The CompletedProcess if the command was successful, None otherwise
        """
        context = context or f"executing {shlex.quote(args[0])}"
        try:
            proc = subprocess.run(
                list(args),
                env=self.environment_variables,
                capture_output=True,
                text=True,
            )
        except Exception as e:
            self.logger.exception(f"An exception occurred when {context}", exc_info=e)
            return None

        if proc.returncode != 0:
            self.logger.error(
                f"The command {context} failed with return code {proc.returncode} and stderr={proc.stderr.strip()}"
            )
            return None
        return proc

    def _run_and_check(self, args: Sequence[str], context: str | None = None) -> bool:
        return self._run(args, context) is not None

    def _run_and_capture_stdout (self, args: Sequence[str], context: str | None = None) -> str | None:
        proc = self._run(args, context)
        return proc.stdout if proc else None

    async def _to_thread(self, func):
        """
        Run a blocking callable in the default executor so it doesn't block the event loop.
        :param func: The callable to run (without arguments; use a lambda to bind arguments)
        :return: The return value of the callable
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, func)

    async def _request_async(self, path, data=None) -> RequestResult:
        """
        Make an async HTTP request to the Sunshine server.
        :param path: The path of the request
        :param data: The request data (optional)
        :return: A RequestResult
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._request, path, data)

    def _request(self, path, data=None) -> RequestResult:
        """
        Make an HTTP request to the Sunshine server.
        :param path: The path of the request
        :param data: The request data (optional)
        :return: A RequestResult
        """
        try:
            request = self._createRequest(path, data)
            # The timeout must be passed here: OpenerDirector.open() unconditionally
            # overwrites a timeout attribute set on the Request object.
            with self.opener.open(request, timeout=5) as response:
                if response.getcode() != OK:
                    self.logger.error(f"Request to path '{path}' with data '{data}' failed with code: {response.getcode()}")
                    return RequestResult.failure(RequestError.OTHER)
                encoding = response.headers.get_content_charset() or "utf-8"
                content = response.read().decode(encoding)
                return RequestResult.success(json.loads(content))

        except HTTPError as e:
            if e.code == UNAUTHORIZED:
                return RequestResult.failure(RequestError.UNAUTHORIZED)
            else:
                self.logger.error(f"HTTP error in request to path '{path}' with data '{data}', code: {e.code}, reason: {e.reason}")
                return RequestResult.failure(RequestError.OTHER)

        except URLError as e:
            # Check if the reason is a connection refusal,
            # which means Sunshine's web server is not running (yet)
            if isinstance(e.reason, ConnectionRefusedError) or (
                isinstance(e.reason, OSError) and getattr(e.reason, "errno", None) == 111
            ):
                self.logger.error(f"Server not reachable when requesting path '{path}' with data '{data}': Connection refused")
                return RequestResult.failure(RequestError.UNREACHABLE)
            else:
                self.logger.error(f"URL error in request to path '{path}' with data '{data}', reason: {e.reason}")
                return RequestResult.failure(RequestError.OTHER)

        except Exception as e:
            self.logger.exception(f"An error occurred when performing a request to path '{path}' with data '{data}'", exc_info=e)
            return RequestResult.failure(RequestError.OTHER)

    def _createRequest(self, path, data=None) -> Request:
        """
        Create a Request with necessary headers and set the data accordingly.
        :param path: The path of the request
        :param data: The data to send to the server (optional)
        :return: A configured Request object
        """
        sunshineBaseUrl = "https://127.0.0.1:47990"
        url = sunshineBaseUrl + path
        request = Request(url)
        request.add_header("User-Agent", "decky-sunshine")
        request.add_header("Connection", "keep-alive")
        request.add_header("Accept", "application/json, */*; q=0.01")
        request.add_header("Authorization", self.authHeader)
        if data:
            request.add_header("Content-Type", "application/json")
            request.data = json.dumps(data).encode('utf-8')
        return request

    def _findPulseAudioSocketPath(self) -> str:
        """
        Find the PulseAudio protocol socket path (on PipeWire systems provided
        by pipewire-pulse). Searches common locations and returns the first
        connectable socket found.
        Note that pipewire-0 sockets are deliberately not considered: PULSE_SERVER
        must point to a socket speaking the PulseAudio protocol, while pipewire-0
        speaks the PipeWire native protocol -- it would accept a connection but be
        unusable for Sunshine's libpulse client.
        :return: The socket path in the format "/path/to/socket", or a default path if not found
        """
        # Try to get XDG_RUNTIME_DIR first, which is the standard location
        xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR")

        # Build socket patterns to check (in order of preference)
        socket_patterns = []

        # If XDG_RUNTIME_DIR is set and it's not root's directory, prioritize it
        if xdg_runtime_dir and '/run/user/0' not in xdg_runtime_dir:
            socket_patterns.append(f"{xdg_runtime_dir}/pulse/native")

        # Next, add the socket directories for the user 'deck'.
        # Note that we determine the UID of the specific user 'deck' here to prioritize it,
        # as on systems other than the Steam Deck another user might be used,
        # and thus the default UID 1000 must not be hardcoded.
        deck_uid = None
        try:
            deck_user = pwd.getpwnam('deck')
            deck_uid = deck_user.pw_uid
            socket_patterns.append(f"/run/user/{deck_uid}/pulse/native")
        except KeyError:
            # User 'deck' does not exist, which is expected on non-Steam Deck systems
            pass

        # Finally, add all /run/user/*/pulse/native socket directories.
        # This will find sockets for any user (1000, 1001, etc.)
        socket_patterns.extend([
            "/run/user/*/pulse/native",
            "/tmp/pulse-*/native",
        ])

        # Build a duplicate-free candidate list before probing: the same path can
        # arrive via several patterns (e.g. XDG_RUNTIME_DIR, the deck user entry
        # and the /run/user/* glob), and each socket should only get one connect
        # attempt and appear only once in the fallback log below.
        candidate_paths = []
        for pattern in socket_patterns:
            matches = self._expandSocketPattern(pattern) if '*' in pattern else [pattern]
            for socket_path in matches:
                if socket_path not in candidate_paths:
                    candidate_paths.append(socket_path)

        existing_not_connectable = []
        for socket_path in candidate_paths:
            # Skip root user's socket (uid 0)
            if '/run/user/0/' in socket_path:
                continue
            if not os.path.exists(socket_path):
                continue
            if self._canConnectToAudioSocket(socket_path):
                # Re-arm the fallback warning so a later regression is reported again
                self._socket_fallback_warned = False
                return socket_path
            existing_not_connectable.append(socket_path)

        # If no usable socket was found, return a default path
        # Try to use deck user's UID if found, otherwise use 1000
        default_uid = deck_uid if deck_uid else 1000
        default_socket = f"/run/user/{default_uid}/pulse/native"
        if existing_not_connectable:
            message = (f"PulseAudio socket(s) found but not accepting connections (yet): "
                       f"{', '.join(existing_not_connectable)} - using default: {default_socket}")
        else:
            message = f"No PulseAudio socket found, using default: {default_socket}"
        if self._socket_fallback_warned:
            self.logger.debug(message)
        else:
            self.logger.warning(message)
            self._socket_fallback_warned = True
        return default_socket

    @staticmethod
    def _expandSocketPattern(pattern: str) -> list:
        """
        Expand a glob pattern into a deterministic list of candidate socket paths.
        glob returns matches in filesystem readdir order, which is effectively
        random; sorting numerically by UID makes the search order reproducible
        across boots and systems.
        Sockets of system users (uid < 1000) are skipped: display-manager
        greeters like gdm/sddm run their own PipeWire/PulseAudio instance whose
        socket must not win over the session user's one.
        :param pattern: The glob pattern to expand
        :return: Matching paths, sorted numerically by UID (non-/run/user
                 matches such as /tmp/pulse-* sort last, lexically)
        """
        matches = []
        for socket_path in glob.glob(pattern):
            uid_match = re.match(r"^/run/user/(\d+)/", socket_path)
            uid = int(uid_match.group(1)) if uid_match else None
            if uid is not None and uid < 1000:
                continue
            matches.append((uid is None, uid or 0, socket_path))
        return [socket_path for _, _, socket_path in sorted(matches)]

    def _canConnectToAudioSocket(self, socket_path: str) -> bool:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                sock.connect(socket_path)
            return True
        except (socket.error, OSError) as e:
            self.logger.debug(f"Cannot connect to audio socket {socket_path}: {e}")
            return False
        except Exception as e:
            self.logger.exception("Unexpected error checking audio availability", exc_info=e)
            return False

    def _isDisplayAvailable(self) -> bool:
        """
        Check whether a display is available.
        :return: True, if a display is available, otherwise False.
        """
        result = self._run_and_capture_stdout(["drm_info", "-j"], context="checking for available display")

        try:
            data = json.loads(result or "{}")
        except Exception as e:
            self.logger.exception("An error occurred when parsing the output of drm_info", exc_info=e)
            data = None

        data = data or {}
        for _, card in data.items():
            for crtc in card.get("crtcs", []):
                # Sunshine checks for the crtcs of a plane with a fb_id that is not 0.
                # https://github.com/LizardByte/Sunshine/blob/6ab24491ed0463eb60c8b902e018d98be3afd06b/src/platform/linux/kmsgrab.cpp#L1620
                # If the fb_id is 0, the crtc will be skipped.
                # If no crtc with an fb_id != 0 is found on any planes of a card,
                # the card won't be added to the available cards.
                # I checked the output of drm_info directly after startup where Sunshine
                # won't be able to start correctly and later when Sunshine would be able,
                # and there was no fb_id != 0 directly after start, but only later. Thus,
                # it should be sufficient to find a single fb_id != 0 to determine that
                # Sunshine should be able to find a display as well.
                if crtc.get("fb_id", 0) != 0:
                    return True
        return False

    def _isAudioAvailable(self) -> bool:
        """
        Check whether the audio subsystem (PulseAudio/PipeWire) is available.
        This checks if the PulseAudio socket exists and is accessible, similar to
        how Sunshine checks for audio availability.
        :return: True if audio is available, otherwise False.
        """
        # An externally configured PULSE_SERVER overrides socket discovery entirely
        external_pulse_server = os.environ.get("PULSE_SERVER")
        if external_pulse_server:
            if external_pulse_server.startswith("unix:"):
                socket_path = external_pulse_server[len("unix:"):]
                if not (os.path.exists(socket_path) and self._canConnectToAudioSocket(socket_path)):
                    self.logger.debug(f"Externally configured PULSE_SERVER is not connectable (yet): {external_pulse_server}")
                    return False
            # Non-unix values (e.g. tcp:host:port) are trusted without a check
            return True

        # Re-evaluate the best socket each time, as the correct socket may not have existed on startup (cold boot)
        pulse_socket_path = self._findPulseAudioSocketPath()

        # Checking whether the socket path exists should only fail in case we had to use a default path
        if not os.path.exists(pulse_socket_path):
            self.logger.debug(f"Audio socket does not exist: {pulse_socket_path}")
            return False

        # Try to connect to the socket to verify it's actually working
        if not self._canConnectToAudioSocket(pulse_socket_path):
            return False

        # Update the environment variable if a different working socket was found so Sunshine will use it
        pulse_env_var = f"unix:{pulse_socket_path}"
        if pulse_env_var != self.environment_variables.get("PULSE_SERVER"):
            self.environment_variables["PULSE_SERVER"] = pulse_env_var
            self.logger.info(f"Updated PULSE_SERVER to {pulse_env_var}")
        return True

    async def _getCountOfClientName_async(self, client_name) -> int | None:
        """
        Get the count of clients with the given client_name.
        :param client_name: The client name to count
        :return: The count of clients with the given name, or None if an error occurred
        """
        res = await self._request_async("/api/clients/list")
        if not res.ok or not res.data.get("status"):
            return None

        return len([client for client in res.data.get("named_certs", []) if client.get("name") == client_name])

    def _wasBwrapCopied(self) -> bool:
        """
        Check if bwrap was copied to the expected location.
        :return: True if bwrap was copied, False otherwise
        """
        try:
            return os.path.isfile(self.environment_variables["FLATPAK_BWRAP"])
        except Exception as e:
            self.logger.exception("An error occurred when checking if bwrap was copied", exc_info=e)
        return False

    def _isSunshineInstalled(self) -> bool:
        result = self._run_and_capture_stdout(
                ["flatpak", "list", "--system", "--columns=application"],
                context="checking whether Sunshine is installed"
            )
        return any(line.strip() == self.SunshineFlatpakAppId for line in (result or "").splitlines())

    def _copyBwrap(self) -> bool:
        """
        Copy the bwrap binary to its dedicated root-owned directory.
        :return: True if the copy was successful, False otherwise
        """
        bwrap_path = self.environment_variables["FLATPAK_BWRAP"]
        bwrap_dir = os.path.dirname(bwrap_path)
        try:
            os.makedirs(bwrap_dir, exist_ok=True)
            # makedirs is subject to the umask, so set the mode explicitly: the
            # directory must not be writable by anyone but root.
            os.chmod(bwrap_dir, 0o755)
        except Exception as e:
            self.logger.exception("An error occurred when creating the bwrap directory", exc_info=e)
            return False
        return self._run_and_check(
                ["cp", "/usr/bin/bwrap", bwrap_path],
                context="copying bwrap to its dedicated directory"
        )

    def _installOrUpdateSunshine(self) -> bool:
        """
        Install or update Sunshine using Flatpak.
        :return: True if the installation or update was successful, False otherwise
        """
        return self._run_and_check(
            ["flatpak", "install", "--system", "--noninteractive", "--or-update", self.SunshineFlatpakAppId],
            context="installing or updating Sunshine via Flatpak"
        )

    async def _initSunshine(self) -> bool:
        """
        Initialize Sunshine after a fresh installation by starting it and setting initial credentials.
        :return: True if initialization was successful, False otherwise
        """
        self.logger.info("Starting Sunshine after fresh installation")
        started = await self.start_async()
        if not started:
            self.logger.error("Sunshine could not be started after installation")
            return False

        self.logger.info("Setting initial credentials")

        username = "decky_sunshine"
        password = secrets.token_urlsafe(6) # Will create a 8 character password
        wait_time = 0.25
        retry_count = 20
        while retry_count > 0:
            res = await self._setUser_async(username, password)
            if res:
                break
            elif res is False:
                self.logger.error("Setting initial credentials failed")
                return False

            retry_count -= 1
            if retry_count == 0:
                self.logger.error("Initial credentials could not be set")
                return False
            self.logger.info(f"Setting initial credentials failed. Trying again in {wait_time} {'second' if wait_time == 1 else 'seconds'}")

            await asyncio.sleep(wait_time)

        self.logger.info(f"Initial credentials set successfully. Username: {username}, Password: {password}")
        return True

    async def _setUser_async(self, newUsername, newPassword, currentUsername = None, currentPassword = None) -> bool | None:
        """
        Set a new username and password for Sunshine.
        :param newUsername: The new username to set
        :param newPassword: The new password to set
        :param currentUsername: The current username (optional)
        :param currentPassword: The current password (optional)
        :return: True if the user was changed successfully, False if the change failed, None if no response was received
        """
        data = {
            "newUsername": newUsername,
            "newPassword": newPassword,
            "confirmNewPassword": newPassword,
        }

        if currentUsername or currentPassword:
            data["currentUsername"] = currentUsername
            data["currentPassword"] = currentPassword

        res = await self._request_async("/api/password", data)

        if not res.ok:
            self.logger.error("No response received while setting user")
            return None

        if not res.data.get("status"):
            self.logger.error("User was not changed")
            return False

        self.setCredentials(newUsername, newPassword)

        return True
