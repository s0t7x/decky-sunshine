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
} from "decky-frontend-lib";
import { VFC, useEffect, useState } from "react";
import { FaSun } from "react-icons/fa";
import { NumpadInput } from "./components/NumpadInput";

// interface AddMethodArgs {
//   left: number;
//   right: number;
// }

const __unused = (...argv: any[]) => { argv.toString() }

const Content: VFC<{ serverAPI: ServerAPI }> = ({ serverAPI }) => {
  const [sunshineIsEnabled, setSunshineIsEnabled] = useState<boolean>(false);
  const [wantSetSunshineEnabled, setWantSetSunshineEnabled] = useState<boolean>(false);
  const [pin, setPin] = useState("");
  const [resPin, setResPin] = useState<any>();

  __unused(setSunshineIsEnabled)

  const sendPin = async () => {
    const result = await serverAPI.callPluginMethod<any, number>(
      "sendPin",
      {
        pin
      }
    );
    console.log("[SUN]", "sendPin result", result)
    if (result.success) {
      setResPin(result);
    } else {
      setResPin(undefined);
    }
  }

  const sunshineCheckRunning = async () => {
    const result = await serverAPI.callPluginMethod<any, number>(
      "sunshineIsOnline",
      {
      }
    );
    console.log("[SUN]", "checkRunning result", result)
    if (result.success) {
      setSunshineIsEnabled(Boolean(result.result));
    } else {
      setSunshineIsEnabled(false);
    }
  };

  useEffect(() => {
    setWantSetSunshineEnabled(sunshineIsEnabled)
  }, [sunshineIsEnabled])

  useEffect(() => {
    if (wantSetSunshineEnabled != sunshineIsEnabled) {
      if (wantSetSunshineEnabled) {
        console.log("[SUN]", "should enable")
        serverAPI.callPluginMethod<any, number>(
          "sunshineStart",
          {
          }
        );
      } else {
        console.log("[SUN]", "should disable")
        serverAPI.callPluginMethod<any, number>(
          "sunshineStop",
          {
          }
        );
      }
      window.setTimeout(() => sunshineCheckRunning(), 1000)
    }
  }, [wantSetSunshineEnabled])

  sunshineCheckRunning()

  return (wantSetSunshineEnabled != sunshineIsEnabled) ? <Spinner></Spinner> :
    <PanelSection>
      <PanelSectionRow>
        <ToggleField
          label="Enabled"
          checked={wantSetSunshineEnabled}
          onChange={setWantSetSunshineEnabled}
        ></ToggleField>
      </PanelSectionRow>
      {/* <NumpadInput value={pin} onChange={setPin} label="PIN"></NumpadInput>
      <PanelSectionRow>
        <ButtonItem onClick={() => sendPin()} disabled={pin.length < 4}>Send PIN</ButtonItem>
      </PanelSectionRow>
      <span>{JSON.stringify(resPin)}</span> */}
      {/* {sunshineIsEnabled &&
        <ButtonItem onClick={() => Navigation.NavigateToExternalWeb("http://127.0.0.1:7777")}>Web UI</ButtonItem>} */}
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
