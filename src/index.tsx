import {
  ToggleField,
  definePlugin,
  PanelSection,
  PanelSectionRow,
  ServerAPI,
  staticClasses,
  ButtonItem,
  Spinner,
  Navigation,
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

  const sendPin = async () => {
    const result = await serverAPI.callPluginMethod<any, number>(
      "sendPin",
      {
        pin: localPin
      }
    );
    console.log("[SUN]", "sendPin result", result)
    setLocalPin("")
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

  const setAuthHeader = async () => {
    const result = await serverAPI.callPluginMethod<any, boolean>(
      "setAuthHeader",
      {
        username: JSON.parse(localStorage.getItem("decky_sunshine:localUsername") || ""),
        password: JSON.parse(localStorage.getItem("decky_sunshine:localPassword") || "")
      }
    );
    console.log("[SUN]", "setAuthHeader result", result)
  }

  const sunshineCheckAuthorized = async () => {
    if(!sunshineIsRunning) return
    await setAuthHeader()
    const result = await serverAPI.callPluginMethod<any, boolean>(
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

  useEffect(() => {
    setWantToggleSunshine(sunshineIsRunning)
    sunshineCheckAuthorized()
  }, [sunshineIsRunning])

  useEffect(() => {
    if (wantToggleSunshine != sunshineIsRunning) {
      if (wantToggleSunshine) {
        console.log("[SUN]", "should start")
        serverAPI.callPluginMethod<any, any>(
          "sunshineStart",
          {
          }
        ).then(res => console.log("[SUN]", res));
      } else {
        console.log("[SUN]", "should stop")
        serverAPI.callPluginMethod<any, any>(
          "sunshineStop",
          {
          }
        ).then(res => console.log("[SUN]", res));
      }
      window.setTimeout(() => sunshineCheckRunning(), 1000)
    }
  }, [wantToggleSunshine])

  sunshineCheckRunning()
  sunshineCheckAuthorized()

  return (wantToggleSunshine != sunshineIsRunning) ? <Spinner></Spinner> :
    <PanelSection>
      <PanelSectionRow>
        <ToggleField
          label="Enabled"
          checked={wantToggleSunshine}
          onChange={setWantToggleSunshine}
        ></ToggleField>
      </PanelSectionRow>
      {sunshineIsAuthorized ? (sunshineIsRunning && <div>
        <NumpadInput value={localPin} key="pin" onChange={setLocalPin} label="PIN"></NumpadInput>
        <PanelSectionRow>
          <div></div>
          <ButtonItem onClick={() => sendPin()} disabled={localPin.length < 4}>Send PIN</ButtonItem>
        </PanelSectionRow>
      </div>) : (sunshineIsRunning &&
        <PanelSectionRow>
          <div></div>
          <p>You need to log into web ui once</p>
          <ButtonItem onClick={() => {
            Navigation.CloseSideMenus();
            Navigation.Navigate("/sunshine-login");
          }}>Login</ButtonItem>

        </PanelSectionRow>
      )}
      {/* {sunshineIsEnabled &&
        <ButtonItem onClick={() => Navigation.NavigateToExternalWeb("https://127.0.0.1:47990")}>Web UI</ButtonItem>} */}
    </PanelSection>
};

const DeckySunshineLogin: VFC = () => {
  let pun, ppw = undefined
  try{
    pun = JSON.parse(localStorage.getItem("decky_sunshine:localUsername") || "")
    ppw = JSON.parse(localStorage.getItem("decky_sunshine:localPassword") || "")
  } catch {

  }

  const [localUsername, setLocalUsername] = useState(pun || "sunshine");
  const [localPassword, setLocalPassword] = useState(ppw || "");

  const storeCreds = (): void => {
    localStorage.setItem("decky_sunshine:localUsername", JSON.stringify(localUsername));
    localStorage.setItem("decky_sunshine:localPassword", JSON.stringify(localPassword));
  };

  return (
    <div style={{ marginTop: "50px", color: "white" }}>
      <TextField label="Username" value={localUsername} onChange={(e) => setLocalUsername(e.target.value)}></TextField>
      <TextField label="Password" bIsPassword={true} bAlwaysShowClearAction={true} value={[...localPassword].map((c) => '*').join('')} onChange={(e) => {
        setLocalPassword(e.target.value);
      }}></TextField>
      <ButtonItem onClick={() => {
        Navigation.NavigateBack();
        storeCreds();
      }} disabled={localUsername.length < 1 || localPassword.length < 1}>Login</ButtonItem>
    </div>
  );
};

export default definePlugin((serverApi: ServerAPI) => {
  serverApi.routerHook.addRoute("/sunshine-login", DeckySunshineLogin, {
    exact: true
  });

  return {
    title: <div className={staticClasses.Title}>Decky Sunshine</div>,
    content: <Content serverAPI={serverApi} />,
    icon: <FaSun />,
    onDismount() {
      serverApi.routerHook.removeRoute("/sunshine-login");
    },
  };
});
