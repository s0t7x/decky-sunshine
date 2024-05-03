// Basic React component that renders a numeric input field

import React from "react";
import { PanelSectionRow, gamepadDialogClasses, joinClassNames, DialogButton, Focusable } from "decky-frontend-lib";

import { playSound } from "../util/util";

const FieldWithSeparator = joinClassNames(gamepadDialogClasses.Field, gamepadDialogClasses.WithBottomSeparatorStandard);

// NumericInputProps interface with value and onChange properties
interface PINInputProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSend: (value: string) => void;
  sendLabel: string;
}

export const PINInput = (props: PINInputProps): JSX.Element => {
  const { label, value, onChange, onSend, sendLabel } = props;

  const enterDigit = (digit: string) => {
    //Concat the digit to the current value
    if (value.length == 4) {
      playSound("https://steamloopback.host/sounds/deck_ui_default_activation.wav");
      return
    }
    let newValue = value + digit;

    // setvalue(newValue);
    onChange(newValue);

    playSound("https://steamloopback.host/sounds/deck_ui_misc_10.wav");
  }

  const backspace = () => {
    playSound("https://steamloopback.host/sounds/deck_ui_misc_10.wav");
    if (value.length > 1) {
      //Remove the last digit from the current value
      const newValue = value.slice(0, -1);
      // setvalue(newValue);
      onChange(newValue);
    }
    else {
      //Clear the current value
      // setvalue("");
      onChange("");
    }
  }

  const sendPin = () => {
    playSound("https://steamloopback.host/sounds/deck_ui_side_menu_fly_in.wav");
    onSend(value)
  }

  return (
    <React.Fragment>
      <PanelSectionRow>
        <div className={FieldWithSeparator}>
          <div
            className={gamepadDialogClasses.FieldLabelRow}
          >
            <div
              className={gamepadDialogClasses.FieldLabel}
              style={{ "maxWidth": "50%", "wordBreak": "keep-all" }}
            >
              {label}
            </div>
            <div
              className={gamepadDialogClasses.FieldChildren}
              style={{ "maxWidth": "50%", "width": "100%", "wordBreak": "break-all", "textAlign": "end" }}
            >
              {value}
            </div>
          </div>
        </div>
      </PanelSectionRow>


      <React.Fragment>
        {/* Override min-width for DialogButtons */}
        <style>{`
            .NumpadGrid button {
              min-width: 0 !important; 
            }
          `}</style>

        {/* 3x4 Digit Grid */}
        <Focusable className="NumpadGrid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gridTemplateRows: "repeat(4, 1fr)", gridGap: "0.5rem", padding: "0px 0" }}>
          <DialogButton onClick={() => enterDigit("7")}>7</DialogButton>
          <DialogButton onClick={() => enterDigit("8")}>8</DialogButton>
          <DialogButton onClick={() => enterDigit("9")}>9</DialogButton>

          <DialogButton onClick={() => enterDigit("4")}>4</DialogButton>
          <DialogButton onClick={() => enterDigit("5")}>5</DialogButton>
          <DialogButton onClick={() => enterDigit("6")}>6</DialogButton>

          <DialogButton onClick={() => enterDigit("1")}>1</DialogButton>
          <DialogButton onClick={() => enterDigit("2")}>2</DialogButton>
          <DialogButton onClick={() => enterDigit("3")}>3</DialogButton>

          <DialogButton onClick={() => backspace()}>&larr;</DialogButton>
          <DialogButton onClick={() => enterDigit("0")}>0</DialogButton>
          <DialogButton disabled={value.length < 4} onClick={() => sendPin()} style={{ backgroundColor: "green" }}>{sendLabel}</DialogButton>
        </Focusable>
      </React.Fragment>
    </React.Fragment>
  );
}