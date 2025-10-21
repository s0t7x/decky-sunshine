import { useState, useEffect, VFC } from "react";
import {
  definePlugin,
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Spinner,
  showModal,
} from "decky-frontend-lib";
import { FaSun } from "react-icons/fa";
import backend from "./util/backend";

import { PairingModal } from "./components/PairingModal";
import { CredentialsModal } from "./components/CredentialsModal";
import { LOG_TAG } from "./util/constants";

const Content: VFC = () => {
  const HEALTH_CHECK_INTERVAL = 5000;
  const STATE_UPDATE_INTERVAL = 1000;

  // State
  const [isSunshineRunning, setIsSunshineRunning] = useState<boolean>(false);
  const [areCredentialsValid, setAreCredentialsValid] = useState<boolean | null>(null);
  const [shouldSunshineRun, setShouldSunshineRun] = useState<boolean>(false);
  const [sunshineCurrentVersion, setSunshineCurrentVersion] = useState<string | null>(null);
  const [sunshineUpdateVersion, setSunshineUpdateVersion] = useState<string | null>(null);
  const [updateCheckTriggeredManually, setUpdateCheckTriggeredManually] = useState<boolean>(false);
  const [isUpdating, setIsUpdating] = useState<boolean>(false);
  const [isRefreshingVersionInfo, setIsRefreshingVersionInfo] = useState<boolean>(false);
  const [isInitializing, setIsInitializing] = useState<boolean>(true);
  const [credentials, setCredentials] = useState<{username: string, password: string} | null>(null);
  const [isGettingCredentials, setIsGettingCredentials] = useState<boolean>(false);
  const [getCredentialsReturnedValue, setGetCredentialsReturnedValue] = useState<boolean | null>(null);

  const updateSunshineState = async () => {
    const isSunshineRunning = await backend.isSunshineRunning();
    const areCredentialsValid = await backend.areCredentialsValid();
    setIsSunshineRunning(isSunshineRunning);
    setAreCredentialsValid(areCredentialsValid);
  };

  useEffect(() => {
    const initializeIsSunshineRunning = async () => {
      const isSunshineRunning = await backend.isSunshineRunning();

      // On startup, the backend will load the lastRunState and start Sunshine if it ran before.
      // Thus, we check the state of Sunshine and update the local state accordingly.
      setIsSunshineRunning(isSunshineRunning);
      setShouldSunshineRun(isSunshineRunning);
      setIsInitializing(false);
    };

    initializeIsSunshineRunning();
  }, []);

  useEffect(() => {
    const initializeAreCredentialsValid = async () => {
      const areCredentialsValid = await backend.areCredentialsValid();

      setAreCredentialsValid(areCredentialsValid);
    };

    initializeAreCredentialsValid();
  }, []);

  useEffect(() => {
    refreshVersionInfo();
  }, []);

  useEffect(() => {
    const healthCheck = setInterval(async () => {
      const hasDesiredState = shouldSunshineRun === isSunshineRunning;
      if (hasDesiredState) {
        await updateSunshineState();
      }
    }, HEALTH_CHECK_INTERVAL);

    return () => clearInterval(healthCheck);
  }, []);

  useEffect(() => {
    // Start or stop Sunshine if wanted
    const hasDesiredState = shouldSunshineRun === isSunshineRunning;
    if (hasDesiredState) {
      return;
    }

    const startStopOperation = async () => {
      try {
        shouldSunshineRun ? await backend.startSunshine() : await backend.stopSunshine();
      } catch (error) {
        console.error(LOG_TAG, "Failed to start/stop Sunshine:", error);
        // Reset to the previous state on error
        setShouldSunshineRun(isSunshineRunning);
      }
    };

    startStopOperation();

    // Update state each second till loading is done
    const interval = setInterval(async () => {
      const isSunshineRunning = await backend.isSunshineRunning();
      const hasDesiredState = shouldSunshineRun === isSunshineRunning;
      hasDesiredState ? clearInterval(interval) : updateSunshineState();
    }, STATE_UPDATE_INTERVAL);

    // Cleanup interval to avoid memory leaks
    return () => clearInterval(interval);
  }, [shouldSunshineRun]);

  const refreshVersionInfo = async () => {
    setIsRefreshingVersionInfo(true);
    const versionInfo = await backend.getSunshineVersionInfo();
    setIsRefreshingVersionInfo(false);
    setSunshineCurrentVersion(versionInfo?.current_version ?? null);
    setSunshineUpdateVersion(versionInfo?.update_version ?? null);
  };

  // Show spinner while Sunshine state is being updated or an update is in progress
  const isStartingOrStopping = shouldSunshineRun !== isSunshineRunning;
  const isBusy = isInitializing || isStartingOrStopping || isUpdating;
  const statusInfo = (() => {
    if (isInitializing) {
      return { label: "Checking status...", color: "#888888" };
    }
    if (isUpdating) {
      return { label: "Updating...", color: "orange" };
    }
    if (isStartingOrStopping) {
      return {
        label: shouldSunshineRun ? "Starting..." : "Stopping...",
        color: "orange",
      };
    }
    if (isSunshineRunning) {
      return { label: "Running", color: "#2eaa4f" };
    }
    return { label: "Stopped", color: "#c64040" };
  })();

  return (
    <PanelSection>
      <PanelSectionRow>
        <div style={{ display: "contents" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontWeight: 600,
            }}
          >
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: statusInfo.color,
                boxShadow: `0 0 4px ${statusInfo.color}`,
              }}
            />
            <span>Status: {statusInfo.label}</span>
            {isBusy && <Spinner style={{ width: 14, height: 14 }} />}
          </div>
          <ButtonItem
            disabled={isBusy}
            onClick={() => setShouldSunshineRun(!isSunshineRunning)}
          >
            {isSunshineRunning ? "Stop Sunshine" : "Start Sunshine"}
          </ButtonItem>
        </div>
      </PanelSectionRow>

      {/* Login Section */}
      { areCredentialsValid === false &&
        <PanelSectionRow>
          <div style={{ display: "contents" }}>
                <span>You need to log into Sunshine</span>
                <ButtonItem
                  disabled={!isSunshineRunning || isBusy}
                  onClick={() =>
                    showModal(
                      <CredentialsModal
                        onLogin={async (username: string, password: string) => {
                          try {
                            return await backend.setCredentials(username, password);
                          } catch (error) {
                            console.error(LOG_TAG, "Failed to set credentials:", error);
                            updateSunshineState();
                            return null;
                          }
                        }}
                      />,
                      window
                    )
                  }
                >
                  Login
                </ButtonItem>
              </div>
        </PanelSectionRow>
      }

      {/* Pairing Section */}
      <PanelSectionRow>
        <ButtonItem
            disabled={!areCredentialsValid || !isSunshineRunning || isBusy}
            onClick={() =>
              showModal(
                <PairingModal
                  onPair={async (pin: string, clientName: string) => {
                    try {
                      const success = await backend.pair(pin, clientName);
                    // While testing, sometimes, the Sunshine process stopped when trying
                    // to pair multiple times with a wrong PIN. Thus, it safer to update
                    // the state again for now until we figure out what we are doing wrong
                    // and how to handle this correctly. This only happened one time though,
                    // so it should later be checked if it is actually necessary or helps
                    // at all.
                      updateSunshineState();
                      return success;
                    } catch (error) {
                      console.error(LOG_TAG, "Failed to pair Sunshine:", error);
                      updateSunshineState();
                      return false;
                    }
                  }}
                />,
                window
              )
            }
          >
            Pair Client
          </ButtonItem>
      </PanelSectionRow>

      {/* Update Section */}
      <PanelSectionRow>
        <div style={{ display: "contents" }}>
          <span>Installed Sunshine version: {isRefreshingVersionInfo ? "Checking..." : sunshineCurrentVersion || "Unknown"}</span>
          {isRefreshingVersionInfo && <Spinner style={{ width: 14, height: 14, marginLeft: 8 }} />}
          <br />
          {sunshineUpdateVersion
            ? <div style={{ display: "contents" }}>
                <span style={{ color: "orange" }}>
                  Available Sunshine version: {sunshineUpdateVersion} {(sunshineCurrentVersion === sunshineUpdateVersion && "(Rebuild)")}
                </span>
                <ButtonItem
                  disabled={isStartingOrStopping || isUpdating}
                  onClick={async () => {
                    setIsUpdating(true);
                    const success = await backend.updateSunshine();
                    setIsUpdating(false);
                    if (success) {
                      setSunshineUpdateVersion(null);
                      setUpdateCheckTriggeredManually(false);
                    }
                    updateSunshineState();
                  }}
                >
                  Update
                </ButtonItem>
              </div>
           : <div style={{ display: "contents" }}>
                {updateCheckTriggeredManually && sunshineUpdateVersion == null && (
                  <span>No update available</span>
                )}
                <ButtonItem
                  disabled={isRefreshingVersionInfo}
                  onClick={async () => {
                    setUpdateCheckTriggeredManually(true);
                    await refreshVersionInfo();
                  }}
                >
                  Check for Sunshine update
                </ButtonItem>
              </div>
          }
        </div>
      </PanelSectionRow>

      {/* Credentials Section */}
      <PanelSectionRow>
        <div style={{ display: "contents" }}>
            {isGettingCredentials
              ? <><span>Getting credentials...</span> <Spinner style={{ width: 14, height: 14, marginRight: 8 }} /></>
              : getCredentialsReturnedValue === false
                  ? <span style={{ color: 'red' }}>No credentials stored</span>
                  : credentials &&
                  <>
                    <span>Username: {credentials.username}</span>
                    <br />
                    <span>Password: {credentials.password}</span>
                  </>
            }
            {credentials == null
              ? <ButtonItem
                  disabled={isInitializing || isGettingCredentials}
                  onClick={async () => {
                    setIsGettingCredentials(true);
                    setGetCredentialsReturnedValue(null);
                    const credentials = await backend.getCredentials();
                    setCredentials(credentials);
                    setGetCredentialsReturnedValue(credentials != null);
                    setIsGettingCredentials(false);
                  }}
                >
                  Show credentials
                </ButtonItem>
              : <ButtonItem
                  onClick={() => {
                    setCredentials(null);
                    setGetCredentialsReturnedValue(null);
                  }}
                >
                  Hide credentials
                </ButtonItem>
            }
          </div>
      </PanelSectionRow>
    </PanelSection>
  );
};

export default definePlugin((serverApi: any) => {
  backend.serverAPI = serverApi;

  return {
    title: <div className="Title">Decky Sunshine</div>,
    content: <Content />,
    icon: <FaSun />,
  };
});
