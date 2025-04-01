import subprocess
import os
import signal
import base64
import json
import ssl

from urllib.request import Request, HTTPError, HTTPRedirectHandler, build_opener, HTTPSHandler
from http.client import OK, UNAUTHORIZED

def killpg(group) -> None:
    """
    Kill a process group by sending a SIGTERM signal.
    :param group: The process group ID
    """
    try:
        os.killpg(group, signal.SIGTERM)
    except:
        return

def kill(pid) -> None:
    """
    Kill a process by sending a SIGTERM signal.
    :param pid: The process ID
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except:
        return

def createRequest(path, authHeader, data=None) -> Request:
    """
    Create a Request with necessary headers and set the data accordingly.
    :param path: The path of the request
    :param authHeader:  The authorization header data for the request
    :param data: The data to send to the server
    """
    sunshineBaseUrl = "https://127.0.0.1:47990"
    url = sunshineBaseUrl + path
    request = Request(url)
    request.add_header("User-Agent", "decky-sunshine")
    request.add_header("Connection", "keep-alive")
    request.add_header("Accept", "application/json, */*; q=0.01")
    request.add_header("Authorization", authHeader)
    if data:
        request.add_header("Content-Type", "application/json")
        request.data = json.dumps(data).encode('utf-8')
    return request

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class SunshineController:
    shellHandle = None
    controllerStore = None
    isFreshInstallation = False
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
        self.environment_variables["PULSE_SERVER"] = "unix:/run/user/1000/pulse/native"
        self.environment_variables["DISPLAY"] = ":0"
        self.environment_variables["FLATPAK_BWRAP"] = self.environment_variables["DECKY_PLUGIN_RUNTIME_DIR"] + "/bwrap"
        self.environment_variables["LD_LIBRARY_PATH"] = "/usr/lib/:" + self.environment_variables["LD_LIBRARY_PATH"]

    def killShell(self) -> None:
        """
        Kill the shell process if it exists.
        """
        if self.shellHandle is not None:
            killpg(os.getpgid(self.shellHandle.pid))
            self.shellHandle = None

    def killSunshine(self) -> None:
        """
        Kill the Sunshine process if it exists.
        """
        pid = self.getSunshinePID()
        if pid:
            kill(pid)

    def getSunshinePID(self) -> int:
        """
        Get the process ID of the Sunshine process.
        :return: The process ID or None if not found
        """
        result = subprocess.run(["pgrep", "-x", "sunshine"], capture_output=True, text=True)
        if result.returncode == 0:
            sunshinePids = [int(pid) for pid in result.stdout.split()]
            return sunshinePids[0]
        return None

    def setAuthHeader(self, username, password) -> str:
        """
        Set the authentication header for the controller.
        :param username: The username for authentication
        :param password: The password for authentication
        """
        if (len(username) + len(password) < 1):
            return ""
        credentials = f"{username}:{password}"
        base64_credentials = base64.b64encode(credentials.encode('utf-8'))
        auth_header = f"Basic {base64_credentials.decode('utf-8')}"
        return self.setAuthHeaderRaw(auth_header)

    def setAuthHeaderRaw(self, authHeader) -> str:
        self.authHeader = str(authHeader)
        return self.authHeader

    def request(self, path, data=None) -> str | None:
        """
        Make an HTTP request to the Sunshine server.
        :param path: The path of the request
        :param data: The request data (optional)
        :return: The response data as a string
        """
        try:
            request = createRequest(path, self.authHeader, data)
            with self.opener.open(request) as response:
                if response.getcode() != OK:
                    return None
                encoding = response.headers.get_content_charset() or "utf-8"
                content = response.read().decode(encoding)
                return content
        except Exception as e:
            self.logger.info(f"Exception in request to path '{path}' with data '{data}', exception: {e}")
        return None

    def isRunning(self) -> bool:
        """
        Check if the Sunshine process is running.
        :return: True if the process is running, False otherwise
        """
        return self.getSunshinePID() is not None

    def isAuthorized(self) -> bool:
        """
        Check if the controller is authorized to access the Sunshine server.
        :return: True if authorized, False otherwise
        """
        if not self.isRunning:
            return False
        try:
            request = createRequest("/api/apps", self.authHeader)
            with self.opener.open(request) as response:
                return response.getcode() == OK
        except Exception as e:
            if not (isinstance(e, HTTPError) and e.code == UNAUTHORIZED):
                self.logger.info(f"Exception when checking authorization status, exception: {e}")
            return False

    def start(self) -> bool:
        """
        Start the Sunshine process.
        """
        if self.isRunning():
            return True

        # Set the permissions for our bwrap
        try:
            self.shellHandle = subprocess.Popen(['chown', '0:0', self.environment_variables["FLATPAK_BWRAP"]], env=self.environment_variables, user=0, stdin=subprocess.PIPE, stdout=subprocess.PIPE, preexec_fn=os.setsid)
        except Exception as e:
            self.logger.info(f"An error occurred wwith bwrap chown: {e}")
            self.shellHandle = None
            return False
        try:
            _ = subprocess.Popen(['chmod', 'u+s', self.environment_variables["FLATPAK_BWRAP"]], env=self.environment_variables, user=0, stdin=subprocess.PIPE, stdout=subprocess.PIPE, preexec_fn=os.setsid)
        except Exception as e:
            self.logger.info(f"An error occurred with bwrap chmod: {e}")
            self.shellHandle = None
            return False

        # Run Sunshine
        try:
            _ = subprocess.Popen("sh -c 'flatpak run --socket=wayland dev.lizardbyte.app.Sunshine'", env=self.environment_variables, user=0, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, preexec_fn=os.setsid)
        except subprocess.TimeoutExpired:
            self.logger.error("Sunshine start took too long")
            return False
        except Exception as e:
            self.logger.info(f"An error occurred while starting Sunshine: {e}")
            self.shellHandle = None
            return False
        return True

    def stop(self) -> None:
        """
        Stop the Sunshine process and shell process.
        """
        self.killShell()
        self.killSunshine()

    def sendPin(self, pin) -> bool:
        """
        Send a PIN to the Sunshine server.
        :param pin: The PIN to send
        :return: True if the PIN was accepted, False otherwise
        """
        res = self.request("/api/pin", { "pin": pin, "name": "Deck Sunshine Friendly Client Name" })
        if not res:
            return False
        try:
            data = json.loads(res)
            return data["status"] == "true"
        except Exception as e:
            self.logger.info(f"Exception when sending pin, exception: {e}")
            return False

    def ensureDependencies(self) -> bool:
        """
        Ensure that Sunshine and the environment are set up as expected, and
        """
        if self._isBwrapInstalled():
            self.logger.info("Decky Sunshine's copy of bwrap was already obtained.")
        else:
            self.logger.info("Decky Sunshine's copy of bwrap is missing. Obtaining now...'")
            installed = self._installBwrap()
            if not installed:
                self.logger.info("Decky Sunshine's copy of bwrap could not be obtained.")
                return False
            self.logger.info("Decky Sunshine's copy of bwrap obtained successfully.")

        if self._isSunshineInstalled():
            self.logger.info("Sunshine already installed.")
        else:
            self.logger.info("Sunshine not installed. Installing...")
            installed = self._installSunshine()
            if not installed:
                self.logger.info("Sunshine could not be installed.")
                return False
            self.logger.info("Sunshine was installed successfully.")
            self.isFreshInstallation = True

        return True


    def _isSunshineInstalled(self) -> bool:
        # flatpak list --system | grep Sunshine
        try:
            child = subprocess.Popen(["flatpak", "list", "--system"], env=self.environment_variables, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            response, _ = child.communicate()
            response = response.decode("utf-8")  # Decode the bytes output to a string
            for app in response.split("\n"):
                if "Sunshine" in app:
                    return True
            return False
        except:
            return False

    def _isBwrapInstalled(self) -> bool:
        # Look for our own copy of bwrap
        try:
            return os.path.isfile(self.environment_variables["FLATPAK_BWRAP"])
        except Exception as e:
            return False

    def _installSunshine(self) -> bool:
        try:
            child = subprocess.Popen(["flatpak", "install", "--system", "-y", "dev.lizardbyte.app.Sunshine"], env=self.environment_variables,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, _ = child.communicate()

            return child.returncode == 0
        except Exception as e:
            self.logger.info(f"An exception occurred while installing Sunshine: {e}")
            return False

    def _installBwrap(self) -> bool:
        try:
            child = subprocess.Popen(["cp", "/usr/bin/bwrap", self.environment_variables["FLATPAK_BWRAP"]], env=self.environment_variables,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, _ = child.communicate()

            return child.returncode == 0
        except Exception as e:
            self.logger.info(f"An exception occurred while obtaining bwrap: {e}")
            return False

    def setUser(self, newUsername, newPassword, confirmNewPassword, currentUsername = None, currentPassword = None) -> str:
        data =  { "newUsername": newUsername, "newPassword": newPassword, "confirmNewPassword": confirmNewPassword }

        if(currentUsername or currentPassword):
            data += { "currentUsername": currentUsername, "currentPassword": currentPassword }

        res = self.request("/api/password", data)

        if len(res) <= 0:
            return None

        try:
            data = json.loads(res)
            wasUserChanged = data["status"] == "true"
        except:
            return None

        if not wasUserChanged:
            return None

        return self.setAuthHeader(newUsername, newPassword)
