/**
 * Tests for the Web UI dialog.
 *
 * Steam's built-in browser hard-blocks Sunshine's self-signed certificate (net
 * error -202, no bypass), so the Web UI cannot be opened on the Deck at all.
 * This dialog is the workaround: it shows the address and a QR code for
 * another device on the same network, together with the credentials needed
 * there.
 *
 * Two things it must get right. The hint about read-only editing has to
 * reflect what the *running* Sunshine loaded, not what the config says now -
 * which is why the restart re-reads rather than assuming it worked. And the
 * credentials are revealed only on request: the Deck's screen may be streamed
 * or recorded, so a plaintext password has to be a deliberate act.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { calls, reset, setCallHandler } from "./stubs/decky-api";
import { WebUiModal } from "../../src/components/WebUiModal";
import { withoutErrors } from "./errors";

const READY = { ip: "192.168.1.38", editing_ready: true };
const READ_ONLY = { ip: "192.168.1.38", editing_ready: false };
const CREDENTIALS = { username: "decky_sunshine", password: "s3cr3t-pass" };

beforeEach(() => {
  reset();
});

/** Renders the dialog with the backend scripted, and waits for its first read. */
async function open(answers: Record<string, unknown>, closeModal?: () => void) {
  setCallHandler((method) => (method in answers ? answers[method] : null));
  const view = render(<WebUiModal closeModal={closeModal} />);
  await waitFor(() => expect(calls.some((c) => c.method === "get_web_ui_info")).toBe(true));
  return view;
}

const countOf = (method: string) => calls.filter((c) => c.method === method).length;

