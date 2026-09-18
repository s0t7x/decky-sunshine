import { defineConfig } from "vitest/config";
import { resolve } from "path";

export default defineConfig({
  resolve: {
    alias: {
      // The real packages expect the Steam client around them, so the panel is
      // rendered against stand-ins instead (see tests/frontend/stubs).
      "@decky/ui": resolve(__dirname, "tests/frontend/stubs/decky-ui.tsx"),
      "@decky/api": resolve(__dirname, "tests/frontend/stubs/decky-api.ts"),
    },
  },
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    include: ["tests/frontend/**/*.test.{ts,tsx}"],
    globals: true,
    restoreMocks: true,
    coverage: {
      provider: "v8",
      // The stubs and the tests themselves are not the subject; only what ships
      // in the bundle is. types.tsx is type-only and compiles to nothing.
      include: ["src/**"],
      exclude: ["src/util/types.tsx", "src/**/*.d.ts"],
      reporter: ["text", "html"],
      reportsDirectory: ".coverage-data/frontend",
      // The ratchet, the same idea as fail_under in pyproject.toml; see
      // tests/README.md. autoUpdate only ever raises, so at 100 it does
      // nothing - it stays for the day a threshold is lowered for a new file.
      thresholds: {
        autoUpdate: true,
        statements: 100,
        branches: 100,
        functions: 100,
        lines: 100,
      },
    },
  },
});