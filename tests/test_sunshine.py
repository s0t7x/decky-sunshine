from py_modules.sunshine import SunshineController
import urllib.request

sun = SunshineController()

isRunning = sun.isRunning()
print("Running: " + str(isRunning))

if(not isRunning):
    sun.start()
    
sun.setAuthHeader("sunshine", "lol2")

isAuthorized = sun.isAuthorized()
print("Authorized: " + str(isAuthorized))

sendPin = sun.sendPin("6141")
print("sendPin: " + str(sendPin))

setUser = sun.setUser("sunshine", "lol2", "sunshine", "lol", "lol")
print("setUser: " + str(setUser))

sun.stop()