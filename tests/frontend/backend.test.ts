/**
 * Tests for the backend bridge's error contract.
 *
 * Every panel action goes through Backend.call, and the panel is written
 * against the pre-@decky/api behaviour: a failed call comes back as null or
 * false, it never throws. If that ever changed, a backend that is merely
 * unreachable would take the whole panel down with an unhandled rejection
 * instead of showing "Stopped".
 *
 * The bridge is also the only thing that writes to the Steam client's console,
 * which is where "it just does nothing" has to become a diagnosis - so those
 * lines are checked, tag included (tests/README.md says why).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { calls, reset, setCallHandler } from "./stubs/decky-api";
import backend from "../../src/util/backend";

beforeEach(() => {
  reset();
  // Half of this file drives the failure path on purpose, and the bridge logs
  // every one of those. Without this the run buries its own result in stack
  // traces; the tests that are about the logging set their own spy.
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(console, "log").mockImplementation(() => {});
});

/** Every method: what it must answer when the call fails, which backend method
 *  it reaches, and the arguments that have to arrive there. */
const methods: {
  name: string; run: () => Promise<unknown>; onFailure: unknown;
  backendMethod: string; args: unknown[];
}[] = [
  { name: "pair", run: () => backend.pair("1234", "client"), onFailure: false, backendMethod: "pair", args: ["1234", "client"] },
  { name: "isSunshineRunning", run: () => backend.isSunshineRunning(), onFailure: false, backendMethod: "is_sunshine_running", args: [] },
  { name: "areCredentialsValid", run: () => backend.areCredentialsValid(), onFailure: null, backendMethod: "are_credentials_valid", args: [] },
  { name: "setCredentials", run: () => backend.setCredentials("u", "p"), onFailure: null, backendMethod: "set_credentials", args: ["u", "p"] },
  { name: "getCredentials", run: () => backend.getCredentials(), onFailure: null, backendMethod: "get_credentials", args: [] },
  { name: "startSunshine", run: () => backend.startSunshine(), onFailure: false, backendMethod: "start_sunshine", args: [] },
  { name: "stopSunshine", run: () => backend.stopSunshine(), onFailure: false, backendMethod: "stop_sunshine", args: [] },
  { name: "restartSunshine", run: () => backend.restartSunshine(), onFailure: false, backendMethod: "restart_sunshine", args: [] },
  { name: "getSunshineVersionInfo", run: () => backend.getSunshineVersionInfo(), onFailure: null, backendMethod: "get_sunshine_version_info", args: [] },
  { name: "updateSunshine", run: () => backend.updateSunshine(), onFailure: false, backendMethod: "update_sunshine", args: [] },
  { name: "getWebUiInfo", run: () => backend.getWebUiInfo(), onFailure: null, backendMethod: "get_web_ui_info", args: [] },
  { name: "getForceComposition", run: () => backend.getForceComposition(), onFailure: false, backendMethod: "get_force_composition", args: [] },
  { name: "setForceComposition", run: () => backend.setForceComposition(true), onFailure: false, backendMethod: "set_force_composition", args: [true] },
];

describe("backend error contract", () => {
  it.each(methods)("$name maps a thrown call to $onFailure", async ({ run, onFailure }) => {
    setCallHandler(() => { throw new Error("backend unreachable"); });
    await expect(run()).resolves.toBe(onFailure);
  });

  it.each(methods)("$name calls $backendMethod, and nothing else", async ({ run, backendMethod }) => {
    setCallHandler(() => null);
    await run();
    expect(calls.map((c) => c.method)).toEqual([backendMethod]);
  });

  it.each(methods)("$name passes its arguments through unchanged", async ({ run, args }) => {
    setCallHandler(() => null);
    await run();
    expect(calls[0].args).toEqual(args);
  });
});

// A method that answers false on failure is one that promises a boolean.
const booleanMethods = methods.filter((m) => m.onFailure === false);

describe("boolean methods", () => {
  // The backend answers over JSON-RPC, so anything can come back. Methods
  // declared to return a boolean must not leak a truthy string to the panel.
  it.each(booleanMethods)("$name returns true for true", async ({ run }) => {
    setCallHandler(() => true);
    await expect(run()).resolves.toBe(true);
  });

  it.each(booleanMethods)("$name returns false for a non-true answer", async ({ run }) => {
    setCallHandler(() => "yes");
    await expect(run()).resolves.toBe(false);
  });
});

describe("what the bridge writes to the console", () => {
  it("names the method that failed, the error, and the plugin it came from", async () => {
    // The tag is what makes the line findable at all: the Steam client's
    // console carries every plugin's output and the client's own.
    const error = new Error("backend unreachable");
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    setCallHandler(() => { throw error; });

    await backend.pair("1234", "TV");

    expect(logged).toHaveBeenCalledWith("[SUN]", "Backend method pair failed", error);
  });

  it.each([
    { name: "startSunshine", run: () => backend.startSunshine(), line: "should start" },
    { name: "stopSunshine", run: () => backend.stopSunshine(), line: "should stop" },
    { name: "restartSunshine", run: () => backend.restartSunshine(), line: "should restart" },
  ])("$name says so before the call goes out", async ({ run, line }) => {
    // These three are the ones a user triggers and then watches do nothing,
    // so the console has to show that the press arrived at all.
    const logged = vi.spyOn(console, "log").mockImplementation(() => {});
    setCallHandler(() => true);

    await run();

    expect(logged).toHaveBeenCalledWith("[SUN]", line);
  });
});

describe("pass-through methods", () => {
  it.each([
    { name: "getSunshineVersionInfo", run: () => backend.getSunshineVersionInfo(),
      answer: { current_version: "1", update_available: true, update_version: "2" } },
    { name: "getCredentials", run: () => backend.getCredentials(),
      answer: { username: "u", password: "p" } },
  ])("$name hands the answer through unchanged", async ({ run, answer }) => {
    setCallHandler(() => answer);
    await expect(run()).resolves.toEqual(answer);
  });
});
