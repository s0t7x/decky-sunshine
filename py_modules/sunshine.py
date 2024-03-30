import subprocess
import os
import signal
from urllib.request import urlopen, Request
import base64
import json

def find_process_ids_by_name(name):
    child = subprocess.Popen(['pgrep', '-f', name], stdout=subprocess.PIPE, shell=False)
    response = child.communicate()[0]
    return [int(pid) for pid in response.split()]

def killpg(group):
    os.killpg(group, signal.SIGTERM)

def kill(pid):
    os.kill(pid, signal.SIGTERM)

class ControllerStore:
    needsAuth = True
    authHeader = ""

class SunshineController:
    shellHandle = None
    controllerStore = None
    
    def killShell(self) -> None:
        if self.shellHandle is not None:
            killpg(os.getpgid(self.shellHandle.pid))
            self.shellHandle = None
        
    def killSunshine(self) -> None:
        pid = self.getPID()
        if pid is not None:
            kill(pid)
    
    def getPID(self) -> list[str] | None:
        sunshinePids = find_process_ids_by_name("sunshine")
        if len(sunshinePids) > 0:
            return sunshinePids[0]
        return None
    
    def setAuthHeader(self, username, password) -> None:
        credentials = f"{username}:{password}"
        base64_credentials = base64.b64encode(credentials.encode("utf-8"))
        self.controllerStore.authHeader = f"Basic {base64_credentials.decode('utf-8')}"
        self.controllerStore.needsAuth = False
        self.saveStateToDisk()
    
    def __init__(self) -> None:
        # load controller store from disk
        if self.loadStateFromDisk() is not True:
            self.controllerStore = ControllerStore()
        # instead here is test stuff now
        # TODO: REMOVE DANGEROUS!!!
        
    def loadStateFromDisk(self) -> bool:
        # TODO: implement
        return False    
        
    def saveStateToDisk(self) -> bool:
        # TODO: implement
        return False
    
    def request(self, path, method, data = {}) -> str:
        url = "http://localhost:47990" + path
        try:
            request = Request(url, method=method)
            request.add_header("Authorization", self.authHeader)
            if method is "POST":
                request.data = data
            with urlopen(request) as response:
                json = response.read().decode()
            return str(json)
        except:
            return ""
    
    def isRunning(self) -> bool:
        return self.getPID() is not None
    
    def isAuthorized(self) -> bool:
        res = self.request("", "GET")
        return len(res) > 0
    
    def start(self) -> bool:
        if(self.isRunning()):
            return False
        try:
            self.shellHandle = subprocess.Popen("sh -c 'PULSE_SERVER=unix:$(pactl info | awk '/Server String/{print$3}') flatpak run dev.lizardbyte.app.Sunshine -0'", user=0, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, preexec_fn=os.setsid)
        except:
            self.shellHandle = None
            return False
        else:
            return True
    
    def stop(self):
        self.killShell()
        self.killSunshine()  
    
    def sendPin(self, pin) -> bool:
        res = self.request("/api/pin", "POST", { "pin": pin})
        if len(res) > 0:
            data = json.loads(res)
            return data['status']
        else:
            return False