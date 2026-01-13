import shlex
import subprocess
import os
import base64
import json
import ssl
import asyncio
import secrets

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

    def __init__(self, *args, **kwargs):
        raise RuntimeError("Use factory methods: RequestResult.success() or RequestResult.error()")

    @classmethod
    def success(cls, data: dict):
        self = object.__new__(cls)
        object.__setattr__(self, "ok", True)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "error", None)
        return self

    @classmethod
    def error(cls, error: RequestError):
        self = object.__new__(cls)
        object.__setattr__(self, "ok", False)
        object.__setattr__(self, "data", None)
        object.__setattr__(self, "error", error)
        return self

    def is_unauthorized(self) -> bool:
        return self.error == RequestError.UNAUTHORIZED

    def is_unreachable(self) -> bool:
        return self.error == RequestError.UNREACHABLE

class SunshineController:
    SunshineFlatpakAppId = "dev.lizardbyte.app.Sunshine"
    logger = None

    authHeader = ""

    def __init__(self, logger) -> None:
        """
        Initialize the SunshineController instance.
        """
        assert logger is not None
        self.logger = logger

        sslContext = ssl.create_default_context()
        sslContext.check_hostname = False
        sslContext.verify_mode = ssl.CERT_NONE

        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=sslContext))

        self.environment_variables = os.environ.copy()
        self.environment_variables["PULSE_SERVER"] = self._findPulseAudioSocket()
        self.environment_variables["DISPLAY"] = ":0"
        self.environment_variables["FLATPAK_BWRAP"] = self.environment_variables.get("DECKY_PLUGIN_RUNTIME_DIR", "") + "/bwrap"
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
        return result and any(line.strip() == self.SunshineFlatpakAppId for line in result.splitlines())

    async def areCredentialsValid_async(self) -> bool | None:
        """
        Check whether the current credentials are valid by making a request to the Sunshine server.
        :return: True if credentials are valid, False if invalid, None if Sunshine is not running or another error occurred
        """
        if not self.isSunshineRunning():
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
            installed = self._copyBwrap()
            if not installed:
                self.logger.error("Decky Sunshine's copy of bwrap could not be obtained.")
                return False
            self.logger.info("Decky Sunshine's copy of bwrap obtained successfully.")

        if self._isSunshineInstalled():
            self.logger.info("Sunshine already installed.")
            return True
        else:
            self.logger.info("Sunshine not installed. Installing...")
            installed = self._installOrUpdateSunshine()
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
        if self.isSunshineRunning():
            return True

        retry_count = 60
        wait_time = 1

        # If Sunshine is started too early in the boot process, it won't find a display to connect to
        # or the audio subsystem may not be ready. Thus, we check whether both are available before
        # starting sunshine.
        while retry_count > 0:
            display_available = self._isDisplayAvailable()
            audio_available = self._isAudioAvailable()

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
                self.logger.info(f"No display available yet. Checking again in {wait_time} {'second' if wait_time == 1 else 'seconds'}")
            if not audio_available:
                self.logger.info(f"Audio subsystem not available yet. Checking again in {wait_time} {'second' if wait_time == 1 else 'seconds'}")

            await asyncio.sleep(wait_time)

        if display_available and audio_available:
            self.logger.info("Display and audio subsystem available")
        elif display_available:
            self.logger.info("Display available")

        # Set the permissions for our bwrap
        bwrap_path = self.environment_variables["FLATPAK_BWRAP"]

        if not self._run_and_check(['chown', '0:0', bwrap_path], context="setting owner on bwrap to root"):
            return False

        if not self._run_and_check(['chmod', 'u+s', bwrap_path], context="setting setuid on bwrap"):
            return False

        # Run Sunshine
        try:
            subprocess.Popen(f"sh -c 'flatpak run --socket=wayland {self.SunshineFlatpakAppId}'",
                             env=self.environment_variables,
                             shell=True,
                             preexec_fn=os.setsid)
        except Exception as e:
            self.logger.exception("An error occurred when starting Sunshine", exc_info=e)
            return False

        # Wait for Sunshine to start
        retry_count = 20
        wait_time = 0.25
        while not self.isSunshineRunning() and retry_count > 0:
            retry_count -= 1
            if retry_count == 0:
                self.logger.error("Aborting wait for Sunshine process to start.")
                return False
            self.logger.info(f"Sunshine process not found yet. Checking again in {wait_time} {'second' if wait_time == 1 else 'seconds'}")
            await asyncio.sleep(wait_time)

        return True

    async def stop_async(self) -> bool:
        """
        Stop the Sunshine process.
        :return: True if Sunshine was stopped successfully or wasn't running, False otherwise
        """
        if not self.isSunshineRunning():
            return True

        self._run_and_check(["flatpak", "kill", self.SunshineFlatpakAppId], context="killing Sunshine via flatpak")

        retry_count = 20
        wait_time = 0.25
        while self.isSunshineRunning() and retry_count > 0:
            retry_count -= 1
            if retry_count == 0:
                self.logger.error("Aborting wait for Sunshine process to end.")
                return False
            self.logger.info(f"Sunshine process not ended yet. Checking again in {wait_time} {'second' if wait_time == 1 else 'seconds'}")

            await asyncio.sleep(wait_time)

        return True

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

    def getSunshineVersionInfo(self) -> dict | None:
        """
        Get the current and available update version of Sunshine.
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

        self._run_and_check(['flatpak', 'update', '--appstream'], context="refreshing Flatpak appstream data")

        result = self._run_and_capture_stdout(
            ["flatpak", "remote-ls", "--app", "--updates", "--system", "--columns=application,version"],
            context="checking for Sunshine updates"
        )

        update_version = None
        if result:
            for (_, version) in (line.split() for line in result.splitlines() if self.SunshineFlatpakAppId in line):
                update_version = version.strip()

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
        installed = self._installOrUpdateSunshine()
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
            with self.opener.open(request) as response:
                if response.getcode() != OK:
                    self.logger.error(f"Request to path '{path}' with data '{data}' failed with code: {response.getcode()}")
                    return RequestResult.error(RequestError.OTHER)
                encoding = response.headers.get_content_charset() or "utf-8"
                content = response.read().decode(encoding)
                return RequestResult.success(json.loads(content))

        except HTTPError as e:
            if e.code == UNAUTHORIZED:
                return RequestResult.error(RequestError.UNAUTHORIZED)
            else:
                self.logger.error(f"HTTP error in request to path '{path}' with data '{data}', code: {e.code}, reason: {e.reason}")
                return RequestResult.error(RequestError.OTHER)

        except URLError as e:
            # Check if the reason is a connection refusal,
            # which means Sunshine's web server is not running (yet)
            if isinstance(e.reason, ConnectionRefusedError) or (
                isinstance(e.reason, OSError) and getattr(e.reason, "errno", None) == 111
            ):
                self.logger.error(f"Server not reachable when requesting path '{path}' with data '{data}': Connection refused")
                return RequestResult.error(RequestError.UNREACHABLE)
            else:
                self.logger.error(f"URL error in request to path '{path}' with data '{data}', reason: {e.reason}")
                return RequestResult.error(RequestError.OTHER)

        except Exception as e:
            self.logger.exception(f"An error occurred when performing a request to path '{path}' with data '{data}'", exc_info=e)
            return RequestResult.error(RequestError.OTHER)

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
        request.timeout = 5
        request.add_header("User-Agent", "decky-sunshine")
        request.add_header("Connection", "keep-alive")
        request.add_header("Accept", "application/json, */*; q=0.01")
        request.add_header("Authorization", self.authHeader)
        if data:
            request.add_header("Content-Type", "application/json")
            request.data = json.dumps(data).encode('utf-8')
        return request

    def _findPulseAudioSocket(self) -> str:
        """
        Find the PulseAudio/PipeWire socket path.
        Searches common locations and returns the first valid socket found.
        :return: The socket path in the format "unix:/path/to/socket", or a default path if not found
        """
        import glob
        import pwd

        # Try to get XDG_RUNTIME_DIR first, which is the standard location
        xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR")

        # Build socket patterns to check (in order of preference)
        socket_patterns = []

        # If XDG_RUNTIME_DIR is set and it's not root's directory, prioritize it
        if xdg_runtime_dir and '/run/user/0' not in xdg_runtime_dir:
            socket_patterns.extend([
                f"{xdg_runtime_dir}/pulse/native",
                f"{xdg_runtime_dir}/pipewire-0",
            ])

        # Try to find the deck user's UID
        deck_uid = None
        try:
            deck_user = pwd.getpwnam('deck')
            deck_uid = deck_user.pw_uid
            socket_patterns.extend([
                f"/run/user/{deck_uid}/pulse/native",
                f"/run/user/{deck_uid}/pipewire-0",
            ])
        except KeyError:
            pass

        # Search all /run/user/*/pulse/native and /run/user/*/pipewire-0 directories
        # This will find sockets for any user (1000, 1001, etc.)
        socket_patterns.extend([
            "/run/user/*/pulse/native",
            "/run/user/*/pipewire-0",
            "/tmp/pulse-*/native",
        ])

        for pattern in socket_patterns:
            # Use glob to expand wildcards
            matches = glob.glob(pattern) if '*' in pattern else [pattern]
            for socket_path in matches:
                # Skip root user's socket (uid 0)
                if '/run/user/0/' in socket_path:
                    continue
                if os.path.exists(socket_path):
                    self.logger.info(f"Found PulseAudio socket at: {socket_path}")
                    return f"unix:{socket_path}"

        # If no socket found, return a default path
        # Try to use deck user's UID if found, otherwise use 1000
        default_uid = deck_uid if deck_uid else 1000
        default_socket = f"unix:/run/user/{default_uid}/pulse/native"
        self.logger.warning(f"No PulseAudio socket found, using default: {default_socket}")
        return default_socket

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

        data = data or {}
        for _, card in data.items():
            for connector in card.get("crtcs", []):
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
                if connector.get("fb_id", 0) != 0:
                    return True
        return False

    def _isAudioAvailable(self) -> bool:
        """
        Check whether the audio subsystem (PulseAudio/PipeWire) is available.
        This checks if the PulseAudio socket exists and is accessible, similar to
        how Sunshine checks for audio availability.
        :return: True if audio is available, otherwise False.
        """
        import socket

        # Dynamically search for the socket each time, as it may not exist during cold boot
        pulse_socket_uri = self._findPulseAudioSocket()
        
        # Update the environment variable if a different socket was found
        if pulse_socket_uri != self.environment_variables.get("PULSE_SERVER"):
            self.environment_variables["PULSE_SERVER"] = pulse_socket_uri
            self.logger.info(f"Updated PULSE_SERVER to: {pulse_socket_uri}")

        # Remove the "unix:" prefix if present
        pulse_socket = pulse_socket_uri[5:] if pulse_socket_uri.startswith("unix:") else pulse_socket_uri

        # Check if the socket file exists
        if not os.path.exists(pulse_socket):
            self.logger.debug(f"Audio socket does not exist: {pulse_socket}")
            return False

        # Try to connect to the socket to verify it's actually working
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect(pulse_socket)
            sock.close()
            return True
        except (socket.error, OSError) as e:
            self.logger.debug(f"Cannot connect to audio socket {pulse_socket}: {e}")
            return False
        except Exception as e:
            self.logger.exception(f"Unexpected error checking audio availability", exc_info=e)
            return False

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
        return result and any(line.strip() == self.SunshineFlatpakAppId for line in result.splitlines())

    def _copyBwrap(self) -> bool:
        """
        Copy the bwrap binary to the expected location.
        :return: True if the copy was successful, False otherwise
        """
        return self._run_and_check(
                ["cp", "/usr/bin/bwrap", self.environment_variables["FLATPAK_BWRAP"]],
                context="copying bwrap to Decky Plugin Runtime directory"
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
