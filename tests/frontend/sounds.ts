/**
 * What the panel played, by URL.
 *
 * jsdom has no media stack, so every test that touches a dialog has to replace
 * HTMLMediaElement.play anyway. Recording the element's src while doing so
 * costs nothing and turns "a sound was played" into "this sound was played" -
 * the URL names the specific Steam UI sound the rest of the client uses for
 * the same gesture, and a wrong one is as audible as a missing one.
 */
import { vi } from "vitest";

export function playedSounds(): string[] {
  const played: string[] = [];
  vi.spyOn(window.HTMLMediaElement.prototype, "play").mockImplementation(
    function (this: HTMLMediaElement) {
      played.push(this.src);
      return Promise.resolve();
    });
  return played;
}
