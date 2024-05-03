import React, { useState, useEffect, VFC } from "react";
import {
  ToggleField,
  definePlugin,
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Spinner,
  Navigation,
  TextField,
  QuickAccessTab,
} from "decky-frontend-lib";
import { FaSun } from "react-icons/fa";
import backend from "./util/backend";

import { PINInput } from "./components/PINInput";
import { PasswordInput } from "./components/PasswordInput";

const Content: VFC<{ serverAPI: any }> = ({ serverAPI }) => {
  // State variables
  const [sunshineIsRunning, setSunshineIsRunning] = useState<boolean>(false);
  const [sunshineIsAuthorized, setSunshineIsAuthorized] = useState<boolean>(false);
  const [wantToggleSunshine, setWantToggleSunshine] = useState<boolean>(false);
  const [localPin, setLocalPin] = useState("");

  // Function to fetch Sunshine state from the backend
  const updateSunshineState = async () => {
    const authed = await backend.sunshineIsAuthorized();
    setSunshineIsAuthorized(authed);

    const running = await backend.sunshineIsRunning();
    setSunshineIsRunning(running);

    setWantToggleSunshine(running)
  };

  useEffect(() => {
    // Update Sunshine state when the component mounts
    updateSunshineState()
  }, []);

  useEffect(() => {
    // Start or stop Sunshine process based on wantToggleSunshine state
    if (wantToggleSunshine !== sunshineIsRunning) {
      if (wantToggleSunshine) {
        backend.sunshineStart();
      } else {
        backend.sunshineStop();
      }
      // Update state each 2 seconds till loading is done
      const interval = setInterval(() => {
        if (wantToggleSunshine !== sunshineIsRunning) {
          updateSunshineState();
        } else {
          clearInterval(interval)
        }
      }, 2000);
      // Cleanup interval to avoid memory leaks
      return () => clearInterval(interval);
    }
    return () => { }
  }, [wantToggleSunshine]);

  // Show spinner while Sunshine state is being updated
  if (wantToggleSunshine !== sunshineIsRunning) {
    return <Spinner />;
  }

  return (
    <PanelSection>
      <PanelSectionRow>
        {/* Toggle field to enable/disable Sunshine */}
        <ToggleField
          label="Enabled"
          checked={wantToggleSunshine}
          onChange={setWantToggleSunshine}
        />
      </PanelSectionRow>
      {/* Render PIN input if Sunshine is authorized */}
      {sunshineIsAuthorized ? (
        sunshineIsRunning && (
          <PINInput
            value={localPin}
            key="pin"
            onChange={setLocalPin}
            label="Enter PIN"
            onSend={() => {
              backend.sunshineSendPin(localPin);
              setLocalPin("");
            }}
            sendLabel="Pair"
          />
        )
      ) : (
        // Render login button if Sunshine is not authorized
        sunshineIsRunning && (
          <PanelSectionRow>
            <p>You need to log into Sunshine</p>
            <ButtonItem
              onClick={() => {
                Navigation.CloseSideMenus();
                Navigation.Navigate("/sunshine-login");
              }}
            >
              Login
            </ButtonItem>
          </PanelSectionRow>
        )
      )}
    </PanelSection>
  );
};

const DeckySunshineLogin: VFC = () => {
  // State variables for local username and password
  const [localUsername, setLocalUsername] = useState(localStorage.getItem("decky_sunshine:localUsername") || "");
  const [localPassword, setLocalPassword] = useState("");

  return (
    <div style={{ marginTop: "50px", color: "white" }}>
      {/* Input fields for username and password */}
      <TextField
        label="Username"
        value={localUsername}
        onChange={(e) => setLocalUsername(e.target.value)}
      />
      <PasswordInput
        label="Password"
        value={localPassword}
        onChange={(value) => setLocalPassword(value)}
      />
      {/* Button to not accidentally being forced to overwrite existing credentials */}
      <ButtonItem
        onClick={() => {
          Navigation.NavigateBack();
          Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky);
        }}>
        Cancel
      </ButtonItem>
      {/* Button to login with entered credentials */}
      <ButtonItem
        onClick={() => {
          // Store username in localStorage
          localStorage.setItem("decky_sunshine:localUsername", localUsername);
          Navigation.NavigateBack();
          // Set authorization header and open Quick Access menu
          backend.sunshineSetAuthHeader(localUsername, localPassword);
          Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky);
        }}
        disabled={localUsername.length < 1 || localPassword.length < 1}
      >
        Login
      </ButtonItem>
    </div>
  );
};

// Define plugin
export default definePlugin((serverApi: any) => {
  // Add route for Sunshine login
  serverApi.routerHook.addRoute("/sunshine-login", DeckySunshineLogin, {
    exact: true,
  });

  // Set server API for backend
  backend.serverAPI = serverApi;

  return {
    title: <div className="Title">Decky Sunshine</div>,
    content: <Content serverAPI={serverApi} />,
    icon: <FaSun />,
    // Remove route on dismount to avoid memory leaks
    onDismount() {
      serverApi.routerHook.removeRoute("/sunshine-login");
    },
  };
});
