/**
 * Stand-ins for the Steam UI components the panel is built from.
 *
 * The real @decky/ui expects to run inside the Steam client, so the panel can
 * only be rendered against replacements. They render plain elements and keep
 * every label as text, which is what the tests then look for. Only the props
 * the tests assert on are declared: layout, bottomSeparator, focusable and the
 * rest of Steam's presentation props are dropped, so nothing here can tell
 * whether the panel still passes them. Anything that has to be checked must be
 * recorded, the way textFieldProps and focusableProps do.
 */
import React, { FC, ReactNode } from "react";

type Child = { children?: ReactNode };

export const PanelSection: FC<Child & { title?: string }> = ({ title, children }) => (
  <section>{title && <h2>{title}</h2>}{children}</section>
);

export const PanelSectionRow: FC<Child> = ({ children }) => <div>{children}</div>;

// A <label> rather than a <div>, so the label text is really associated with
// the input inside it - the modals label their text fields through the Field
// around them, and a test should be able to find them the way a user does.
export const Field: FC<Child & { label?: ReactNode }> = ({ label, children }) => (
  <label>{label !== undefined && <span>{label}</span>}{children}</label>
);

export const ButtonItem: FC<Child & { onClick?: () => void; disabled?: boolean }> = (
  { onClick, disabled, children }
) => (
  <button onClick={onClick} disabled={disabled}>{children}</button>
);

// The description sits outside the <label> so it does not become part of the
// checkbox's accessible name - it is a help text the row shows on request.
export const ToggleField: FC<{
  label?: ReactNode;
  description?: ReactNode;
  checked?: boolean;
  disabled?: boolean;
  onChange?: (value: boolean) => void;
}> = ({ label, description, checked, disabled, onChange }) => (
  <div>
    <label>
      {label}
      <input type="checkbox" checked={!!checked} disabled={disabled}
             onChange={() => onChange?.(!checked)} />
    </label>
    {description !== undefined && <span>{description}</span>}
  </div>
);

// Given a role so a test can assert "busy" without depending on markup
export const Spinner: FC<{ style?: object }> = () => <div role="progressbar" />;

/** Every set of props a Focusable was rendered with, in order - the only way
 *  to reach the gamepad handlers, which the DOM knows nothing about. */
export const focusableProps: Record<string, unknown>[] = [];

// Steam's own focus/gamepad props mean nothing to the DOM and React warns about
// each one, so they are dropped rather than forwarded. The role and label are
// added: the real Focusable is pressed by gamepad or click and carries no
// implicit role, and a test should find it the way a screen reader would rather
// than by its position among its siblings.
export const Focusable: FC<Child & Record<string, unknown>> = ({ children, ...rest }) => {
  focusableProps.push(rest);
  const passed = Object.fromEntries(
    Object.entries(rest).filter(([key]) => !/^on(Activate|Gamepad|OK|Cancel|Secondary|Option|Menu)/.test(key))
  );
  const label = rest.onOKActionDescription;
  return (
    <div role="button" aria-label={typeof label === "string" ? label : undefined}
         {...passed}>{children}</div>
  );
};

export const ModalRoot: FC<Child> = ({ children }) => <div>{children}</div>;

// `disabled` is forwarded, unlike the focus props above: the modals use it to
// keep a half-filled form from being submitted, which is behaviour a test has
// to be able to see.
export const DialogButton: FC<Child & { onClick?: () => void; disabled?: boolean }> = (
  { onClick, disabled, children }
) => (
  <button onClick={onClick} disabled={disabled}>{children}</button>
);
export const DialogButtonPrimary = DialogButton;

/** Every set of props a TextField was rendered with, in order.
 *
 *  Some of what the panel passes cannot be seen in the DOM: jsdom drops CSS
 *  properties it does not know, and -webkit-text-security - the whole
 *  mechanism PasswordInput masks with - is one of them. Recording the props is
 *  the only way left to check that it was passed at all. */
export const textFieldProps: Record<string, unknown>[] = [];

// `description` is deliberately not rendered: the modals label their fields
// through the Field around them, and text inside that label would become part
// of its accessible name - "Client name" would stop matching.
export const TextField: FC<{
  label?: string;
  value?: string;
  onChange?: (e: { target: { value: string } }) => void;
  style?: React.CSSProperties;
}> = (props) => {
  const { label, value, style, onChange } = props;
  textFieldProps.push(props as Record<string, unknown>);
  return <input aria-label={label} value={value ?? ""} style={style}
                onChange={(e) => onChange?.(e as never)} />;
};

export const showModal = (() => {
  const fn = (...args: unknown[]) => { fn.calls.push(args); };
  fn.calls = [] as unknown[][];
  return fn;
})();

/** The recorded props and calls are module state and survive a test, so each
 *  one has to start from empty lists. */
export function resetStubs() {
  showModal.calls.length = 0;
  textFieldProps.length = 0;
  focusableProps.length = 0;
}

/** The element the panel most recently handed to showModal, ready to render. */
export function lastModal() {
  return showModal.calls[showModal.calls.length - 1]?.[0] as ReactNode;
}

export const staticClasses = { Title: "title" };