describe("web ui modal", () => {
  it("shows the address of this device, not localhost", async () => {
    await open({ get_web_ui_info: READY });

    expect(await screen.findByText("https://192.168.1.38:47990")).toBeTruthy();
  });

  it("offers a QR code so the address does not have to be typed", async () => {
    const view = await open({ get_web_ui_info: READY });

    await screen.findByText("https://192.168.1.38:47990");
    expect(view.container.querySelector("svg")).toBeTruthy();
  });

  it("says it is still looking before the answer arrives", async () => {
    setCallHandler(() => new Promise(() => {}));
    const view = render(<WebUiModal />);

    expect(view.container.querySelector("[role='progressbar']")).toBeTruthy();
  });

  it("shows nothing about a missing address when there is one", async () => {
    await open({ get_web_ui_info: READY });

    await screen.findByText("https://192.168.1.38:47990");
    expect(screen.queryByText(/network address could not be determined/)).toBeNull();
  });

  it("stops saying it is looking once it knows", async () => {
    const view = await open({ get_web_ui_info: READY });

    await screen.findByText("https://192.168.1.38:47990");
    expect(view.container.querySelector("[role='progressbar']")).toBeNull();
  });

  it("survives a backend that could not answer at all", async () => {
    // backend.getWebUiInfo maps a failed call to null, which is not the same
    // as "no address" - and must not reach the JSX as a null dereference.
    await open({ get_web_ui_info: null });

    expect(await screen.findByText(/network address could not be determined/)).toBeTruthy();
  });

  it("explains itself when the Deck has no network address", async () => {
    await open({ get_web_ui_info: { ip: null, editing_ready: false } });

    expect(await screen.findByText(/network address could not be determined/)).toBeTruthy();
    expect(screen.queryByText(/47990$/)).toBeNull();
  });

  it("still offers the credentials without an address", async () => {
    await open({ get_web_ui_info: { ip: null, editing_ready: false } });

    expect(await screen.findByRole("button", { name: "Show credentials" })).toBeTruthy();
  });

  it("warns when the other device can only look", async () => {
    await open({ get_web_ui_info: READ_ONLY });

    expect(await screen.findByText(/can only view/)).toBeTruthy();
  });

  it("says nothing about editing when it already works", async () => {
    await open({ get_web_ui_info: READY });

    await screen.findByText("https://192.168.1.38:47990");
    expect(screen.queryByText(/can only view/)).toBeNull();
  });

  it("restarts Sunshine and re-reads rather than assuming it worked", async () => {
    let info: unknown = READ_ONLY;
    setCallHandler((method) => {
      if (method === "get_web_ui_info") return info;
      if (method === "restart_sunshine") { info = READY; return true; }
      return null;
    });
    render(<WebUiModal />);
    const restart = await screen.findByRole("button", { name: /Restart Sunshine now/ });

    fireEvent.click(restart);

    await waitFor(() => expect(screen.queryByText(/can only view/)).toBeNull());
    expect(countOf("get_web_ui_info")).toBe(2);
  });

  it("keeps the warning when the restart did not help", async () => {
    await open({ get_web_ui_info: READ_ONLY, restart_sunshine: false });
    const restart = await screen.findByRole("button", { name: /Restart Sunshine now/ });

    fireEvent.click(restart);

    await waitFor(() => expect(countOf("get_web_ui_info")).toBe(2));
    expect(screen.queryByText(/can only view/)).toBeTruthy();
  });

  it("cannot be asked to restart twice at once", async () => {
    setCallHandler((method) => {
      if (method === "get_web_ui_info") return READ_ONLY;
      if (method === "restart_sunshine") return new Promise(() => {});
      return null;
    });
    render(<WebUiModal />);
    const restart = await screen.findByRole("button", { name: /Restart Sunshine now/ });

    fireEvent.click(restart);
    await waitFor(() => expect((restart as HTMLButtonElement).disabled).toBe(true));
    fireEvent.click(restart);

    expect(countOf("restart_sunshine")).toBe(1);
  });

  it("keeps the password hidden until it is asked for", async () => {
    await open({ get_web_ui_info: READY, get_credentials: CREDENTIALS });

    await screen.findByText("https://192.168.1.38:47990");
    expect(screen.queryByText(/s3cr3t-pass/)).toBeNull();
    expect(countOf("get_credentials")).toBe(0);
  });

  it("shows them once it is", async () => {
    await open({ get_web_ui_info: READY, get_credentials: CREDENTIALS });

    fireEvent.click(await screen.findByRole("button", { name: "Show credentials" }));

    expect(await screen.findByText("decky_sunshine")).toBeTruthy();
    expect(screen.getByText("s3cr3t-pass")).toBeTruthy();
  });

  it("says so when there are none stored", async () => {
    await open({ get_web_ui_info: READY, get_credentials: null });

    fireEvent.click(await screen.findByRole("button", { name: "Show credentials" }));

    expect(await screen.findByText("No credentials stored")).toBeTruthy();
  });

  it("can be asked to restart again after one that did not work", async () => {
    await open({ get_web_ui_info: READ_ONLY, restart_sunshine: false });
    const restart = await screen.findByRole("button", { name: /Restart Sunshine now/ });

    fireEvent.click(restart);

    await waitFor(() => expect((restart as HTMLButtonElement).disabled).toBe(false));
  });

  it("shows that it is working while it reads the credentials", async () => {
    setCallHandler((method) => (method === "get_web_ui_info" ? READY : new Promise(() => {})));
    const view = render(<WebUiModal />);
    fireEvent.click(await screen.findByRole("button", { name: "Show credentials" }));

    await waitFor(() =>
      expect(view.container.querySelector("[role='progressbar']")).toBeTruthy());
  });

  it("stops showing that it is working once the credentials are there", async () => {
    const view = await open({ get_web_ui_info: READY, get_credentials: CREDENTIALS });

    fireEvent.click(await screen.findByRole("button", { name: "Show credentials" }));

    await screen.findByText("s3cr3t-pass");
    expect(view.container.querySelector("[role='progressbar']")).toBeNull();
  });

  it("can be asked again after a read that found nothing", async () => {
    await open({ get_web_ui_info: READY, get_credentials: null });

    fireEvent.click(await screen.findByRole("button", { name: "Show credentials" }));

    await screen.findByText("No credentials stored");
    expect((screen.getByRole("button", { name: "Show credentials" }) as HTMLButtonElement)
      .disabled).toBe(false);
  });

  it("says nothing about missing credentials before they were asked for", async () => {
    await open({ get_web_ui_info: READY, get_credentials: null });

    await screen.findByText("https://192.168.1.38:47990");
    expect(screen.queryByText("No credentials stored")).toBeNull();
  });

  it("says nothing about missing credentials when they were found", async () => {
    await open({ get_web_ui_info: READY, get_credentials: CREDENTIALS });

    fireEvent.click(await screen.findByRole("button", { name: "Show credentials" }));

    await screen.findByText("s3cr3t-pass");
    expect(screen.queryByText("No credentials stored")).toBeNull();
  });

  it("can be closed even when nothing is listening", async () => {
    await open({ get_web_ui_info: READY });
    const close = await screen.findByRole("button", { name: "Close" });

    withoutErrors(() => fireEvent.click(close));
  });

  it("can be closed", async () => {
    const closeModal = vi.fn();
    await open({ get_web_ui_info: READY }, closeModal);

    fireEvent.click(await screen.findByRole("button", { name: "Close" }));

    expect(closeModal).toHaveBeenCalled();
  });
});
