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

  // State
  const [isSunshineRunning, setIsSunshineRunning] = useState<boolean>(false);
  const [areCredentialsValid, setAreCredentialsValid] = useState<boolean | null>(null);
  // The run state Sunshine is currently transitioning to, or null if no transition is in progress
  const [pendingRunState, setPendingRunState] = useState<boolean | null>(null);
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
    const initialize = async () => {
      await updateSunshineState();
      setIsInitializing(false);
    };

    initialize();
  }, []);

  useEffect(() => {
    refreshVersionInfo(false);
  }, []);

  useEffect(() => {
    // Pause the health check while a transition is in progress;
    // toggleSunshine updates the state itself when it finishes.
    if (pendingRunState !== null) {
      return;
    }

    const healthCheck = setInterval(updateSunshineState, HEALTH_CHECK_INTERVAL);

    return () => clearInterval(healthCheck);
  }, [pendingRunState]);

  const toggleSunshine = async () => {
    const shouldRun = !isSunshineRunning;
    setPendingRunState(shouldRun);
    try {
      // The backend call only returns once Sunshine has actually been
      // started/stopped (or the operation failed or timed out)
      const success = shouldRun ? await backend.startSunshine() : await backend.stopSunshine();
      if (!success) {
        console.error(LOG_TAG, `Failed to ${shouldRun ? "start" : "stop"} Sunshine`);
      }
    } catch (error) {
      console.error(LOG_TAG, "Failed to start/stop Sunshine:", error);
    } finally {
      await updateSunshineState();
      setPendingRunState(null);
    }
  };

  const refreshVersionInfo = async (refreshAppstream: boolean) => {
    setIsRefreshingVersionInfo(true);
    try {
      const versionInfo = await backend.getSunshineVersionInfo(refreshAppstream);
      setSunshineCurrentVersion(versionInfo?.current_version ?? null);
      setSunshineUpdateVersion(versionInfo?.update_version ?? null);
    } finally {
      setIsRefreshingVersionInfo(false);
    }
  };

  // Show spinner while Sunshine state is being updated or an update is in progress
  const isStartingOrStopping = pendingRunState !== null;
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
        label: pendingRunState ? "Starting..." : "Stopping...",
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
            onClick={() => toggleSunshine()}
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
                    try {
                      const success = await backend.updateSunshine();
                      if (success) {
                        setSunshineUpdateVersion(null);
                        setUpdateCheckTriggeredManually(false);
                      }
                      updateSunshineState();
                    } finally {
                      setIsUpdating(false);
                    }
                  }}
                >
                  Update
                </ButtonItem>
              </div>
           : <div style={{ display: "contents" }}>
                {updateCheckTriggeredManually && !isRefreshingVersionInfo && (
                  <span>No update available</span>
                )}
                <ButtonItem
                  disabled={isRefreshingVersionInfo}
                  onClick={async () => {
                    setUpdateCheckTriggeredManually(true);
                    await refreshVersionInfo(true);
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
                    try {
                      const credentials = await backend.getCredentials();
                      setCredentials(credentials);
                      setGetCredentialsReturnedValue(credentials != null);
                    } finally {
                      setIsGettingCredentials(false);
                    }
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
