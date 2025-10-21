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
    const [wasPairingSuccessfull, setWasPairingSucessfull ] = useState<boolean | null>(null);
    const [isWaitingForResponse, setIsWaitingForResponse ] = useState(false);

    const tryPair = async () => {
      playSound("https://steamloopback.host/sounds/deck_ui_side_menu_fly_in.wav");
      setIsWaitingForResponse(true)
      const success = await onPair(pin, clientName);
      if (success){
        closeModal?.()
      }
      setIsWaitingForResponse(false);
      setWasPairingSucessfull(success);
    }

    const handlePINChange = (e: ChangeEvent<HTMLInputElement>) => {
      if (/^\d{0,4}$/.test(e.currentTarget.value)) {
        setWasPairingSucessfull(null);
        setPin(e.currentTarget.value);
      }
    }

    return (
      <ModalRoot onCancel={closeModal}>
        <Field label="Client name">
          <TextField
            value={clientName}
            style={{ width: '25em' }}
            description="A name for the client / device you want to pair"
            bShowClearAction={clientName.length > 0}
            onChange={(e) => setClientName(e.target.value)}
          />
        </Field>
        <Field label="PIN">
          <TextField
            value={pin}
            style={{ width: '25em' }}
            description="The PIN as shown on the client / device you want to pair (4 digits)"
            bShowClearAction={pin.length > 0}
            mustBeNumeric={true}
            onChange={handlePINChange} />
        </Field>
        {isWaitingForResponse && <span>Waiting for response...</span>}
        {wasPairingSuccessfull === false && <span style={{ color: 'red' }}>Pairing failed. Please try again.</span>}
        <DialogButton onClick={() => tryPair()} disabled={ pin.length < 4 || clientName.length < 1 || isWaitingForResponse == true }>
          Pair
        </DialogButton>
      </ModalRoot>
    );
};