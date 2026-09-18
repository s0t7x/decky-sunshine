/**
 * React 19 reports a throwing event handler through reportError rather than by
 * letting it escape into fireEvent, so a test that presses a button cannot see
 * the throw at all - it passes, and vitest prints "This might cause false
 * positive tests" next to it. The window is where the report lands.
 */
import { expect, vi } from "vitest";

/** Run `act`, and fail if anything it touched reported an error. */
export function withoutErrors(run: () => void) {
  const reported = vi.fn();
  window.addEventListener("error", reported);
  try {
    run();
  } finally {
    window.removeEventListener("error", reported);
  }
  expect(reported).not.toHaveBeenCalled();
}
