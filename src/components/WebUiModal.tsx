import { FC, useEffect, useState } from 'react'
import { DialogButton, ModalRoot, Spinner } from "@decky/ui";
import { QRCodeSVG } from "qrcode.react";
import backend from "../util/backend";
import type { WebUiInfo } from "../util/types";

const WEB_UI_PORT = 47990;

export const WebUiModal: FC<{
    closeModal?: () => void;
}> = ({
        closeModal,
      }) => {
    // undefined = still fetching
    const [info, setInfo] = useState<WebUiInfo | null | undefined>(undefined);
    const [isRestarting, setIsRestarting] = useState<boolean>(false);
    const [credentials, setCredentials] = useState<{username: string, password: string} | null>(null);
    const [credentialsMissing, setCredentialsMissing] = useState<boolean>(false);
    const [isGettingCredentials, setIsGettingCredentials] = useState<boolean>(false);

    useEffect(() => {
      backend.getWebUiInfo().then(setInfo);
    }, []);

    const url = info?.ip ? `https://${info.ip}:${WEB_UI_PORT}` : null;

    const restartSunshine = async () => {
      setIsRestarting(true);
      try {
        if (await backend.stopSunshine()) {
          await backend.startSunshine();
        }
        // Re-check instead of assuming success; on failure the hint stays
        setInfo(await backend.getWebUiInfo());
      } finally {
        setIsRestarting(false);
      }
    };

    const showCredentials = async () => {
      setIsGettingCredentials(true);
      try {
        const result = await backend.getCredentials();
        setCredentials(result);
        setCredentialsMissing(result == null);
      } finally {
        setIsGettingCredentials(false);
      }
    };

    // Revealed only on request (never automatically): the Deck's screen may
    // be streamed or recorded, so a plaintext password must be deliberate.
    // Closing the modal hides them again.
    const credentialsBlock = (
      <>
        <span style={{ fontSize: "0.9em", opacity: 0.8 }}>
          Your browser will warn about the certificate - choose to proceed anyway,
          then log in with the Web UI credentials.
        </span>
        {credentials == null
          ? <DialogButton disabled={isGettingCredentials} onClick={() => showCredentials()}>
              {isGettingCredentials
                ? <Spinner style={{ width: 14, height: 14 }} />
                : "Show credentials"}
            </DialogButton>
          : <span style={{ fontSize: "0.9em", userSelect: "text" }}>
              Username: <b>{credentials.username}</b><br />
              Password: <b>{credentials.password}</b>
            </span>
        }
        {credentialsMissing &&
          <span style={{ color: "red", fontSize: "0.9em" }}>No credentials stored</span>
        }
      </>
    );

    return (
      <ModalRoot onCancel={closeModal}>
        {info === undefined &&
          <div style={{ display: "flex", justifyContent: "center" }}>
            <Spinner style={{ width: 24, height: 24 }} />
          </div>
        }
        {url &&
          /* Two columns (QR left, text right) to keep the modal flat enough
             for all hints to fit on screen at once */
          <div style={{ display: "flex", alignItems: "center", gap: "1.2em" }}>
            {/* The white padding keeps the quiet zone scanners need, independent of theme */}
            <div style={{ background: "#ffffff", padding: "0.8em", lineHeight: 0, borderRadius: "0.4em", flexShrink: 0 }}>
              <QRCodeSVG value={url} size={140} bgColor="#ffffff" fgColor="#000000" />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.6em" }}>
              <span>Scan the code or open this address in a browser on another device on the same network:</span>
              <span style={{ fontWeight: 600, fontSize: "1.1em", userSelect: "text", overflowWrap: "anywhere" }}>{url}</span>
              {!info?.editing_ready &&
                <>
                  <span style={{ color: "orange", fontSize: "0.9em" }}>
                    Right now the other device can only view: saving changes there
                    starts working after Sunshine restarts.
                  </span>
                  <DialogButton disabled={isRestarting} onClick={() => restartSunshine()}>
                    {isRestarting
                      ? <Spinner style={{ width: 14, height: 14 }} />
                      : "Restart Sunshine now (ends active streams)"}
                  </DialogButton>
                </>
              }
              {credentialsBlock}
            </div>
          </div>
        }
        {info !== undefined && !info?.ip &&
          <div style={{ display: "flex", flexDirection: "column", gap: "0.6em", textAlign: "center" }}>
            <span style={{ color: "orange" }}>
              This Deck's network address could not be determined - is it connected to a network?
              You can find the address under Settings → Internet, then open https://(that address):{WEB_UI_PORT}.
            </span>
            {credentialsBlock}
          </div>
        }
        <DialogButton style={{ marginTop: "1em" }} onClick={() => { closeModal?.(); }}>Close</DialogButton>
      </ModalRoot>
    );
};
