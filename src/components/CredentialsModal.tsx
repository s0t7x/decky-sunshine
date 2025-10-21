import { VFC } from 'react'
import { DialogButton, TextField, ModalRoot, Field, DialogButtonPrimary } from "decky-frontend-lib";
import { playSound } from "../util/util";
import { useState } from "react";
import { PasswordInput } from './PasswordInput';

export const CredentialsModal: VFC<{
    closeModal?: () => void;
    onLogin: (username: string, password: string) => Promise<boolean | null>;
}> = ({
        closeModal,
        onLogin: onLogin,
      }) => {
    const [localUsername, setLocalUsername] = useState(localStorage.getItem("decky_sunshine:localUsername") || "decky_sunshine");
    const [localPassword, setLocalPassword] = useState("");
    const [wasLoginSucessful, setWasLoginSucessful ] = useState<boolean | null>(null);
    const [hadErrorOnLogin, setHadErrorOnLogin ] = useState<boolean>(false);
    const [isWaitingForResponse, setIsWaitingForResponse ] = useState(false);

    const tryLogin = async () => {
      playSound("https://steamloopback.host/sounds/deck_ui_side_menu_fly_in.wav");
      setIsWaitingForResponse(true)
      const success = await onLogin(localUsername, localPassword);
      localStorage.setItem("decky_sunshine:localUsername", localUsername);

      if (success){
        closeModal?.();
      }

      setIsWaitingForResponse(false);
      setWasLoginSucessful(success);
      setHadErrorOnLogin(success === null);
    }

    return (
      <ModalRoot onCancel={closeModal}>
        <Field label="Username">
          <TextField
            value={localUsername}
            style={{ width: '20em' }}
            bShowClearAction={localUsername.length > 0}
            onChange={(e) => {setLocalUsername(e.target.value); setWasLoginSucessful(null);}}
          />
        </Field>
        <Field label="Password">
          <PasswordInput
            value={localPassword}
            style={{ width: '20em' }}
            onChange={(value) => {setLocalPassword(value); setWasLoginSucessful(null);}}
          />
        </Field>
        {hadErrorOnLogin && <span style={{ color: 'red' }}>An error occurred during login. Please try again.</span>}
        {isWaitingForResponse && <span>Waiting for response...</span>}
        {wasLoginSucessful === false && <span style={{ color: 'red' }}>Login failed. Please try again.</span>}
        <div style={{ display: 'flex', gap: '0.5em' }}>
          <DialogButton onClick={() => { closeModal?.(); }}>Cancel</DialogButton>
          <DialogButtonPrimary onClick={() => tryLogin()} disabled={ localUsername.length < 1 || localPassword.length < 1 || isWaitingForResponse === true }>
            Login
          </DialogButtonPrimary>
        </div>
      </ModalRoot>
    );
};