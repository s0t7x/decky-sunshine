/**
 * Tests for the login dialog.
 *
 * Sunshine's Web API is Basic-auth'd and the plugin holds the header, so this
 * dialog is the only way in after the generated credentials are lost or
 * changed. Two of its three outcomes look alike from the outside and must not:
 * "Sunshine said no" is the user's problem to fix, "the call never got an
 * answer" is not, and telling them apart is what keeps someone from retyping a
 * password that was correct all along.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CredentialsModal } from "../../src/components/CredentialsModal";
import { resetStubs, textFieldProps } from "./stubs/decky-ui";
import { playedSounds } from "./sounds";
import { withoutErrors } from "./errors";

/** The last render of each field, found by what it is rather than by where it
 *  sits: PasswordInput is the one that sets bIsPassword. */
const lastField = (isPassword: boolean) =>
  [...textFieldProps].reverse().find((p) => (p.bIsPassword === true) === isPassword)!;

const STORED_USERNAME = "decky_sunshine:localUsername";

/** jsdom has no media stack, so play is replaced either way; see ./sounds. */
let played: string[];

beforeEach(() => {
  localStorage.clear();
  resetStubs();
  played = playedSounds();
});

const loginButton = () => screen.getByRole("button", { name: "Login" }) as HTMLButtonElement;
const usernameField = () => screen.getByLabelText("Username");
const passwordField = () => screen.getByLabelText("Password");

function fill(username: string, password: string) {
  fireEvent.change(usernameField(), { target: { value: username } });
  fireEvent.change(passwordField(), { target: { value: password } });
}

