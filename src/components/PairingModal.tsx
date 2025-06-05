import { ChangeEvent, VFC } from 'react'
import { DialogButton, TextField, ModalRoot, Field } from "decky-frontend-lib";
import { playSound } from "../util/util";
import { useState } from "react";

export const PairingModal: VFC<{
    closeModal?: () => void;
    onPair: (pin: string, clientName: string) => Promise<boolean>;
}> = ({
        closeModal,
        onPair,
      }) => {
    const [pin, setPin] = useState("");
    const [clientName, setClientName] = useState("");
    const [wasPairingSucessful, setWasPairingSucessful ] = useState<boolean | null>(null);
    const [isWaitingForResponse, setIsWaitingForResponse ] = useState(false);

    const pair = async () => {
      playSound("https://steamloopback.host/sounds/deck_ui_side_menu_fly_in.wav");
      setIsWaitingForResponse(true)
      const success = await onPair(pin, clientName);
      setIsWaitingForResponse(false)
      setWasPairingSucessful(success);
      if (success){
        closeModal?.()
      }
    }

    const handlePINChange = (e: ChangeEvent<HTMLInputElement>) => {
      if (/^\d{0,4}$/.test(e.currentTarget.value)) {
        setWasPairingSucessful(null);
        setPin(e.currentTarget.value);
      }
    }

    return (
      <ModalRoot onCancel={closeModal}>
        <Field label="Client name">
          <TextField
            value={clientName}
            style={{ width: '20em' }}
            description="A name for the client / device you want to pair"
            onChange={(e) => setClientName(e.target.value)}
          />
        </Field>
        <Field label="PIN">
          <TextField
            value={pin}
            style={{ width: '3em' }}
            description="The PIN as shown on the client / device you want to pair (4 digits)"
            onChange={handlePINChange} />
        </Field>
        <DialogButton disabled={ pin.length < 4 || clientName.length < 1 || wasPairingSucessful === false || isWaitingForResponse == true } onClick={() => pair()} style={{ backgroundColor: wasPairingSucessful === null ? "green" : "red" }}>
          {wasPairingSucessful === null
            ? isWaitingForResponse ? "Waiting for response..." : "Pair"
            : "Pairing failed"}</DialogButton>
      </ModalRoot>
    );
};