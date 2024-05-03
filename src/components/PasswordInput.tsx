import React from "react";
import { TextField } from "decky-frontend-lib";

// NumericInputProps interface with value and onChange properties
interface PasswordInputProps {
  label: string;
  value: string;
  onChange: (e: string) => void;
}

export const PasswordInput = (props: PasswordInputProps): JSX.Element => {
  const { label, value, onChange } = props;

  const tfId = Math.trunc(Math.random() * 999_999)

  const doOnChange = (e: any) => {
    e.target.type = "password"
    onChange(e.target.value)
  }

  return (
    <React.Fragment>
      <TextField id={`passwordInput-${tfId}`} typeof="password" itemType="password" label={label} bIsPassword={true} bShowClearAction={value.length > 0} value={value} onChange={doOnChange}></TextField>
    </React.Fragment>
  );
}