describe("credentials modal", () => {
  it("offers the username the plugin generates for itself", () => {
    render(<CredentialsModal onLogin={async () => true} />);

    expect((usernameField() as HTMLInputElement).value).toBe("decky_sunshine");
  });

  it("starts with an empty password field", () => {
    // The username is remembered on purpose, the password must never be - and
    // a field that came up pre-filled would invite a login with a stale one.
    localStorage.setItem(STORED_USERNAME, "someone_else");

    render(<CredentialsModal onLogin={async () => true} />);

    expect((passwordField() as HTMLInputElement).value).toBe("");
  });

  it("gives the submit the click feedback the rest of the client gives", async () => {
    render(<CredentialsModal onLogin={async () => true} />);

    fill("admin", "hunter2");
    fireEvent.click(loginButton());

    await waitFor(() => expect(played).toEqual(["https://steamloopback.host/sounds/deck_ui_side_menu_fly_in.wav"]));
  });

  it("remembers the username from the last successful visit", () => {
    localStorage.setItem(STORED_USERNAME, "someone_else");

    render(<CredentialsModal onLogin={async () => true} />);

    expect((usernameField() as HTMLInputElement).value).toBe("someone_else");
  });

  it("sends what the user typed", async () => {
    const onLogin = vi.fn().mockResolvedValue(true);
    render(<CredentialsModal onLogin={onLogin} />);

    fill("admin", "hunter2");
    fireEvent.click(loginButton());

    await waitFor(() => expect(onLogin).toHaveBeenCalledWith("admin", "hunter2"));
  });

  it("keeps the username but never the password", async () => {
    render(<CredentialsModal onLogin={async () => true} />);

    fill("admin", "hunter2");
    fireEvent.click(loginButton());

    await waitFor(() => expect(localStorage.getItem(STORED_USERNAME)).toBe("admin"));
    expect(JSON.stringify(localStorage)).not.toContain("hunter2");
  });

  it("closes once the login worked", async () => {
    const closeModal = vi.fn();
    render(<CredentialsModal closeModal={closeModal} onLogin={async () => true} />);

    fill("admin", "hunter2");
    fireEvent.click(loginButton());

    await waitFor(() => expect(closeModal).toHaveBeenCalled());
  });

  it("says the login was refused and stays open", async () => {
    const closeModal = vi.fn();
    render(<CredentialsModal closeModal={closeModal} onLogin={async () => false} />);

    fill("admin", "wrong");
    fireEvent.click(loginButton());

    expect(await screen.findByText(/Login failed/)).toBeTruthy();
    expect(closeModal).not.toHaveBeenCalled();
  });

  it("tells a failed call apart from a refused login", async () => {
    render(<CredentialsModal onLogin={async () => null} />);

    fill("admin", "hunter2");
    fireEvent.click(loginButton());

    expect(await screen.findByText(/An error occurred during login/)).toBeTruthy();
    expect(screen.queryByText(/Login failed/)).toBeNull();
  });

  it("shows that it is waiting while the backend is working", async () => {
    let release: (value: boolean) => void = () => {};
    render(<CredentialsModal onLogin={() => new Promise<boolean>((r) => { release = r; })} />);

    fill("admin", "hunter2");
    fireEvent.click(loginButton());

    expect(await screen.findByText("Waiting for response...")).toBeTruthy();
    release(false);
    await waitFor(() => expect(screen.queryByText("Waiting for response...")).toBeNull());
  });

  it("cannot be submitted twice while the first attempt is in flight", async () => {
    const onLogin = vi.fn(() => new Promise<boolean>(() => {}));
    render(<CredentialsModal onLogin={onLogin} />);

    fill("admin", "hunter2");
    fireEvent.click(loginButton());
    await waitFor(() => expect(loginButton().disabled).toBe(true));

    fireEvent.click(loginButton());
    expect(onLogin).toHaveBeenCalledTimes(1);
  });

  it("will not submit an empty password", () => {
    render(<CredentialsModal onLogin={async () => true} />);

    fill("admin", "");

    expect(loginButton().disabled).toBe(true);
  });

  it("will not submit an empty username", () => {
    render(<CredentialsModal onLogin={async () => true} />);

    fill("", "hunter2");

    expect(loginButton().disabled).toBe(true);
  });

  it("clears the failure message when the password is retyped", async () => {
    render(<CredentialsModal onLogin={async () => false} />);
    fill("admin", "wrong");
    fireEvent.click(loginButton());
    await screen.findByText(/Login failed/);

    fireEvent.change(passwordField(), { target: { value: "right" } });

    expect(screen.queryByText(/Login failed/)).toBeNull();
  });

  it("clears the failure message when the username is retyped", async () => {
    render(<CredentialsModal onLogin={async () => false} />);
    fill("admin", "wrong");
    fireEvent.click(loginButton());
    await screen.findByText(/Login failed/);

    fireEvent.change(usernameField(), { target: { value: "root" } });

    expect(screen.queryByText(/Login failed/)).toBeNull();
  });

  it("says nothing about errors before anything was tried", () => {
    render(<CredentialsModal onLogin={async () => true} />);

    expect(screen.queryByText(/An error occurred during login/)).toBeNull();
    expect(screen.queryByText(/Login failed/)).toBeNull();
  });

  it("does not call a refused login an error", async () => {
    render(<CredentialsModal onLogin={async () => false} />);

    fill("admin", "wrong");
    fireEvent.click(loginButton());

    await screen.findByText(/Login failed/);
    expect(screen.queryByText(/An error occurred during login/)).toBeNull();
  });

  it("accepts a login of one character each", () => {
    render(<CredentialsModal onLogin={async () => true} />);

    fill("a", "b");

    expect(loginButton().disabled).toBe(false);
  });

  it("offers to clear a field only once it holds something", () => {
    render(<CredentialsModal onLogin={async () => true} />);
    const username = () => textFieldProps.find((p) => p.value === "decky_sunshine");

    expect(username()!.bShowClearAction).toBe(true);

    fireEvent.change(usernameField(), { target: { value: "" } });
    expect(lastField(false).bShowClearAction).toBe(false);
  });

  it("can be cancelled even when nothing is listening", () => {
    render(<CredentialsModal onLogin={async () => true} />);

    withoutErrors(() => fireEvent.click(screen.getByRole("button", { name: "Cancel" })));
  });

  it("can be left without logging in", () => {
    const closeModal = vi.fn();
    const onLogin = vi.fn();
    render(<CredentialsModal closeModal={closeModal} onLogin={onLogin} />);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(closeModal).toHaveBeenCalled();
    expect(onLogin).not.toHaveBeenCalled();
  });

  it("masks the password rather than showing it on a screen that may be streamed", () => {
    render(<CredentialsModal onLogin={async () => true} />);

    expect((lastField(true).style as Record<string, string>).WebkitTextSecurity).toBe("disc");
  });
});
