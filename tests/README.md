# Tests

Two suites, because the plugin is Python on the backend and React on the
frontend, and neither half can be tested through the other.

**Reviewing this suite, or a change to it: `tests/REVIEW.md`.** It holds the
criteria five review passes produced - the findings that make a test green
while the behaviour it names is gone, what a comment has to do, and what the
CI configuration is checked against.

Two inputs are verbatim from a Steam Deck rather than invented
(`DECK_MOUNTS`, `DECK_OS_RELEASE` in `tests/test_setuid_env.py`). Everything
else about a mount table can be made up, but "does the filesystem hosting the
setuid bwrap copy allow setuid" is a question about that machine: there `/var`
is its own ext4 mount without `nosuid`, and `/tmp` is `nosuid` - which is why
the copy is where it is.

```sh
pytest                    # backend
pnpm run test             # frontend
pnpm run typecheck        # types, including the test files
```

`pytest` needs the packages in `requirements-test.txt`. Current distributions
and SteamOS mark their Python as externally managed (PEP 668), so install them
into a virtualenv - `tools/coverage.sh` creates one at `.venv-tests/` on first
use and everything here works from there.

## How the backend tests are put together

`tests/conftest.py` holds what every backend test file needs:

- **`decky_stub` / `settings_stub`** - the modules the Decky loader provides at
  runtime and nothing provides in a test run. They go in through
  `monkeypatch.setitem(sys.modules, ...)`, so pytest takes them out again; a
  stub left behind is invisible in the file that set it and breaks the next
  file that wanted the real thing.
- **`load_main`** - imports `main.py` against those stubs, fresh per test.
  `main.py` binds `decky` and `SettingsManager` at import time, so a cached
  module would keep an earlier test's stubs alive inside it.
- **`bare_controller`** - a `SunshineController` with `__init__` skipped, plus
  whatever attributes the test needs. The constructor reads the environment,
  looks for sockets and probes the filesystem; almost no test wants that, and
  setting three attributes by hand keeps the preconditions visible in the test.
- **`logger`** - records what it was told, per level. A good part of what this
  plugin does for the user *is* the log, and warning and debug are kept apart
  because several paths warn once and then demote themselves to debug.

## What is covered

The frontend suite is one file per surface: the panel itself
(`panel-controls`, `update-banner`, `health-check`), the three dialogs
(`pairing-modal`, `credentials-modal`, `web-ui-modal`), the small pieces they
are built from (`small-components`) and the bridge to the backend (`backend`).
The Steam UI is not available outside the client, so everything renders against
the stand-ins in `tests/frontend/stubs`. Those render plain elements and keep
every label as text. Only the props the tests assert on are declared, so
nothing there can tell whether the panel still passes Steam's presentation
props; anything that has to be checked is recorded instead (`textFieldProps`,
`focusableProps`). That is the only way to check something like
PasswordInput's masking: jsdom drops CSS properties it does not know.

The backend suite is one file per concern, and each file's docstring says which
failure it exists for. Roughly: the plugin's own lifecycle
(`test_plugin_load`, `test_run_intent`, `test_crash_watch`), starting Sunshine
and keeping it up (`test_startup_env`, `test_display_audio`, `test_install_update`,
`test_setuid_env`, `test_bwrap_copy`), the streaming fixes
(`test_composition_force`), the Web UI and its CSRF flow (`test_csrf_flow`,
`test_csrf_origin`), and the API surface the panel talks to (`test_panel_api`,
`test_http`, `test_credentials`, `test_version_info`, `test_uninstall`).

## Coverage

```sh
tools/coverage.sh                # measure, report, raise the floor
tools/coverage.sh --no-raise     # measure and report only
pnpm run coverage                # frontend
```

Branch coverage, not line: a line whose condition only ever goes one way reads
as covered while half of it is unverified, and that half is where the bugs were
- the display gate that could not tell "no tool" from "no display yet", and the
restart path that slowed the next check down after a restart that worked.

Both halves carry a **ratchet** - `fail_under` in `pyproject.toml`, `thresholds`
in `vitest.config.ts`. A better run raises it, a worse one fails. That is what
catches a deleted test: removing one changes no production line, so a check
that only looks at the diff has nothing to look at.

