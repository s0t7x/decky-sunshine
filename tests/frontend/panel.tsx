/**
 * Shared helpers for the tests that render the whole panel.
 *
 * Three files did this with three near-identical copies that had already
 * drifted apart - different defaults, and different ideas of when the panel
 * had settled. One copy waits for a *state* rather than for a call to have
 * gone out, which is the stronger condition and the one every test wants.
 */
import { ReactElement, ReactNode, cloneElement } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect } from "vitest";

import { calls, setCallHandler } from "./stubs/decky-api";
import { lastModal } from "./stubs/decky-ui";

/**
 * What the entry point evaluates to here. The real definePlugin is typed as
 * returning a registration function; the stub calls the factory instead, so
 * what comes back is the plugin object itself.
 */
type Panel = { name: string; content: ReactNode };

/** The whole object the loader is handed, not just the panel inside it. */
export async function loadPlugin(): Promise<Panel> {
  return (await import("../../src/index")).default as unknown as Panel;
}

export type VersionInfo = {
  current_version: string | null;
  update_available: boolean;
  update_version: string | null;
};

export const IDLE_VERSION: VersionInfo =
  { current_version: "2026.914.233613", update_available: false, update_version: null };
export const PENDING_UPDATE: VersionInfo =
  { current_version: "2026.516.143833", update_available: true, update_version: "2026.914.233613" };

/** A promise that never settles, for looking at the panel mid-call. */
export const neverAnswers = () => new Promise(() => {});

/** Script the backend. An answer may be a value or a function of the call's
 *  arguments, which is how a test makes the backend change its mind. */
export function answerWith(answers: Record<string, unknown> = {}) {
  const defaults: Record<string, unknown> = {
    is_sunshine_running: true,
    are_credentials_valid: true,
    get_force_composition: false,
    get_sunshine_version_info: IDLE_VERSION,
    get_web_ui_info: { ip: "192.168.1.38", editing_ready: true },
  };
  setCallHandler((method, args) => {
    const answer = method in answers ? answers[method] : defaults[method];
    return typeof answer === "function" ? (answer as (a: unknown[]) => unknown)(args) : answer;
  });
}

/**
 * Renders the panel with the backend scripted, and waits until its opening
 * round of calls has landed - everything built on this starts from a settled
 * panel rather than from "a call went out".
 */
export async function openPanel(answers: Record<string, unknown> = {}) {
  answerWith(answers);
  const view = render((await loadPlugin()).content);
  await waitFor(() => expect(screen.queryByText(/Checking status/)).toBeNull());
  return view;
}

/** The panel with nothing answered yet: what it shows before it knows. */
export async function openPanelPending() {
  setCallHandler(() => neverAnswers());
  return render((await loadPlugin()).content);
}

export const status = () => screen.getByText(/^Status: /).textContent;
export const button = (name: string | RegExp) =>
  screen.getByRole("button", { name }) as HTMLButtonElement;
export const countOf = (method: string) => calls.filter((c) => c.method === method).length;

type Dialog = ReturnType<typeof within>;

/**
 * Render the dialog the panel last opened, scoped so its buttons cannot be
 * confused with the panel's own.
 *
 * closeModal is injected the way the real showModal does it. The dialogs close
 * themselves through it when the panel's callback reports success, so it is
 * the only place a test can see that the answer travelled back at all.
 */
export function openDialog(closeModal: () => void = () => {}): Dialog {
  const element = lastModal() as ReactElement<{ closeModal?: () => void }>;
  return within(render(cloneElement(element, { closeModal })).container);
}

export function logIn(dialog: Dialog, username = "admin", password = "hunter2") {
  fireEvent.change(dialog.getByLabelText("Username"), { target: { value: username } });
  fireEvent.change(dialog.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(dialog.getByRole("button", { name: "Login" }));
}

export function pairClient(dialog: Dialog, clientName = "TV", pin = "1234") {
  fireEvent.change(dialog.getByLabelText("Client name"), { target: { value: clientName } });
  fireEvent.change(dialog.getByLabelText("PIN"), { target: { value: pin } });
  fireEvent.click(dialog.getByRole("button", { name: "Pair" }));
}
