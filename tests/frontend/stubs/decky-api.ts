/**
 * Stand-in for @decky/api, the bridge to the Python backend.
 *
 * `call` is the single point every backend method goes through, so the tests
 * drive the whole panel by scripting it: `callHandler` decides what each
 * method name answers, and `calls` records what was asked for, in order.
 */
export const calls: { method: string; args: unknown[] }[] = [];

export let callHandler: (method: string, args: unknown[]) => unknown = () => null;

export function setCallHandler(handler: (method: string, args: unknown[]) => unknown) {
  callHandler = handler;
}

export function resetCalls() {
  calls.length = 0;
}

/** Clear both the recorded calls and the handler, so no test inherits the
 *  previous one's answers. restoreMocks does not cover this: callHandler is a
 *  plain module variable, not a vi.fn. */
export function reset() {
  calls.length = 0;
  callHandler = () => null;
}

export async function call<Args extends unknown[], T>(method: string, ...args: Args): Promise<T> {
  calls.push({ method, args });
  const result = callHandler(method, args);
  // A handler may throw to exercise the failed-call path, or return a promise
  return (result instanceof Promise ? await result : result) as T;
}

// The plugin's entry point hands definePlugin a factory; calling it straight
// away is what gives the tests the panel element to render.
export function definePlugin<T>(factory: () => T): T {
  return factory();
}