Both are currently at the top of their range (99.79% combined for Python, 100%
for the frontend on statements, functions and lines), so there is no headroom
left: a new production line without a test fails the gate rather than merely
eating into a margin. The frontend branch threshold is the one exception, a
fraction under 100% that moves whenever branches are added, and it is not a
gap in the tests - from Vitest 4 on the v8 remapper miscounts one branch in
`index.tsx`; `vitest.config.ts` has the reduced case, and `autoUpdate` raises
the number back to 100 on its own once that is fixed.
That is the ratchet working as asked for, and the `coverage-override` label
below is the way past it when a change is worth merging anyway.

The three uncovered branch edges in Python are loop conditions that cannot go
the other way - the body breaks or returns first.

CI adds `diff-cover` on top, which asks the other question - are the lines this
PR *added* covered - because a large well-tested change can otherwise offset an
untested one in the total.

A maintainer can put the `coverage-override` label on a pull request to skip
both gates. Labels need write access, so the author of a PR cannot wave their
own change through.

## Mutation testing

Coverage says which lines ran. Mutation testing says whether anything would
have noticed if they were wrong: it breaks the code in one small way at a time
and reruns the tests. A mutant that survives is a line no assertion pins down.

```sh
mutmut run                # backend
mutmut results            # what survived
mutmut show <mutant>      # the diff for one of them
pnpm run mutation         # frontend (Stryker)
```

