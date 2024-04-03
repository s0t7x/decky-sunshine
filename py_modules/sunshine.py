import subprocess
import os
import signal
import base64
import json
import ssl

from urllib.request import urlopen, Request

def find_process_ids_by_name(name):
    """
    Find the process IDs of running processes with the given name.
    :param name: The name of the process to search for
    :return: A list of process IDs (PIDs)
    """
    child = subprocess.Popen(['pgrep', '-f', name], stdout=subprocess.PIPE, shell=False)
    response = child.communicate()[0]
    return [int(pid) for pid in response.split()]

def killpg(group):
    """
    Kill a process group by sending a SIGTERM signal.
    :param group: The process group ID
    """
    try:
        os.killpg(group, signal.SIGTERM)
    except:
        return

def kill(pid):
    """
    Kill a process by sending a SIGTERM signal.
    :param pid: The process ID
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except:
        return

class SunshineController:
    shellHandle = None
    controllerStore = None
    sslContext = None
    
    needsAuth = True
    authHeader = ""
    
    sunshineBaseUrl = "https://127.0.0.1:47990"

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
        pid = self.getPID()
        if pid is not None:
            kill(pid)

    def getPID(self) -> list[str] | None:
        """
        Get the process ID of the Sunshine process.
        :return: The process ID or None if not found
        """
        sunshinePids = find_process_ids_by_name("sunshine")
        if len(sunshinePids) > 0:
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
    
    def setAuthHeaderRaw(self, authHeader):
        self.authHeader = str(authHeader)
        self.needsAuth = False
        return self.authHeader

    def __init__(self) -> None:
        """
        Initialize the SunshineController instance.
        """
        self.sslContext = ssl.create_default_context()
        self.sslContext.check_hostname = False
        self.sslContext.verify_mode = ssl.CERT_NONE

    def request(self, path, method, data=None) -> str:
        """
        Make an HTTP request to the Sunshine server.
        :param path: The path of the request
        :param method: The HTTP method (GET, POST, etc.)
        :param data: The request data (optional)
        :return: The response data as a string
        """
        url = self.sunshineBaseUrl + path
        try:
            request = Request(url, data=data, method=method)
            request.add_header("User-Agent", "decky-sunshine")
            request.add_header("Connection", "keep-alive")
            request.add_header("Accept", "application/json, */*; q=0.01")
            request.add_header("Authorization", self.authHeader)
            if method == "POST":
                request.add_header("Content-Type", "application/json")
                request.data = json.dumps(data).encode('utf-8')
            with urlopen(request, context=self.sslContext) as response:
                json_response = response.read().decode()
                response.close()
                return str(json_response)
        except:
            return ""
        
    def requestRaw(self, path, method, data=None) -> str:
        url = self.sunshineBaseUrl + path
        try:
            request = Request(url, data=None, method=method, unverifiable=True)
            request.add_header("User-Agent", "decky-sunshine")
            request.add_header("Connection", "keep-alive")
            request.add_header("Accept", "application/json, */*; q=0.01")
            request.add_header("Authorization", self.authHeader)
            if method == "POST":
                request.add_header("Content-Type", "application/json")
                request.data = json.dumps(data).encode('utf-8')
            response = urlopen(request, context=self.sslContext)
            return response
        except Exception as e:
            return None

    def isRunning(self) -> bool:
        """
        Check if the Sunshine process is running.
        :return: True if the process is running, False otherwise
        """
        return self.getPID() is not None

    def isAuthorized(self) -> bool:
        """
        Check if the controller is authorized to access the Sunshine server.
        :return: True if authorized, False otherwise
        """
        res = self.requestRaw("/api/apps", "GET")
        if(res):
            res.close()
            return res.status == 200
        return False

    def start(self) -> bool:
        """
        Start the Sunshine process.
        :return: True if the process was started successfully, False otherwise
        """
        if self.isRunning():
            return False
        try:
            my_env = os.environ.copy()
            my_env["PULSE_SERVER"] = "unix:/run/user/1000/pulse/native"
            self.shellHandle = subprocess.Popen("sh -c 'flatpak run --socket=wayland dev.lizardbyte.app.Sunshine'", env=my_env, user=0, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, preexec_fn=os.setsid)
        except Exception as e:
            print(f"An error occurred while starting Sunshine: {e}")
            self.shellHandle = None
            return False
        return True

    def stop(self):
        """
        Stop the Sunshine process and shell process.
        """
        self.killShell()
        self.killSunshine()

    def sendPin(self, pin):
        """
        Send a PIN to the Sunshine server.
        :param pin: The PIN to send
        :return: True if the PIN was accepted, False otherwise
        """
        res = self.request("/api/pin", "POST", { "pin": pin })
        if len(res) > 0:
            try:
                data = json.loads(res)
                if data["status"] == "true":
                    return True
            except:
                return False
        return False
    
    def isInstalled(self) -> bool:
        # flatpak list --system | grep Sunshine
        try:
            child = subprocess.Popen(["flatpak", "list", "--system"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            response, _ = child.communicate()
            response = response.decode("utf-8")  # Decode the bytes output to a string
            for app in response.split("\n"):
                if "Sunshine" in app:
                    return True
        except:
            return False
        return False
        
    def install(self) -> bool:
        try:
            child = subprocess.Popen(["flatpak", "install", "--system", "-y", "dev.lizardbyte.app.Sunshine"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = child.communicate()

            if child.returncode != 0:
                return False
            
            return True

        except Exception as e:
            return False
        
    def setUser(self, newUsername, newPassword, confirmNewPassword, currentUsername = None, currentPassword = None) -> bool:
        data =  { "newUsername": newUsername, "newPassword": newPassword, "confirmNewPassword": confirmNewPassword }
        if(currentUsername or currentPassword):
            data += { "currentUsername": currentUsername, "currentPassword": currentPassword }
        res = self.request("/api/password", "POST", data)
        if len(res) > 0:
            try:
                data = json.loads(res)
                if data["status"] == "true":
                    return True
            except:
                return False
        return False