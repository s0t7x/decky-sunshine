from py_modules.sunshine import SunshineController
import urllib.request

sun = SunshineController()

isRunning = sun.isRunning()
print("Running: " + str(isRunning))

if(not isRunning):
    sun.start()
    
sun.setAuthHeader("sunshine", "lol")

isAuthorized = sun.isAuthorized()
print("Authorized: " + str(isAuthorized))

res = sun.sendPin("6141")
print(res)

sun.stop()