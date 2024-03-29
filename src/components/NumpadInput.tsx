// Basic React component that renders a numeric input field

import React, { useEffect, useState } from "react";
import { PanelSectionRow, gamepadDialogClasses, joinClassNames, DialogButton, Focusable } from "decky-frontend-lib";

import { playSound } from "../util/util";

const FieldWithSeparator = joinClassNames(gamepadDialogClasses.Field, gamepadDialogClasses.WithBottomSeparatorStandard);

// NumericInputProps interface with value and onChange properties
interface NumpadInputProps {
  value: string;
  onChange: (value: string) => void;
  label: string;
}

export const NumpadInput = (props: NumpadInputProps): JSX.Element => {
  const { label, value, onChange } = props;

  const [inputValue, setInputValue] = useState(value);

  const [active] = useState(true);

  useEffect(() => {
    if (active) {
      playSound("https://steamloopback.host/sounds/deck_ui_side_menu_fly_in.wav");
    }
    else {
      playSound("https://steamloopback.host/sounds/deck_ui_side_menu_fly_out.wav");
    }
  }, [active]);

  const enterDigit = (digit: string) => {
    //Ensure only one decimal point
    if (digit === "." && inputValue.includes(".")) {
      playSound("https://steamloopback.host/sounds/deck_ui_default_activation.wav");
      return;
    }

    //Concat the digit to the current value
    let newValue = inputValue + digit;
    if (inputValue === "0") {
      if (digit === ".") {
        newValue = "0.";
      }
      else {
        newValue = digit;
      }
    }

    setInputValue(newValue);
    onChange(newValue);

    playSound("https://steamloopback.host/sounds/deck_ui_misc_10.wav");
  }

  const backspace = () => {
    playSound("https://steamloopback.host/sounds/deck_ui_misc_10.wav");
    if (inputValue.length > 1) {
      //Remove the last digit from the current value
      const newValue = inputValue.slice(0, -1);
      setInputValue(newValue);
      onChange(newValue);
    }
    else {
      //Clear the current value
      setInputValue("0");
      onChange("0");
    }
  }

  return (
    <React.Fragment>
      <PanelSectionRow>
        <div className={FieldWithSeparator}>
          <div
            className={gamepadDialogClasses.FieldLabelRow}
          // onClick={() => setActive(!active)}
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
              {inputValue}
            </div>
          </div>
        </div>
      </PanelSectionRow>

      {/* If active */}
      {active && (
        <React.Fragment>
          {/* Override min-width for DialogButtons */}
          <style>{`
            .NumpadGrid button {
              min-width: 0 !important; 
            }
          `}</style>

          {/* 3x4 Digit Grid */}
          <Focusable className="NumpadGrid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gridTemplateRows: "repeat(4, 1fr)", gridGap: "0.5rem", padding: "8px 0" }}>
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
            <DialogButton onClick={() => enterDigit(".")}>.</DialogButton>
          </Focusable>
        </React.Fragment>
      )}
    </React.Fragment>
  );
}