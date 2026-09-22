/**
 * Tests for the panel itself: what it shows about Sunshine and what its
 * buttons do.
 *
 * The panel is the only thing most users ever see of this plugin, and almost
 * everything it does is asynchronous - a start takes as long as Sunshine takes
 * to come up. So the interesting part is not the happy path but the states in
 * between: what it says while it is working, what it refuses to let the user
 * press twice, and whether it tells the truth again afterwards when the call
 * failed.
 *
 * What the panel hands to a modal is checked by rendering that modal: showModal
 * is stubbed to record the element, which is the seam between the panel's
 * callbacks and the dialogs (tested on their own elsewhere).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import backend from "../../src/util/backend";
import { calls, reset } from "./stubs/decky-api";
import { lastModal, resetStubs } from "./stubs/decky-ui";
import {
  IDLE_VERSION, PENDING_UPDATE, button, countOf, loadPlugin, logIn, neverAnswers,
  openDialog, openPanel, openPanelPending, pairClient, status,
} from "./panel";

beforeEach(() => {
  reset();
  resetStubs();
  localStorage.clear();            // CredentialsModal remembers the username
  // jsdom has no media stack; the dialogs play a sound on submit
  vi.spyOn(window.HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
});

describe("what the loader registers", () => {
  it("registers the plugin under the name the user sees in the menu", async () => {
    // Decky puts this in its plugin list and its settings. Nothing in the
    // panel renders it, so no other test here would notice it changing.
    expect((await loadPlugin()).name).toBe("Decky Sunshine");
  });
});

describe("status", () => {
  it("says it is checking before the first answer arrives", async () => {
    await openPanelPending();

    expect(screen.getByText("Status: Checking status...")).toBeTruthy();
  });

  it("offers nothing it does not know the answer to yet", async () => {
    await openPanelPending();

    // The panel must not answer for a Sunshine nobody has asked yet - except
    // the toggle, which has no "unknown" to show
    expect(screen.queryByRole("button", { name: "Stop Sunshine" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Restart Sunshine" })).toBeNull();
    expect(screen.queryByText("Update available")).toBeNull();
    expect(screen.queryByText("Up to date")).toBeNull();
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByText(/You need to log into Sunshine/)).toBeNull();
  });

  it("shows that it is busy while it works", async () => {
    await openPanel({ is_sunshine_running: false, start_sunshine: neverAnswers });

    fireEvent.click(button("Start Sunshine"));

    await waitFor(() => expect(screen.getAllByRole("progressbar").length).toBeGreaterThan(0));
  });

  it("stops showing that once it is done", async () => {
    await openPanel({ is_sunshine_running: false, start_sunshine: true });

    fireEvent.click(button("Start Sunshine"));

    await waitFor(() => expect(screen.queryAllByRole("progressbar")).toHaveLength(0));
  });

  it("reports a running Sunshine", async () => {
    await openPanel();

    expect(status()).toBe("Status: Running");
  });

  it("reports a stopped one", async () => {
    await openPanel({ is_sunshine_running: false });

    expect(status()).toBe("Status: Stopped");
  });

  it("says what it is doing while starting", async () => {
    await openPanel({ is_sunshine_running: false, start_sunshine: neverAnswers });

    fireEvent.click(button("Start Sunshine"));

    await waitFor(() => expect(status()).toBe("Status: Starting..."));
  });

  it("says what it is doing while stopping", async () => {
    await openPanel({ stop_sunshine: neverAnswers });

    fireEvent.click(button("Stop Sunshine"));

    await waitFor(() => expect(status()).toBe("Status: Stopping..."));
  });

  it("says what it is doing while restarting", async () => {
    await openPanel({ restart_sunshine: neverAnswers });

    fireEvent.click(button("Restart Sunshine"));

    await waitFor(() => expect(status()).toBe("Status: Restarting..."));
  });
});

describe("starting and stopping", () => {
  it("offers to start a Sunshine that is down", async () => {
    await openPanel({ is_sunshine_running: false });

    expect(button("Start Sunshine")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Restart Sunshine" })).toBeNull();
  });

  it("offers to stop and restart one that is up", async () => {
    await openPanel();

    expect(button("Stop Sunshine")).toBeTruthy();
    expect(button("Restart Sunshine")).toBeTruthy();
  });

  it("starts Sunshine and reports the new state", async () => {
    let running = false;
    await openPanel({
      is_sunshine_running: () => running,
      start_sunshine: () => { running = true; return true; },
    });

    fireEvent.click(button("Start Sunshine"));

    await waitFor(() => expect(status()).toBe("Status: Running"));
    expect(countOf("start_sunshine")).toBe(1);
  });

  it("stops Sunshine and reports the new state", async () => {
    let running = true;
    await openPanel({
      is_sunshine_running: () => running,
      stop_sunshine: () => { running = false; return true; },
    });

    fireEvent.click(button("Stop Sunshine"));

    await waitFor(() => expect(status()).toBe("Status: Stopped"));
  });

  it("goes back to the truth when the stop did not work", async () => {
    await openPanel({ stop_sunshine: false });

    fireEvent.click(button("Stop Sunshine"));

    await waitFor(() => expect(status()).toBe("Status: Running"));
  });

  it("goes back to the truth when the restart did not work", async () => {
    await openPanel({ restart_sunshine: false });

    fireEvent.click(button("Restart Sunshine"));

    await waitFor(() => expect(status()).toBe("Status: Running"));
    expect(button("Restart Sunshine").disabled).toBe(false);
  });

  it("restarts with one call rather than a stop and a start", async () => {
    await openPanel({ restart_sunshine: true });

    fireEvent.click(button("Restart Sunshine"));

    await waitFor(() => expect(countOf("restart_sunshine")).toBe(1));
    expect(countOf("stop_sunshine") + countOf("start_sunshine")).toBe(0);
  });

  it("goes back to the truth when the start did not work", async () => {
    await openPanel({ is_sunshine_running: false, start_sunshine: false });

    fireEvent.click(button("Start Sunshine"));

    await waitFor(() => expect(status()).toBe("Status: Stopped"));
  });

  it("recovers when the call itself throws", async () => {
    await openPanel({
      is_sunshine_running: false,
      start_sunshine: () => { throw new Error("backend gone"); },
    });

    fireEvent.click(button("Start Sunshine"));

    await waitFor(() => expect(status()).toBe("Status: Stopped"));
    expect(button("Start Sunshine").disabled).toBe(false);
  });

  it("leaves a trace in the log when a start fails", async () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    await openPanel({ is_sunshine_running: false, start_sunshine: false });

    fireEvent.click(button("Start Sunshine"));

    await waitFor(() => expect(logged.mock.calls.some(
      (args) => args.join(" ").includes("Failed to start Sunshine"))).toBe(true));
  });

  it("leaves a trace in the log when a stop fails", async () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    await openPanel({ stop_sunshine: false });

    fireEvent.click(button("Stop Sunshine"));

    await waitFor(() => expect(logged.mock.calls.some(
      (args) => args.join(" ").includes("Failed to stop Sunshine"))).toBe(true));
  });

  it("leaves a trace in the log when a restart fails", async () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    await openPanel({ restart_sunshine: false });

    fireEvent.click(button("Restart Sunshine"));

    await waitFor(() => expect(logged.mock.calls.some(
      (args) => args.join(" ").includes("Failed to restart Sunshine"))).toBe(true));
  });

  it("says nothing about a start that worked", async () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    let running = false;
    await openPanel({
      is_sunshine_running: () => running,
      start_sunshine: () => { running = true; return true; },
    });

    fireEvent.click(button("Start Sunshine"));

    await waitFor(() => expect(status()).toBe("Status: Running"));
    expect(logged).not.toHaveBeenCalled();
  });

  it("says nothing about a restart that worked", async () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    await openPanel({ restart_sunshine: true });

    fireEvent.click(button("Restart Sunshine"));

    await waitFor(() => expect(button("Restart Sunshine").disabled).toBe(false));
    expect(logged).not.toHaveBeenCalled();
  });

  it("cannot be pressed again while it is working", async () => {
    await openPanel({ is_sunshine_running: false, start_sunshine: neverAnswers });

    fireEvent.click(button("Start Sunshine"));
    await waitFor(() => expect(button("Start Sunshine").disabled).toBe(true));
    fireEvent.click(button("Start Sunshine"));

    expect(countOf("start_sunshine")).toBe(1);
  });
});

describe("logging in", () => {
  it("stays out of the way while the credentials work", async () => {
    await openPanel();

    expect(screen.queryByText(/You need to log into Sunshine/)).toBeNull();
  });

  it("asks for a login when Sunshine rejects the credentials", async () => {
    await openPanel({ are_credentials_valid: false });

    expect(screen.getByText("You need to log into Sunshine")).toBeTruthy();
    expect(button("Login")).toBeTruthy();
  });

  it("says nothing while the answer is unknown", async () => {
    await openPanel({ are_credentials_valid: null });

    expect(screen.queryByText(/You need to log into Sunshine/)).toBeNull();
  });

  it("cannot log into a Sunshine that is not running", async () => {
    await openPanel({ are_credentials_valid: false, is_sunshine_running: false });

    expect(button("Login").disabled).toBe(true);
  });

  it("hands the login on to the backend", async () => {
    await openPanel({ are_credentials_valid: false, set_credentials: true });
    fireEvent.click(button("Login"));

    logIn(openDialog());

    await waitFor(() => expect(calls.some((c) => c.method === "set_credentials")).toBe(true));
    expect(calls.find((c) => c.method === "set_credentials")!.args).toEqual(["admin", "hunter2"]);
  });

  it("tells the dialog the login worked, so it closes", async () => {
    // The other direction: the callback has to report the backend's answer
    // back. Swallow it and the user types a correct password, gets told the
    // login failed, and the dialog never closes.
    await openPanel({ are_credentials_valid: false, set_credentials: true });
    fireEvent.click(button("Login"));
    const closeDialog = vi.fn();

    logIn(openDialog(closeDialog));

    await waitFor(() => expect(closeDialog).toHaveBeenCalled());
  });

  it("turns a failed login call into no answer rather than into a refusal", async () => {
    await openPanel({
      are_credentials_valid: false,
      set_credentials: () => { throw new Error("backend gone"); },
    });
    fireEvent.click(button("Login"));

    const modal = openDialog();
    logIn(modal);

    expect(await modal.findByText(/An error occurred during login/)).toBeTruthy();
  });
});

describe("what the panel does when the backend layer itself gives way", () => {
  // backend.* maps a failed call to null/false rather than throwing, so these
  // catch blocks are the panel's second line of defence. They are reachable
  // only by making the method itself reject - which is what a change to that
  // contract would look like.

  it("survives a start that rejects instead of answering", async () => {
    await openPanel({ is_sunshine_running: false });
    vi.spyOn(backend, "startSunshine").mockRejectedValue(new Error("gone"));

    fireEvent.click(button("Start Sunshine"));

    await waitFor(() => expect(button("Start Sunshine").disabled).toBe(false));
    expect(status()).toBe("Status: Stopped");
  });

  it("survives a restart that rejects instead of answering", async () => {
    await openPanel();
    vi.spyOn(backend, "restartSunshine").mockRejectedValue(new Error("gone"));

    fireEvent.click(button("Restart Sunshine"));

    await waitFor(() => expect(button("Restart Sunshine").disabled).toBe(false));
    expect(status()).toBe("Status: Running");
  });

  it("leaves a trace in the log when a start rejects", async () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    await openPanel({ is_sunshine_running: false });
    vi.spyOn(backend, "startSunshine").mockRejectedValue(new Error("gone"));

    fireEvent.click(button("Start Sunshine"));

    await waitFor(() => expect(logged.mock.calls.some(
      (args) => args.join(" ").includes("Failed to start/stop Sunshine"))).toBe(true));
  });

  it("leaves a trace in the log when a restart rejects", async () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    await openPanel();
    vi.spyOn(backend, "restartSunshine").mockRejectedValue(new Error("gone"));

    fireEvent.click(button("Restart Sunshine"));

    await waitFor(() => expect(logged.mock.calls.some(
      (args) => args.join(" ").includes("Failed to restart Sunshine:"))).toBe(true));
  });

  it("leaves a trace in the log when a login rejects", async () => {
    // The dialog only says "an error occurred"; which call broke, and with
    // what, exists nowhere but here.
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    const gone = new Error("gone");
    await openPanel({ are_credentials_valid: false });
    vi.spyOn(backend, "setCredentials").mockRejectedValue(gone);
    fireEvent.click(button("Login"));

    logIn(openDialog());

    await waitFor(() => expect(logged)
      .toHaveBeenCalledWith("[SUN]", "Failed to set credentials:", gone));
  });

  it("leaves a trace in the log when a pairing rejects", async () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    const gone = new Error("gone");
    await openPanel();
    vi.spyOn(backend, "pair").mockRejectedValue(gone);
    fireEvent.click(button("Pair Client"));

    pairClient(openDialog());

    await waitFor(() => expect(logged)
      .toHaveBeenCalledWith("[SUN]", "Failed to pair Sunshine:", gone));
  });

  it("re-checks Sunshine after a login that could not be carried out", async () => {
    await openPanel({ are_credentials_valid: false });
    vi.spyOn(backend, "setCredentials").mockRejectedValue(new Error("gone"));
    fireEvent.click(button("Login"));
    const before = countOf("is_sunshine_running");

    const modal = openDialog();
    logIn(modal);

    await waitFor(() => expect(countOf("is_sunshine_running")).toBeGreaterThan(before));
  });

  it("re-checks Sunshine after a pairing that could not be carried out", async () => {
    await openPanel();
    vi.spyOn(backend, "pair").mockRejectedValue(new Error("gone"));
    fireEvent.click(button("Pair Client"));
    const before = countOf("is_sunshine_running");

    const modal = openDialog();
    pairClient(modal);

    await waitFor(() => expect(countOf("is_sunshine_running")).toBeGreaterThan(before));
  });

  it("keeps a rejected login from escaping into the dialog", async () =>{
    await openPanel({ are_credentials_valid: false });
    vi.spyOn(backend, "setCredentials").mockRejectedValue(new Error("gone"));
    fireEvent.click(button("Login"));

    const modal = openDialog();
    logIn(modal);

    expect(await modal.findByText(/An error occurred during login/)).toBeTruthy();
  });

  it("keeps a rejected pairing from escaping into the dialog", async () => {
    await openPanel();
    vi.spyOn(backend, "pair").mockRejectedValue(new Error("gone"));
    fireEvent.click(button("Pair Client"));

    const modal = openDialog();
    pairClient(modal);

    expect(await modal.findByText(/Pairing failed/)).toBeTruthy();
  });
});

describe("pairing", () => {
  it("is offered once Sunshine runs and the credentials work", async () => {
    await openPanel();

    expect(button("Pair Client").disabled).toBe(false);
  });

  it("is not offered while Sunshine is down", async () => {
    await openPanel({ is_sunshine_running: false });

    expect(button("Pair Client").disabled).toBe(true);
  });

  it("is not offered without working credentials", async () => {
    await openPanel({ are_credentials_valid: false });

    expect(button("Pair Client").disabled).toBe(true);
  });

  it("hands the PIN and the client name on to the backend", async () => {
    await openPanel({ pair: true });
    fireEvent.click(button("Pair Client"));

    pairClient(openDialog());

    await waitFor(() => expect(calls.some((c) => c.method === "pair")).toBe(true));
    expect(calls.find((c) => c.method === "pair")!.args).toEqual(["1234", "TV"]);
  });

  it("tells the dialog the pairing worked, so it closes", async () => {
    // Swallowing the answer costs the user the PIN: Sunshine really paired,
    // the dialog says it failed, and the PIN is only valid for one attempt.
    await openPanel({ pair: true });
    fireEvent.click(button("Pair Client"));
    const closeDialog = vi.fn();

    pairClient(openDialog(closeDialog));

    await waitFor(() => expect(closeDialog).toHaveBeenCalled());
  });

  it("re-checks Sunshine afterwards, because pairing has been seen to kill it", async () => {
    await openPanel({ pair: true });
    fireEvent.click(button("Pair Client"));
    const before = countOf("is_sunshine_running");

    pairClient(openDialog());

    await waitFor(() => expect(countOf("is_sunshine_running")).toBeGreaterThan(before));
  });

  it("reports a pairing the backend could not carry out as failed", async () => {
    await openPanel({ pair: () => { throw new Error("backend gone"); } });
    fireEvent.click(button("Pair Client"));

    pairClient(openDialog());

    expect(await screen.findByText(/Pairing failed/)).toBeTruthy();
  });
});

describe("the docked-image toggle", () => {
  const toggle = () => screen.getByRole("checkbox") as HTMLInputElement;

  it("starts out showing what was stored", async () => {
    await openPanel({ get_force_composition: true });

    await waitFor(() => expect(toggle().checked).toBe(true));
  });

  it("starts out off when nothing was stored", async () => {
    await openPanel();

    expect(toggle().checked).toBe(false);
  });

  it("persists a change immediately", async () => {
    await openPanel();

    fireEvent.click(toggle());

    await waitFor(() => expect(calls.some((c) => c.method === "set_force_composition")).toBe(true));
    expect(calls.find((c) => c.method === "set_force_composition")!.args).toEqual([true]);
  });

  it("keeps its own state so the switch does not jump back", async () => {
    await openPanel();

    fireEvent.click(toggle());

    await waitFor(() => expect(toggle().checked).toBe(true));
  });

  it("explains itself on request, and only then", async () => {
    await openPanel();
    expect(screen.queryByText(/squeezed into part of the screen/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Toggle help" }));

    expect(await screen.findByText(/squeezed into part of the screen/)).toBeTruthy();
  });
});

describe("the web ui address", () => {
  it("is offered while Sunshine runs", async () => {
    await openPanel();

    expect(button("Show Web UI address").disabled).toBe(false);
  });

  it("is not offered while it is down - there would be nothing to reach", async () => {
    await openPanel({ is_sunshine_running: false });

    expect(button("Show Web UI address").disabled).toBe(true);
  });

  it("opens the Web UI dialog with this Deck's address", async () => {
    await openPanel();

    fireEvent.click(button("Show Web UI address"));

    render(lastModal());
    expect(await screen.findByText("https://192.168.1.38:47990")).toBeTruthy();
  });
});

describe("the stored credentials", () => {
  const CREDENTIALS = { username: "decky_sunshine", password: "s3cr3t-pass" };

  it("are not read until they are asked for", async () => {
    await openPanel({ get_credentials: CREDENTIALS });

    expect(countOf("get_credentials")).toBe(0);
  });

  it("are shown on request", async () => {
    await openPanel({ get_credentials: CREDENTIALS });

    fireEvent.click(button("Show credentials"));

    expect(await screen.findByText("s3cr3t-pass")).toBeTruthy();
  });

  it("can be hidden again", async () => {
    await openPanel({ get_credentials: CREDENTIALS });
    fireEvent.click(button("Show credentials"));
    await screen.findByText("s3cr3t-pass");

    fireEvent.click(button("Hide credentials"));

    expect(screen.queryByText("s3cr3t-pass")).toBeNull();
  });

  it("say so when there are none", async () => {
    await openPanel({ get_credentials: null });

    fireEvent.click(button("Show credentials"));

    expect(await screen.findByText("None stored")).toBeTruthy();
  });

  it("cannot be asked for twice at once", async () => {
    await openPanel({ get_credentials: neverAnswers });

    fireEvent.click(button("Show credentials"));
    await waitFor(() => expect(button("Show credentials").disabled).toBe(true));
    fireEvent.click(button("Show credentials"));

    expect(countOf("get_credentials")).toBe(1);
  });
});

describe("updating", () => {
  it("installs the update and drops the banner", async () => {
    await openPanel({ get_sunshine_version_info: PENDING_UPDATE, update_sunshine: true });

    fireEvent.click(button("Update"));

    await waitFor(() => expect(screen.queryByText("Update available")).toBeNull());
    expect(countOf("update_sunshine")).toBe(1);
  });

  it("drops an earlier up-to-date verdict once an update is installed", async () => {
    // "Up to date" is a statement about the last check the user asked for.
    // Installing an update makes it stale, so it has to go until they ask again.
    let info: unknown = IDLE_VERSION;
    await openPanel({ get_sunshine_version_info: () => info, update_sunshine: true });

    fireEvent.click(button("Check for updates"));
    await screen.findByText("Up to date");
    info = PENDING_UPDATE;
    fireEvent.click(button("Check for updates"));
    await screen.findByText("Update available");

    fireEvent.click(button("Update"));

    await waitFor(() => expect(screen.queryByText("Update available")).toBeNull());
    expect(screen.queryByText("Up to date")).toBeNull();
  });

  it("keeps the banner when the update did not work", async () => {
    await openPanel({ get_sunshine_version_info: PENDING_UPDATE, update_sunshine: false });

    fireEvent.click(button("Update"));

    await waitFor(() => expect(countOf("update_sunshine")).toBe(1));
    expect(screen.queryByText("Update available")).toBeTruthy();
  });

  it("says what it is doing while updating", async () => {
    await openPanel({ get_sunshine_version_info: PENDING_UPDATE, update_sunshine: neverAnswers });

    fireEvent.click(button("Update"));

    await waitFor(() => expect(status()).toBe("Status: Updating..."));
  });

  it("re-reads the version when asked to check", async () => {
    await openPanel();

    fireEvent.click(button("Check for updates"));

    await waitFor(() => expect(countOf("get_sunshine_version_info")).toBe(2));
  });

  it("says it is up to date only after the user asked", async () => {
    await openPanel();
    expect(screen.queryByText("Up to date")).toBeNull();

    fireEvent.click(button("Check for updates"));

    // Waits for the check to finish first: during it the panel says nothing,
    // and a findByText would happily settle for a frame in between.
    await waitFor(() => expect(countOf("get_sunshine_version_info")).toBe(2));
    await waitFor(() => expect(screen.getByText("Up to date")).toBeTruthy());
  });

  it("shows that it is looking while it checks", async () => {
    let answer: unknown = IDLE_VERSION;
    await openPanel({ get_sunshine_version_info: () => answer });
    answer = neverAnswers();

    fireEvent.click(button("Check for updates"));

    await waitFor(() => expect(screen.getAllByRole("progressbar").length).toBeGreaterThan(0));
    expect(screen.queryByText("Up to date")).toBeNull();
  });

  it("cannot be asked to update twice at once", async () => {
    await openPanel({ get_sunshine_version_info: PENDING_UPDATE, update_sunshine: neverAnswers });

    fireEvent.click(button("Update"));
    await waitFor(() => expect(button("Update").disabled).toBe(true));
    fireEvent.click(button("Update"));

    expect(countOf("update_sunshine")).toBe(1);
  });

  it("re-checks Sunshine after an update and stops saying it is updating", async () => {
    await openPanel({ get_sunshine_version_info: PENDING_UPDATE, update_sunshine: true });
    const before = countOf("is_sunshine_running");

    fireEvent.click(button("Update"));

    await waitFor(() => expect(countOf("is_sunshine_running")).toBeGreaterThan(before));
    await waitFor(() => expect(status()).toBe("Status: Running"));
  });

  it("shows the new version when the check finds one", async () => {
    let info: unknown = IDLE_VERSION;
    await openPanel({ get_sunshine_version_info: () => info });
    info = PENDING_UPDATE;

    fireEvent.click(button("Check for updates"));

    expect(await screen.findByText("2026.914.233613")).toBeTruthy();
  });
});
