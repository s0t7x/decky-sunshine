/**
 * Tests for the pairing dialog.
 *
 * Pairing is the one thing in this panel the user cannot retry blind: the PIN
 * shown on the client is valid for one attempt, and Sunshine's own /api/pin
 * cannot be trusted to say whether it worked (LizardByte/Sunshine#3944). So
 * the dialog has to be strict about what it sends and honest about what came
 * back - a silent failure here reads as "the Deck is broken" rather than
 * "type it again".
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PairingModal } from "../../src/components/PairingModal";
import { resetStubs, textFieldProps } from "./stubs/decky-ui";
import { playedSounds } from "./sounds";

/** jsdom has no media stack; the dialog plays a sound on submit. */
let played: string[];

beforeEach(() => {
  resetStubs();
  played = playedSounds();
});

const pairButton = () => screen.getByRole("button", { name: "Pair" }) as HTMLButtonElement;
const field = (label: string) => screen.getByLabelText(label);

function fill(pin: string, clientName = "Living Room TV") {
  fireEvent.change(field("Client name"), { target: { value: clientName } });
  fireEvent.change(field("PIN"), { target: { value: pin } });
}

describe("pairing modal", () => {
  it("gives the submit the click feedback the rest of the client gives", async () => {
    render(<PairingModal onPair={async () => true} />);

    fill("1234");
    fireEvent.click(pairButton());

    await waitFor(() => expect(played).toEqual(["https://steamloopback.host/sounds/deck_ui_side_menu_fly_in.wav"]));
  });

  it("sends the PIN and the client name the user typed", async () => {
    const onPair = vi.fn().mockResolvedValue(true);
    render(<PairingModal onPair={onPair} />);

    fill("1234");
    fireEvent.click(pairButton());

    await waitFor(() => expect(onPair).toHaveBeenCalledWith("1234", "Living Room TV"));
  });

  it("closes itself once the client is paired", async () => {
    const closeModal = vi.fn();
    render(<PairingModal closeModal={closeModal} onPair={async () => true} />);

    fill("1234");
    fireEvent.click(pairButton());

    await waitFor(() => expect(closeModal).toHaveBeenCalled());
  });

  it("stays open and says so when the pairing did not work", async () => {
    const closeModal = vi.fn();
    render(<PairingModal closeModal={closeModal} onPair={async () => false} />);

    fill("9999");
    fireEvent.click(pairButton());

    expect(await screen.findByText(/Pairing failed/)).toBeTruthy();
    expect(closeModal).not.toHaveBeenCalled();
  });

  it("shows that it is waiting while the backend is working", async () => {
    let release: (value: boolean) => void = () => {};
    render(<PairingModal onPair={() => new Promise<boolean>((r) => { release = r; })} />);

    fill("1234");
    fireEvent.click(pairButton());

    expect(await screen.findByText("Waiting for response...")).toBeTruthy();
    release(false);
    await waitFor(() => expect(screen.queryByText("Waiting for response...")).toBeNull());
  });

  it("cannot be submitted twice while the first attempt is in flight", async () => {
    const onPair = vi.fn(() => new Promise<boolean>(() => {}));
    render(<PairingModal onPair={onPair} />);

    fill("1234");
    fireEvent.click(pairButton());
    await waitFor(() => expect(pairButton().disabled).toBe(true));

    fireEvent.click(pairButton());
    expect(onPair).toHaveBeenCalledTimes(1);
  });

  it("will not submit without a PIN of four digits", () => {
    render(<PairingModal onPair={async () => true} />);

    fill("123");

    expect(pairButton().disabled).toBe(true);
  });

  it("will not submit without a client name", () => {
    render(<PairingModal onPair={async () => true} />);

    fill("1234", "");

    expect(pairButton().disabled).toBe(true);
  });

  it("refuses a fifth digit rather than sending a truncated PIN", () => {
    render(<PairingModal onPair={async () => true} />);
    fill("1234");

    fireEvent.change(field("PIN"), { target: { value: "12345" } });

    expect((field("PIN") as HTMLInputElement).value).toBe("1234");
  });

  it("refuses anything that is not a digit", () => {
    render(<PairingModal onPair={async () => true} />);

    fireEvent.change(field("PIN"), { target: { value: "12a4" } });

    expect((field("PIN") as HTMLInputElement).value).toBe("");
  });

  it("lets the user correct the PIN by deleting it", () => {
    render(<PairingModal onPair={async () => true} />);
    fill("1234");

    fireEvent.change(field("PIN"), { target: { value: "" } });

    expect((field("PIN") as HTMLInputElement).value).toBe("");
    expect(pairButton().disabled).toBe(true);
  });

  it("accepts a client name of one character", () => {
    render(<PairingModal onPair={async () => true} />);

    fill("1234", "x");

    expect(pairButton().disabled).toBe(false);
  });

  it("offers to clear a field only once it holds something", () => {
    render(<PairingModal onPair={async () => true} />);

    expect(textFieldProps.every((p) => p.bShowClearAction === false)).toBe(true);

    fill("1234");

    const filled = ["Living Room TV", "1234"].map((value) =>
      [...textFieldProps].reverse().find((p) => p.value === value)!);
    expect(filled.every((p) => p.bShowClearAction === true)).toBe(true);
  });

  it("keeps the PIN field numeric for the on-screen keyboard", () => {
    render(<PairingModal onPair={async () => true} />);

    const pin = textFieldProps.find((p) => String(p.description).startsWith("The PIN"));
    expect(pin!.mustBeNumeric).toBe(true);
    expect(textFieldProps.filter((p) => p.mustBeNumeric === true)).toHaveLength(1);
  });

  it("tells the user how many digits the PIN has", () => {
    // The only place that says it - the field itself accepts any length
    render(<PairingModal onPair={async () => true} />);

    expect(textFieldProps.map((p) => p.description)).toContain(
      "The PIN as shown on the client / device you want to pair (4 digits)");
  });

  it("clears the failure message when the PIN is retyped", async () => {
    render(<PairingModal onPair={async () => false} />);
    fill("9999");
    fireEvent.click(pairButton());
    await screen.findByText(/Pairing failed/);

    fireEvent.change(field("PIN"), { target: { value: "1111" } });

    expect(screen.queryByText(/Pairing failed/)).toBeNull();
  });
});
