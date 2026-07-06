import React from "react";
import { TextField } from "decky-frontend-lib";

interface PasswordInputProps {
  style?: React.CSSProperties;
  label?: string;
  value?: string;
  onChange?: (e: string) => void;
}

export const PasswordInput = (props: PasswordInputProps): JSX.Element => {
  const { style, label, value, onChange } = props;

  // Mask the input via CSS instead of type="password": Valve's TextField
  // manages the underlying input's type itself and resets it, so neither
  // bIsPassword nor forcing input.type sticks (its behavior apparently
  // changed with some Steam client update). The style prop however is passed
  // through to the underlying <input>, and -webkit-text-security masks the
  // rendered characters in CEF/Chromium independently of the input type.
  return (
    <TextField
      label={label}
      style={{ ...style, WebkitTextSecurity: "disc" } as React.CSSProperties}
      bIsPassword={true}
      bShowClearAction={(value?.length ?? 0) > 0}
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  );
}
