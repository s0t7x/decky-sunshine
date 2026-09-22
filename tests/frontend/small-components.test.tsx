/**
 * The small pieces that have no test file of their own.
 *
 * Each exists to work around something about the Steam client rather than to
 * hold logic of its own, which makes them easy to "simplify" back into the
 * bug they were written for:
 *
 * - PasswordInput masks through CSS because Valve's TextField manages the
 *   underlying input's type itself and resets it, so type="password" does not
 *   stick.
 * - LabelWithInfo de-dupes its own presses, because a Focusable can deliver
 *   both onActivate and onClick for one press, and drops its highlight on
 *   touch, because the Deck fires the gamepad focus events for taps too and
 *   the highlight would stay stuck afterwards.
 * - playSound is the click feedback the rest of the Steam UI gives.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { focusableProps, resetStubs, textFieldProps } from "./stubs/decky-ui";
import { playedSounds } from "./sounds";
import { LabelWithInfo } from "../../src/components/LabelWithInfo";
import { PasswordInput } from "../../src/components/PasswordInput";
import { playSound } from "../../src/util/util";
import { withoutErrors } from "./errors";

beforeEach(() => {
  resetStubs();
});

const lastTextField = () => textFieldProps[textFieldProps.length - 1];

/** The info button is a Focusable, which the stub gives the role it plays and
 *  names from the description the component passes for the gamepad prompt. */
const infoButton = () => screen.getByRole("button", { name: "Toggle help" });

describe("password input", () => {
  it("asks the client for a password field as well as masking it", () => {
    // Belt and braces: bIsPassword is what the client should honour, the CSS
    // masking is what survives it resetting the input's type.
    render(<PasswordInput value="hunter2" />);

    expect(lastTextField().bIsPassword).toBe(true);
  });

  it("masks what is typed", () => {
    render(<PasswordInput value="hunter2" />);

    expect((lastTextField().style as Record<string, string>).WebkitTextSecurity).toBe("disc");
  });

  it("keeps the caller's own styling", () => {
    render(<PasswordInput value="" style={{ width: "20em" }} />);

    expect((lastTextField().style as Record<string, string>).width).toBe("20em");
  });

  it("reports what was typed as a plain string", () => {
    const onChange = vi.fn();
    render(<PasswordInput value="" onChange={onChange} />);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "hunter2" } });

    expect(onChange).toHaveBeenCalledWith("hunter2");
  });

  it("survives being used without a change handler", () => {
    render(<PasswordInput value="" />);

    withoutErrors(() =>
      fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } }));
  });

  it("offers to clear itself only once there is something to clear", () => {
    render(<PasswordInput value="" />);
    expect(lastTextField().bShowClearAction).toBe(false);

    render(<PasswordInput value="a" />);
    expect(lastTextField().bShowClearAction).toBe(true);
  });

  it("offers nothing to clear before it has a value at all", () => {
    render(<PasswordInput />);

    expect(lastTextField().bShowClearAction).toBe(false);
  });
});

describe("label with info", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // The de-dupe compares against performance.now(), which fake timers start
    // at zero - and zero is inside its own 300 ms window, so the very first
    // press would be swallowed. In the client the panel opens long after load.
    vi.advanceTimersByTime(1000);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const press = () => fireEvent.click(infoButton());

  it("shows the label it was given", () => {
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={() => {}} />);

    expect(screen.getByText("Fix image when docked")).toBeTruthy();
  });

  it("toggles the help text when pressed", () => {
    const onToggleHelp = vi.fn();
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={onToggleHelp} />);

    press();

    expect(onToggleHelp).toHaveBeenCalledTimes(1);
  });

  it("counts one press as one press even when it arrives twice", () => {
    const onToggleHelp = vi.fn();
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={onToggleHelp} />);
    const activate = focusableProps[focusableProps.length - 1].onActivate as (e?: unknown) => void;

    press();
    activate();

    expect(onToggleHelp).toHaveBeenCalledTimes(1);
  });

  it("can be pressed again afterwards", () => {
    const onToggleHelp = vi.fn();
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={onToggleHelp} />);

    press();
    vi.advanceTimersByTime(400);
    press();

    expect(onToggleHelp).toHaveBeenCalledTimes(2);
  });

  it("is ready again exactly when the window is over, not a tick later", () => {
    // Pinned on the boundary rather than comfortably past it: at exactly
    // 300 ms the window has passed, and only this distinguishes `< 300` from
    // `<= 300`. A test that waits 400 ms passes either way.
    const onToggleHelp = vi.fn();
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={onToggleHelp} />);

    press();
    vi.advanceTimersByTime(300);
    press();

    expect(onToggleHelp).toHaveBeenCalledTimes(2);
  });

  it("does not toggle the row it sits in", () => {
    const onToggleHelp = vi.fn();
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={onToggleHelp} />);
    const activate = focusableProps[focusableProps.length - 1].onActivate as (e: unknown) => void;
    const stopPropagation = vi.fn();

    activate({ stopPropagation });

    expect(stopPropagation).toHaveBeenCalled();
  });

  const button = infoButton;
  /** Gamepad focus events reach React through the Focusable, not the DOM, so
   *  they are called directly - inside act, because they set state. */
  const gamepad = (name: string) => () =>
    act(() => { (focusableProps[focusableProps.length - 1][name] as () => void)(); });

  it("is not highlighted until something selects it", () => {
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={() => {}} />);

    expect(button().style.boxShadow).toBe("none");
  });

  it("highlights itself while a controller has it selected", () => {
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={() => {}} />);

    gamepad("onGamepadFocus")();

    expect(button().style.boxShadow).not.toBe("none");
  });

  it("drops the highlight again when the selection moves on", () => {
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={() => {}} />);
    gamepad("onGamepadFocus")();

    gamepad("onGamepadBlur")();

    expect(button().style.boxShadow).toBe("none");
  });

  it("does not leave a tap highlighted", () => {
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={() => {}} />);

    fireEvent.touchEnd(button());
    gamepad("onGamepadFocus")();      // the Deck sends these for a tap too

    expect(button().style.boxShadow).toBe("none");
  });

  it("goes back to highlighting once the tap is over", () => {
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={() => {}} />);
    fireEvent.touchEnd(button());

    vi.advanceTimersByTime(600);
    gamepad("onGamepadFocus")();

    expect(button().style.boxShadow).not.toBe("none");
  });

  it("goes back to highlighting exactly when the suppression ends", () => {
    // The other boundary, and pinned for the same reason as the de-dupe
    // window: at exactly 500 ms the tap no longer suppresses anything.
    render(<LabelWithInfo title="Fix image when docked" onToggleHelp={() => {}} />);
    fireEvent.touchEnd(button());

    vi.advanceTimersByTime(500);
    gamepad("onGamepadFocus")();

    expect(button().style.boxShadow).not.toBe("none");
  });
});

describe("play sound", () => {
  it("plays the sound it was given", () => {
    const played = playedSounds();

    playSound("https://steamloopback.host/sounds/deck_ui_side_menu_fly_in.wav");

    expect(played).toEqual(["https://steamloopback.host/sounds/deck_ui_side_menu_fly_in.wav"]);
  });
});
