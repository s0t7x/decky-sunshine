"""Shared fixtures for the backend tests.

Three things every backend test file needs:

  * the module stubs the plugin's imports need ("decky", "settings"), which the
    Decky loader provides at runtime and nothing provides in a test run, and
  * a logger that records what it was told instead of printing it, because a
    good part of what this plugin does for the user IS the log, and
  * the controller main.py talks to, faked down to what it actually calls.

The stubs are fixtures rather than module-level assignments so that pytest
tears them down again: a stub left in sys.modules is invisible in the file that set
it and breaks the next file that wanted the real thing.
"""
import importlib
import logging
import os
import sys
import types

import pytest

# The loader puts the plugin directory and py_modules on the path, and main.py
# does `import sunshine`. The tests load that same file as py_modules.sunshine
# instead - a namespace package, no __init__.py needed - and register it under
# the plain name as well, so main.py and every test share one module object.
#
# The dotted name is for mutmut. It names each mutant after the file path
# (py_modules.sunshine) and matches it against the __module__ the function
# reports at run time; under the plain name the two never meet, and every
# mutant in sunshine.py comes back "no tests".
#
# The root is derived from this file's own location rather than declared as
# pythonpath in pyproject.toml, and that is not a style choice either: mutmut
# runs the suite against a copy of the tree under mutants/, and a path spelled
# out in the pytest config is resolved against the original checkout - the
# tests would then import the unmutated files.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
sys.modules["sunshine"] = importlib.import_module("py_modules.sunshine")


class RecordingLogger:
    """A logger that keeps what it was told, per level.

    Separate lists per level on purpose: several paths warn the first time
    something happens and demote themselves to debug afterwards, and a single
    combined list cannot tell those two apart.

    Assertions name a whole line (`message in logger.infos`, which compares
    list elements) rather than a fragment of one: a fragment leaves the rest
    of the wording untested, and the wording is what the line is for.
    """

    def __init__(self):
        self.debugs = []
        self.infos = []
        self.warnings = []
        self.errors = []
        self.exceptions = []
        self.raised = []

    def debug(self, msg, *args, **kwargs):
        self.debugs.append(str(msg) % args if args else str(msg))

    def info(self, msg, *args, **kwargs):
        self.infos.append(str(msg) % args if args else str(msg))

    def warning(self, msg, *args, **kwargs):
        self.warnings.append(str(msg) % args if args else str(msg))

    def error(self, msg, *args, **kwargs):
        self.errors.append(str(msg) % args if args else str(msg))

    def exception(self, msg, *args, **kwargs):
        text = str(msg) % args if args else str(msg)
        self.exceptions.append(text)
        self.errors.append(text)
        # (message, exception) pairs. "It logged something" and "it logged the
        # traceback" are different promises: without exc_info the line names
        # the symptom and loses the stack that says where it came from, and
        # these paths are all ones nobody watches happen.
        self.raised.append((text, kwargs.get("exc_info")))

    def all(self):
        """Everything, in no particular order - for "was this mentioned at all"."""
        return self.debugs + self.infos + self.warnings + self.errors

    def raised_with_traceback(self, message):
        """Was exactly `message` logged, and did it carry the exception?

        Both halves matter and neither implies the other: the message says
        what the plugin was doing, the traceback says where it broke, and a
        line with the first and not the second is the one that gets a bug
        report closed as "cannot reproduce".
        """
        return any(text == message and error is not None
                   for text, error in self.raised)


@pytest.fixture
def logger():
    """A fresh recorder per test, so one test's lines cannot satisfy the next
    test's assertions."""
    return RecordingLogger()


class FakeSettingsManager:
    """Stands in for Decky's SettingsManager: a dict with its interface.

    `writes` keeps every setSetting in order, because the final state does not
    always show whether a setting was written: several paths write the value
    that was already there (a failed stop re-records "start"), and a test that
    only reads the dict back cannot tell that apart from writing nothing.
    """

    def __init__(self, *args, name=None, settings_directory=None, **kwargs):
        self.settings = {}
        self.writes = []
        # Kept because _main is the one place that chooses them, and the file
        # they name is the one _migration moves.
        self.name = name
        self.settings_directory = settings_directory

    def read(self):
        pass

    def getSetting(self, key, default=None):
        return self.settings.get(key, default)

    def setSetting(self, key, value):
        self.writes.append((key, value))
        self.settings[key] = value

    def writes_of(self, key):
        """Every value written to `key`, in order."""
        return [value for written, value in self.writes if written == key]