**`py_modules/sunshine.py` is mutated only because of how the tests import
it.** mutmut 3.8 names each mutant after the *file path* - here
`py_modules.sunshine` - and matches it against the `__module__` the function
reports at run time. The Decky loader puts `py_modules` on `sys.path` and
`main.py` does `import sunshine`, so a test suite that imports it the same way
reports plain `sunshine`, the two keys never meet, and every mutant in the file
comes back "no tests". (mutmut has a check for exactly this,
`_check_test_to_mutant_associations`, but it only fires when *no* key matches -
`main.py`'s do, so it would stay quiet.)

`tests/conftest.py` therefore loads the file as `py_modules.sunshine` - a
namespace package, no `__init__.py` - and registers the same module object
under `sunshine` in `sys.modules`, which is what `main.py` and the tests then
get. Nothing in the shipped plugin changes. A test that loaded the file some
other way - by path through `importlib.util`, or after removing the
`sys.modules` entry - would get a second copy of the module, and patch one
while the code under test ran the other.

The last run: **2401 mutants, 64 survived**, the rest killed - 6 or 7 of them
by timeout, depending on how busy the machine is. About three minutes.

On `main.py` the current state is 550 mutants, 539 killed, 11 survived (98%).
Every one of the eleven has been looked at, and all eleven are equivalent -
the mutated code cannot behave differently from the original:

* `last_attempt = 0.0` &rarr; `None` / `1.0` (2). Never read before it is
  assigned: the only read is guarded by `attempts and ...`, and `attempts` is
  still 0 until the line above the assignment.
* `record_intent = False` &rarr; `None` (2), `getSetting("csrfRestartPending",
  False)` &rarr; `None` / no default (2), `getSetting("lastAuthHeader", "")`
  &rarr; `None` / no default (2). Each value is only ever tested for
  truthiness, and both spellings are falsy.
* the second `else 'unknown'` in the running-state line (3).
  `isSunshineRunning_async` is typed `-> bool` and has no path that answers
  `None`, so that fallback never renders. The first one does - it is what the
  remembered side reads before the first poll - and is pinned.

There is no per-mutant way to mark those. mutmut's `# pragma: no mutate` is
per *line*, and each of these lines except the `last_attempt` one also carries
mutants that are killed and worth killing (a wrong setting key, a dropped
`not`), so silencing the line would silence those too. They are listed here
instead.

**Log messages count as behaviour here.** The log is what a user pastes into a
bug report and the only account of everything the panel cannot show, so a test
pins the whole line (`"Sunshine stopped" in log.infos`, which compares list
elements) rather than a fragment of it. A fragment leaves the rest of the
wording untested, and mutmut says so: it produces one mutant per string that
pads it with `XX...XX`, and only an assertion on the entire line kills that
one. Changing a message is therefore expected to break a test - that is the
test doing its job, not brittleness.

### The 64 that survive in `sunshine.py` and `main.py`

Eleven are in `main.py` and listed above. The rest fall into a handful of
kinds, all of them equivalent unless noted:

* **Case of a name that is matched case-insensitively** (~15): HTTP header
  names (`"Accept"` &rarr; `"ACCEPT"`), which urllib normalises, and codec
  names (`'utf-8'` &rarr; `'UTF-8'`), which Python's codec lookup does.
* **`XX…XX` inside a character set** (~4): `rstrip("/")` &rarr;
  `rstrip("XX/XX")` adds `X` to the set. Only a path or value ending in `X`
  would tell them apart.
* **A fallback string that the surrounding code never renders** (~13): the
  `'second'`/`'seconds'` halves that the fixed `wait_time` at each site never
  reaches, and `(result or "")` &rarr; `"XXXX"`, where neither spelling
  matches anything.
* **Falsy replaced by falsy** (~8): `None` for `False` or `""` in values that
  are only ever tested for truthiness.
* **Loop guards that cannot differ** (~5): `while retry_count > 0` &rarr;
  `>= 0`, where the body always returns or breaks at zero, and `tick += 1`
  &rarr; `-= 1` under a `% 6 == 0` test.
* **`split("-", 1)` losing its maxsplit** (2): DRM connector directories are
  `card0-eDP-1`, and every maxsplit gives a segment with the same prefix.
* **A handful of others** where a test would have to be built around a value
  nobody would write (a mount point ending in `X`, a `getattr` default spelled
  two ways).

Nothing in that list is a missing assertion. What *was* missing is now
covered: the exact command line of every `flatpak`, `su` and `cp` call and the
`context=` each carries into the log; the environment and session Sunshine is
spawned with; the glob patterns the sysfs and `/run/user` searches use; the
HTTP headers; the socket kind, address and timeout of every probe; and every
log line.

Stryker's number for the frontend is 80%, out of 625 mutants: 496 killed,
124 survived, 5 runtime errors. `src/util` is at 100%. Counted out:

* **103** change a value in an inline style object - a colour, a width, a gap,
  a border radius - or a `bottomSeparator`. Cosmetic; no test should care.
* **11** are equivalent under the test stubs: `focusable={false}` on a `Field`
  (7 - the stub discards the prop) and a `useEffect` dependency array `[]`
  given one constant entry (4 - React compares by value, and a literal array
  is stable either way).
* **10** are equivalent for a reason that needs the surrounding code to see,
  so they are written down here rather than re-derived every time:
  - `setSunshineUpdateVersion(null)` and both `setGetCredentialsReturnedValue(
    null)` can be deleted. Each is either overwritten before anything renders
    again, or its value is only read behind a flag the line above already
    cleared. The one path that would tell them apart needs `backend.getCredentials`
    to reject, and `Backend.call` never lets it.
  - `isRefreshingVersionInfo` starting `true` instead of `false`: the mount
    effect sets it `true` before the first paint is visible to anything.
  - `info?.editing_ready` losing its `?.` in `WebUiModal`: that branch only
    renders when `url` is set, and `url` is derived from `info`.
  - `e?.stopPropagation?.()` losing the inner `?.`: `e?.` already covers the
    call with no event, and a real event always has the method.

**No surviving mutant changes a message the user reads.** Every visible string
is pinned by a test, and so are the `console` lines: the Steam client's console
is the frontend's only diagnostic channel, so `LOG_TAG` and each message are
asserted whole, the same rule as the backend log above.

Do not chase this number between runs - Stryker reclassifies a handful of
mutants between "survived" and "runtime error" from one run to the next, which
moves the percentage by a point or two without anything having changed.

It runs in CI on pushes to `main` that touch code, and reports rather than
gates - it takes minutes rather than seconds, and its number moves for reasons
that are nobody's fault.

Expect survivors that are not worth fixing, particularly in the frontend: a
changed pixel value in an inline style, or a Steam prop the stubs discard,
produces a mutant no test should care about. Judge the list, don't chase the
number - and when a survivor turns out to be equivalent rather than untested,
write down why, next to the eleven above.
