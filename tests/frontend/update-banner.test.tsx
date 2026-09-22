/**
 * Tests for what the panel shows about Sunshine's version.
 *
 * Whether an update exists comes from update_available, never from comparing
 * version strings: current_version is served from a cache and can be stale, so
 * a string comparison offers the installed version as an update to itself.
 */
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { calls, reset } from "./stubs/decky-api";
import { VersionInfo, openPanel } from "./panel";

/** Render the panel with the backend scripted to the given version info. */
const renderPanel = (versionInfo: VersionInfo | null) =>
  openPanel({ get_sunshine_version_info: versionInfo });

beforeEach(() => {
  reset();
});

describe("update banner", () => {
  it("asks the backend for version info when it opens", async () => {
    await renderPanel({ current_version: "2026.516.143833", update_available: false, update_version: null });
    const versionCalls = calls.filter((c) => c.method === "get_sunshine_version_info");
    expect(versionCalls).toHaveLength(1);
    // Nothing is passed: the backend decides for itself whether its cache is fresh
    expect(versionCalls[0].args).toEqual([]);
  });

  it("shows no banner when no update is pending", async () => {
    await renderPanel({ current_version: "2026.914.233613", update_available: false, update_version: null });
    await waitFor(() => expect(screen.getByText("2026.914.233613")).toBeTruthy());
    expect(screen.queryByText("Update available")).toBeNull();
  });

  it("shows the banner with the version the update would install", async () => {
    await renderPanel({ current_version: "2026.516.143833", update_available: true, update_version: "2026.914.233613" });
    await waitFor(() => expect(screen.getByText("Update available")).toBeTruthy());
    expect(screen.getByText("2026.914.233613")).toBeTruthy();
  });

  it("does not call an ordinary update a rebuild", async () => {
    await renderPanel({ current_version: "2026.516.143833", update_available: true, update_version: "2026.914.233613" });
    await waitFor(() => expect(screen.getByText("Update available")).toBeTruthy());
    expect(screen.queryByText(/Rebuild/)).toBeNull();
  });

  it("marks a same-version update as a rebuild", async () => {
    // A real case: Flathub rebuilt 2026.516.143833 under a new commit
    await renderPanel({ current_version: "2026.516.143833", update_available: true, update_version: "2026.516.143833" });
    await waitFor(() => expect(screen.getByText("Update available")).toBeTruthy());
    expect(screen.getByText(/Rebuild/)).toBeTruthy();
  });

  it("still offers the update when the remote has no version string", async () => {
    // No appstream data cached: the update is real, the label is not available
    await renderPanel({ current_version: "2026.516.143833", update_available: true, update_version: null });
    await waitFor(() => expect(screen.getByText("Update available")).toBeTruthy());
    expect(screen.getByText("Unknown version")).toBeTruthy();
    // "Unknown version" must not then be compared against the installed one
    expect(screen.queryByText(/Rebuild/)).toBeNull();
  });

  it("does not call two unknown versions equal", async () => {
    // Sunshine not installed yet, so there is no installed version to compare
    // against. Without the explicit null check both sides are null and the
    // banner would call an unknown version a rebuild of an unknown version.
    await renderPanel({ current_version: null, update_available: true, update_version: null });
    await waitFor(() => expect(screen.getByText("Update available")).toBeTruthy());
    expect(screen.getByText("Unknown version")).toBeTruthy();
    expect(screen.queryByText(/Rebuild/)).toBeNull();
  });

  it("ignores a version string when no update is pending", async () => {
    // The regression guard: an update_version left over from an earlier answer
    // must not by itself produce a banner. This is the shape the old panel got
    // wrong.
    await renderPanel({ current_version: "2026.914.233613", update_available: false, update_version: "2026.516.143833" });
    await waitFor(() => expect(screen.getByText("2026.914.233613")).toBeTruthy());
    expect(screen.queryByText("Update available")).toBeNull();
  });

  it("says so when no version is installed", async () => {
    await renderPanel({ current_version: null, update_available: false, update_version: null });
    await waitFor(() => expect(screen.getByText("Sunshine")).toBeTruthy());
    expect(screen.getByText("Unknown")).toBeTruthy();
  });

  it("survives a backend that answers nothing", async () => {
    await renderPanel(null);

    expect(screen.queryByText("Update available")).toBeNull();
    expect(screen.getByText("Sunshine")).toBeTruthy();
  });

  it("survives a backend call that fails outright", async () => {
    await openPanel({
      get_sunshine_version_info: () => { throw new Error("backend gone"); },
    });

    expect(screen.queryByText("Update available")).toBeNull();
    expect(screen.getByText("Sunshine")).toBeTruthy();
  });
});