@pytest.fixture
def decky_stub(monkeypatch):
    """The `decky` module main.py imports at load time."""
    decky = types.ModuleType("decky")
    decky.logger = RecordingLogger()
    decky.migrate_settings = lambda *a, **k: None
    decky.DECKY_PLUGIN_VERSION = "test"
    decky.DECKY_HOME = "/tmp"
    decky.DECKY_PLUGIN_RUNTIME_DIR = "/tmp"
    monkeypatch.setitem(sys.modules, "decky", decky)
    return decky


@pytest.fixture
def settings_stub(monkeypatch):
    """The `settings` module, whose SettingsManager main.py instantiates."""
    module = types.ModuleType("settings")
    module.SettingsManager = FakeSettingsManager
    monkeypatch.setitem(sys.modules, "settings", module)
    return module


@pytest.fixture
def load_main(monkeypatch, decky_stub, settings_stub):
    """Imports main.py against the stubs and hands it back.

    main.py is re-imported per test rather than cached, because it binds
    `decky` and `SettingsManager` at import time - a module left over from an
    earlier test would keep that test's stubs alive inside it.

    Pass a module (or anything with a SunshineController attribute) to replace
    `sunshine` for the duration; leave it out to run against the real one.
    """

    def _load(sunshine_module=None):
        if sunshine_module is not None:
            monkeypatch.setitem(sys.modules, "sunshine", sunshine_module)
        sys.modules.pop("main", None)
        return importlib.import_module("main")

    yield _load
    # Not monkeypatch's job: main was imported, not replaced, so nothing was
    # recorded to roll back. Leaving it behind would hand the next test a module
    # still holding this test's stubs.
    sys.modules.pop("main", None)


@pytest.fixture
def bare_controller(logger):
    """A SunshineController with __init__ skipped, plus whatever a test needs.

    The constructor reads the environment, looks for sockets and probes the
    filesystem; almost no test wants any of that. Skipping it and setting the
    two or three attributes under test keeps each test's preconditions visible
    in the test itself.

    sunshine is imported inside the factory, not at module level: a test that
    replaces it with a stand-in must not be pre-empted by this file having
    already imported the real one.
    """

    def _make(**attributes):
        from sunshine import SunshineController

        controller = object.__new__(SunshineController)
        controller.logger = logger
        for name, value in attributes.items():
            setattr(controller, name, value)
        return controller

    return _make


@pytest.fixture(autouse=True)
def quiet_logging():
    """Keep the real logging machinery from printing during a run.

    Autouse: every assertion about a log line reads RecordingLogger, so nothing
    here needs the root logger. It is process-wide, so a test that wants caplog
    would have to opt out.
    """
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


class FakeController:
    """Sunshine as main.py sees it, reduced to what every path touches.

    getLanIp answers None so the CSRF origin handling stays a no-op: it has its
    own file (test_csrf_flow.py) and only adds noise anywhere else.
    """

    def __init__(self, running=False):
        self.running = running

    def getLanIp(self):
        return None

    async def ensureCsrfAllowedOrigin_async(self, previously_managed):
        return previously_managed, False

    async def isSunshineRunning_async(self):
        return self.running


class StartStopController(FakeController):
    """Adds the two calls that change that answer, each able to fail.

    The call counts matter as much as the outcome: several paths are about
    whether Sunshine was asked at all, not about what came back.
    """

    def __init__(self, running=False, start_succeeds=True, stop_succeeds=True):
        super().__init__(running)
        self.start_succeeds = start_succeeds
        self.stop_succeeds = stop_succeeds
        self.start_calls = 0
        self.stop_calls = 0

    async def start_async(self):
        self.start_calls += 1
        self.running = self.start_succeeds
        return self.start_succeeds

    async def stop_async(self):
        self.stop_calls += 1
        if self.stop_succeeds:
            self.running = False
        return self.stop_succeeds


@pytest.fixture
def log(decky_stub):
    """What the plugin told the user, as one searchable list.

    A RecordingLogger like the `logger` fixture, but the one main.py writes
    to: it logs through the `decky` module rather than through a controller.
    """
    return decky_stub.logger
