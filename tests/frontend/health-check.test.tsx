/**
 * Tests for the panel's health-check interval.
 *
 * The panel polls Sunshine's state every few seconds and has to stop doing so
 * when it closes. A missing cleanup is invisible in normal use and compounds:
 * every change of pendingRunState or isRestarting adds another timer that
 * never stops, so after a handful of start/stop cycles the panel polls the
 * backend several times a second, forever.
 */
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { calls, reset } from "./stubs/decky-api";
import { openPanel as renderPanel } from "./panel";

const polls = () => calls.filter((c) => c.method === "is_sunshine_running").length;

/** The interval sets state, so the clock has to be advanced inside act. */
const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

beforeEach(() => {
  reset();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("health check", () => {
  it("keeps polling while the panel is open", async () => {
    await renderPanel();
    const before = polls();
    await tick(11000);   // two intervals
    expect(polls()).toBeGreaterThan(before);
  });

  it("stops polling once the panel is closed", async () => {
    const view = await renderPanel();
    await tick(6000);
    view.unmount();

    const afterClose = polls();
    await tick(30000);   // six intervals' worth
    expect(polls()).toBe(afterClose);
  });

  it("holds still while Sunshine is being started or stopped", async () => {
    // Without this the poll lands in the gap a transition makes and reports
    // "Stopped" for a Sunshine that is on its way up - which is exactly what
    // the restart button produces.
    await renderPanel({ stop_sunshine: () => new Promise(() => {}) });
    fireEvent.click(screen.getByRole("button", { name: "Stop Sunshine" }));
    await waitFor(() => expect(screen.getByText("Status: Stopping...")).toBeTruthy());
    const frozen = polls();

    await tick(30000);   // six intervals' worth

    expect(polls()).toBe(frozen);
  });

  it("picks the polling back up afterwards", async () => {
    let stopped = false;
    await renderPanel({
      is_sunshine_running: () => !stopped,
      stop_sunshine: () => { stopped = true; return true; },
    });
    fireEvent.click(screen.getByRole("button", { name: "Stop Sunshine" }));
    await waitFor(() => expect(screen.getByText("Status: Stopped")).toBeTruthy());
    const settled = polls();

    await tick(11000);

    expect(polls()).toBeGreaterThan(settled);
  });

  it("runs one interval at a time, not one per state change", async () => {
    await renderPanel();
    await tick(5500);
    const afterOne = polls();

    // One interval's worth of time must produce one poll. A cleanup that never
    // ran would leave the previous timer behind and double this every cycle.
    await tick(5500);
    expect(polls() - afterOne).toBe(1);
  });
});
