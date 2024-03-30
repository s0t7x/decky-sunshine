import {
  ToggleField,
  definePlugin,
  PanelSection,
  PanelSectionRow,
  ServerAPI,
  staticClasses,
  ButtonItem,
  Spinner,
  // Navigation,
  TextField,
} from "decky-frontend-lib";
import { VFC, useEffect, useState } from "react";
import { FaSun } from "react-icons/fa";
import { NumpadInput } from "./components/NumpadInput";

const Content: VFC<{ serverAPI: ServerAPI }> = ({ serverAPI }) => {
  const [sunshineIsRunning, setSunshineIsRunning] = useState<boolean>(false);
  const [sunshineIsAuthorized, setSunshineIsAuthorized] = useState<boolean>(false);

  const [wantToggleSunshine, setWantToggleSunshine] = useState<boolean>(false);

  const [localPin, setLocalPin] = useState("");

  const [localUsername, setLocalUsername] = useState("sunshine");
  const [localPassword, setLocalPassword] = useState("");

  const sendPin = async () => {
    const result = await serverAPI.callPluginMethod<any, number>(
      "sendPin",
      {
        pin: localPin
      }
    );
    console.log("[SUN]", "sendPin result", result)
  }

  const sunshineCheckRunning = async () => {
    const result = await serverAPI.callPluginMethod<any, number>(
      "sunshineIsRunning",
      {
      }
    );
    console.log("[SUN]", "sunshineCheckRunning result", result)
    if (result.success) {
      setSunshineIsRunning(Boolean(result.result));
    } else {
      setSunshineIsRunning(false);
    }
  };

  const sunshineCheckAuthorized = async () => {
    const result = await serverAPI.callPluginMethod<any, number>(
      "sunshineIsAuthorized",
      {
      }
    );
    console.log("[SUN]", "sunshineCheckAuthorized result", result)
    if (result.success) {
      setSunshineIsAuthorized(Boolean(result.result));
    } else {
      setSunshineIsAuthorized(false);
    }
  };

  const setAuthHeader = async () => {
    const result = await serverAPI.callPluginMethod<any, number>(
      "setAuthHeader",
      {
        username: localUsername,
        password: localPassword
      }
    );
    console.log("[SUN]", "setAuthHeader result", result)
    sunshineCheckAuthorized()
  }

  useEffect(() => {
    setWantToggleSunshine(sunshineIsRunning)
    sunshineCheckAuthorized()
  }, [sunshineIsRunning])

  useEffect(() => {
    if (wantToggleSunshine != sunshineIsRunning) {
      if (wantToggleSunshine) {
        console.log("[SUN]", "should start")
        serverAPI.callPluginMethod<any, number>(
          "sunshineStart",
          {
          }
        );
      } else {
        console.log("[SUN]", "should stop")
        serverAPI.callPluginMethod<any, number>(
          "sunshineStop",
          {
          }
        );
      }
      window.setTimeout(() => sunshineCheckRunning(), 1000)
    }
  }, [wantToggleSunshine])

  sunshineCheckRunning()

  return (wantToggleSunshine != sunshineIsRunning) ? <Spinner></Spinner> :
    <PanelSection>
      <PanelSectionRow>
        <ToggleField
          label="Enabled"
          checked={wantToggleSunshine}
          onChange={setWantToggleSunshine}
        ></ToggleField>
      </PanelSectionRow>
      {sunshineIsAuthorized ? <div>
        <NumpadInput value={localPin} onChange={setLocalPin} label="PIN"></NumpadInput>
        <PanelSectionRow>
          <ButtonItem onClick={() => sendPin()} disabled={localPin.length < 4}>Send PIN</ButtonItem>
        </PanelSectionRow>
      </div> : <div>
        <PanelSectionRow>
          <TextField label="Username" value={localUsername} onChange={(e) => setLocalUsername(e.target.value)}></TextField>
          <TextField label="Password" value={localPassword} onChange={(e) => setLocalPassword(e.target.value)}></TextField>
          <ButtonItem onClick={() => setAuthHeader()} disabled={localUsername.length < 1 || localPassword.length < 1}>Login</ButtonItem>
        </PanelSectionRow>
      </div>}
      {/* {sunshineIsEnabled &&
        <ButtonItem onClick={() => Navigation.NavigateToExternalWeb("https://127.0.0.1:47990")}>Web UI</ButtonItem>} */}
    </PanelSection>
};

export default definePlugin((serverApi: ServerAPI) => {
  return {
    title: <div className={staticClasses.Title}>Decky Sunshine</div>,
    content: <Content serverAPI={serverApi} />,
    icon: <FaSun />,
    onDismount() {
    },
  };
});
