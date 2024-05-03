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
  QuickAccessTab,
  Button
} from "decky-frontend-lib";
import { VFC, useEffect, useState } from "react";
import { FaSun } from "react-icons/fa";
import backend from "./util/backend";

import { PINInput } from "./components/PINInput";
import { PasswordInput } from "./components/PasswordInput";

const __unused = (v: any) => v

const Content: VFC<{ serverAPI: ServerAPI }> = ({ serverAPI }) => {
  __unused(serverAPI)

  const [sunshineIsRunning, setSunshineIsRunning] = useState<boolean>(false);
  const [sunshineIsAuthorized, setSunshineIsAuthorized] = useState<boolean>(false);

  const [wantToggleSunshine, setWantToggleSunshine] = useState<boolean>(false);

  const [localPin, setLocalPin] = useState("");

  const updateSunshineState = async () => {
    const running = await backend.sunshineIsRunning()
    setSunshineIsRunning(running)
    const authed = await backend.sunshineIsAuthorized()
    setSunshineIsAuthorized(authed)
  }

  useEffect(() => {
    if (wantToggleSunshine != sunshineIsRunning)
      setWantToggleSunshine(sunshineIsRunning)
  }, [sunshineIsRunning])

  useEffect(() => {
    if (wantToggleSunshine != sunshineIsRunning) {
      if (wantToggleSunshine) {
        backend.sunshineStart()
      } else {
        backend.sunshineStop()
      }
      window.setTimeout(() => updateSunshineState(), 1000)
    }
  }, [wantToggleSunshine])

  updateSunshineState()

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
        <PINInput value={localPin} key="pin" onChange={setLocalPin} label="Enter PIN" onSend={() => { backend.sunshineSendPin(localPin); setLocalPin("") }} sendLabel="Pair"></PINInput>
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
      {/* <ButtonItem onClick={() => {
        Navigation.CloseSideMenus();
        Navigation.Navigate("/sunshine-set-user");
      }}>Set User</ButtonItem> */}
    </PanelSection>
};

const DeckySunshineLogin: VFC = () => {
  let pun = undefined
  try {
    pun = JSON.parse(localStorage.getItem("decky_sunshine:localUsername") || "decky_sunshine")
  } catch {
    pun = "decky_sunshine"
  }

  const [localUsername, setLocalUsername] = useState(pun);
  const [localPassword, setLocalPassword] = useState("");

  return (
    <div style={{ marginTop: "50px", color: "white" }}>
      <TextField label="Username" value={localUsername} onChange={(e) => setLocalUsername(e.target.value)}></TextField>
      <PasswordInput label="Password" value={localPassword} onChange={(value) => {
        setLocalPassword(value);
      }}></PasswordInput>
      <ButtonItem onClick={() => {
        localStorage.setItem("decky_sunshine:localUsername", localUsername)
        Navigation.NavigateBack();
        backend.sunshineSetAuthHeader(localUsername, localPassword)
        Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky)
      }} disabled={localUsername.length < 1 || localPassword.length < 1}>Login</ButtonItem>
    </div>
  );
};

// const DeckySunshineSetUser: VFC = () => {
//   const [currentUsername, setCurrentUsername] = useState("")
//   const [currentPassword, setCurrentPassword] = useState("")
//   const [newUsername, setNewUsername] = useState("")
//   const [newPassword, setNewPassword] = useState("")
//   const [confirmNewPassword, setConfirmNewPassword] = useState("")

//   const [step, setStep] = useState(0)

//   return (
//     <div style={{ marginTop: "50px", color: "white" }}>
//       <h2>Set new Credentials</h2>
//       {(step == 0) ?
//         <div>
//           <TextField label="currentUsername" value={currentUsername} onChange={(e) => setCurrentUsername(e.target.value)}></TextField>
//           <PasswordInput label="currentPassword" value={currentPassword} onChange={(e) => setCurrentPassword(e)}></PasswordInput>
//           <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between" }}>
//             <Button onClick={() => {
//               Navigation.NavigateBack();
//               Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky)
//             }}>Cancel</Button>
//             <Button onClick={() => setStep(1)}>Next</Button>
//           </div>
//         </div> :
//         <div>
//           <TextField label="newUsername" value={newUsername} onChange={(e) => setNewUsername(e.target.value)}></TextField>
//           <PasswordInput label="newPassword" value={newPassword} onChange={(e) => setNewPassword(e)}></PasswordInput>
//           <PasswordInput label="confirmNewPassword" value={confirmNewPassword} onChange={(e) => setConfirmNewPassword(e)}></PasswordInput>
//           <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
//             <ButtonItem onClick={() => setStep(0)}>Back</ButtonItem>
//             <ButtonItem onClick={() => {
//               Navigation.NavigateBack();
//               backend.sunshineSetUser(newUsername, newPassword, confirmNewPassword, currentUsername, currentPassword);
//               Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky)
//             }} disabled={
//               currentUsername.length < 1 ||
//               currentPassword.length < 1 ||
//               newUsername.length < 1 ||
//               newPassword.length < 1 ||
//               confirmNewPassword.length < 1
//             }>Set Credentials</ButtonItem>
//           </div>
//         </div>
//       }

//     </div >
//   );
// };

export default definePlugin((serverApi: ServerAPI) => {
  serverApi.routerHook.addRoute("/sunshine-login", DeckySunshineLogin, {
    exact: true
  });
  // serverApi.routerHook.addRoute("/sunshine-set-user", DeckySunshineSetUser, {
  //   exact: true
  // });

  backend.serverAPI = serverApi

  return {
    title: <div className={staticClasses.Title}>Decky Sunshine</div>,
    content: <Content serverAPI={serverApi} />,
    icon: <FaSun />,
    onDismount() {
      serverApi.routerHook.removeRoute("/sunshine-login");
      // serverApi.routerHook.removeRoute("/sunshine-set-user");
    },
  };
});
