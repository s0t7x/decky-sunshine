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
  QuickAccessTab
} from "decky-frontend-lib";
import { VFC, useEffect, useState } from "react";
import { FaSun } from "react-icons/fa";

import { PINInput } from "./components/PINInput";

const Content: VFC<{ serverAPI: ServerAPI }> = ({ serverAPI }) => {
  const [sunshineIsRunning, setSunshineIsRunning] = useState<boolean>(false);
  const [sunshineIsAuthorized, setSunshineIsAuthorized] = useState<boolean>(false);

  const [wantToggleSunshine, setWantToggleSunshine] = useState<boolean>(false);

  const [localPin, setLocalPin] = useState("");

  const sendPin = async () => {
    const result = await serverAPI.callPluginMethod<{ pin: string }, boolean>(
      "sendPin",
      {
        pin: localPin
      }
    );
    console.log("[SUN]", "sendPin result", result)
    setLocalPin("")
  }

  const sunshineCheckRunning = async () => {
    const result = await serverAPI.callPluginMethod<any, boolean>(
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
    const changed = localStorage.getItem("decky_sunshine:localChanged")
    if(!changed) return
    localStorage.setItem("decky_sunshine:localChanged", JSON.stringify(false));
    const result = await serverAPI.callPluginMethod<any, boolean>(
      "setAuthHeader",
      {
        username: JSON.parse(localStorage.getItem("decky_sunshine:localUsername") || "decky_sunshine"),
        password: JSON.parse(localStorage.getItem("decky_sunshine:localPassword") || "decky_sunshine")
      }
    );
    console.log("[SUN]", "setAuthHeader result", result)
  }

  const sunshineCheckAuthorized = async () => {
    if (!sunshineIsRunning) return
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
        ).then(res => console.log("[SUN] start res: ", res));
      } else {
        console.log("[SUN]", "should stop")
        serverAPI.callPluginMethod<any, any>(
          "sunshineStop",
          {
          }
        ).then(res => console.log("[SUN] stop res: ", res));
      }
      window.setTimeout(() => sunshineCheckRunning(), 1000)
    }
  }, [wantToggleSunshine])

  ;(async () => {
    await sunshineCheckRunning()
    await sunshineCheckAuthorized()
  })()

  return (wantToggleSunshine != sunshineIsRunning) ? <Spinner></Spinner> :
    <PanelSection>
      <PanelSectionRow>
        <ToggleField
          label="Enabled"
          checked={wantToggleSunshine}
          onChange={setWantToggleSunshine}
        ></ToggleField>
      </PanelSectionRow>
      {sunshineIsAuthorized ? (sunshineIsRunning &&
        <PINInput value={localPin} key="pin" onChange={setLocalPin} label="Enter PIN" onSend={sendPin} sendLabel="Pair"></PINInput>
      ) : (sunshineIsRunning &&
        <PanelSectionRow>
          <p>You need to log into web ui once</p>
          <ButtonItem onClick={() => {
            Navigation.CloseSideMenus();
            Navigation.Navigate("/sunshine-login");
          }}>Login</ButtonItem>
        </PanelSectionRow>)}
      {/* {sunshineIsEnabled &&
        <ButtonItem onClick={() => Navigation.NavigateToExternalWeb("https://127.0.0.1:47990")}>Web UI</ButtonItem>} */}
    </PanelSection>
};

const DeckySunshineLogin: VFC = () => {
  let pun, ppw = undefined
  try {
    pun = JSON.parse(localStorage.getItem("decky_sunshine:localUsername") || "decky_sunshine")
    ppw = ""
  } catch {

  }

  const [localUsername, setLocalUsername] = useState(pun || "decky_sunshine");
  const [localPassword, setLocalPassword] = useState(ppw || "");

  const storeCreds = (): void => {
    localStorage.setItem("decky_sunshine:localUsername", JSON.stringify(localUsername));
    localStorage.setItem("decky_sunshine:localPassword", JSON.stringify(localPassword));
    localStorage.setItem("decky_sunshine:localChanged", JSON.stringify(true));
  };

  return (
    <div style={{ marginTop: "50px", color: "white" }}>
      <TextField label="Username" value={localUsername} onChange={(e) => setLocalUsername(e.target.value)}></TextField>
      <TextField label="Password" bIsPassword={true} bAlwaysShowClearAction={true} value={localPassword} onChange={(e) => {
        setLocalPassword(e.target.value);
      }}></TextField>
      <ButtonItem onClick={() => {
        Navigation.NavigateBack();
        storeCreds();
        Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky)
      }} disabled={localUsername.length < 1 || localPassword.length < 1}>Login</ButtonItem>
    </div>
  );
};

const DeckySunshineSetUser: VFC = () => {
  const [currentUsername, setCurrentUsername] = useState("")
  const [currentPassword, setCurrentPassword] = useState("")
  const [newUsername, setNewUsername] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmNewPassword, setConfirmNewPassword] = useState("")


  const storeCreds = (): void => {
    localStorage.setItem("decky_sunshine:setUserData", JSON.stringify(
      {
        currentUsername, currentPassword,
        newUsername, newPassword, confirmNewPassword
      }
    ));
  };

  return (
    <div style={{ marginTop: "50px", color: "white" }}>
      <TextField label="currentUsername" value={currentUsername} onChange={(e) => setCurrentUsername(e.target.value)}></TextField>
      <TextField label="currentPassword" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)}></TextField>
      <TextField label="newUsername" value={newUsername} onChange={(e) => setNewUsername(e.target.value)}></TextField>
      <TextField label="newPassword" value={newPassword} onChange={(e) => setNewPassword(e.target.value)}></TextField>
      <TextField label="confirmNewPassword" value={confirmNewPassword} onChange={(e) => setConfirmNewPassword(e.target.value)}></TextField>

      <ButtonItem onClick={() => {
        Navigation.NavigateBack();
        storeCreds();
        Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky)
      }} disabled={
        currentUsername.length < 1 ||
        currentPassword.length < 1 ||
        newUsername.length < 1 ||
        newPassword.length < 1 ||
        confirmNewPassword.length < 1
      }>Set Credentials</ButtonItem>
    </div>
  );
};

export default definePlugin((serverApi: ServerAPI) => {
  serverApi.routerHook.addRoute("/sunshine-login", DeckySunshineLogin, {
    exact: true
  });
  serverApi.routerHook.addRoute("/sunshine-set-user", DeckySunshineSetUser, {
    exact: true
  });

  return {
    title: <div className={staticClasses.Title}>Decky Sunshine</div>,
    content: <Content serverAPI={serverApi} />,
    icon: <FaSun />,
    onDismount() {
      serverApi.routerHook.removeRoute("/sunshine-login");
      serverApi.routerHook.removeRoute("/sunshine-set-user");
    },
  };
});
