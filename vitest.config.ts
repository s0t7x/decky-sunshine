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
      //
      // branches is not 100 because of the tool, not the tests. From Vitest 4
      // on, coverage-v8 remaps through ast-v8-to-istanbul, and that remapper
      // loses the implicit else of an if when a ternary with an await in both
      // arms sits in front of it. index.tsx:88-89 is the only place in src
      // with that shape, and both of its arms are exercised (panel-controls
      // "start fails" / "stop fails" and the two counting tests above them).
      // Reduced to: ternary + await + if-without-else reports 5/6 branches,
      // the same code without the ternary reports 4/4. Vitest 3 counted it as
      // covered. autoUpdate raises this back to 100 by itself once the
      // remapper is fixed, so this number needs no watching.
      thresholds: {
        autoUpdate: true,
        statements: 100,
        branches: 99.28,
        functions: 100,
        lines: 100,
      },
    },
  },
});