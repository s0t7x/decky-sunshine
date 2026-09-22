"""The uninstall cleanup.

The setuid-root bwrap copy must not survive an uninstall - leaving it behind
would leave a root-capable binary on the system with nothing owning it any more.

The cleanup also has to fit into the loader's budget: it sends SIGTERM and
SIGKILLs about five seconds later, and on the Deck the event loop was observed
stopped mid-uninstall, so a coroutine parked at an await was never resumed.
Everything that matters therefore happens before the first suspension point,
ordered by cost: dispatch the detached helper (~2 ms), then do the removals.
"""
import asyncio

import pytest

import sunshine as sunshine_module
from sunshine import SunshineController


# --- removeBwrapCopy ----------------------------------------------------------

@pytest.fixture
def make_controller(bare_controller, tmp_path):
    def _make(bwrap_dir, legacy_path=None):
        return bare_controller(
            environment_variables={"FLATPAK_BWRAP": str(bwrap_dir / "bwrap")},
            legacyBwrapPath=str(legacy_path) if legacy_path is not None else None,
        )

    return _make


@pytest.fixture
def bwrap_dir(tmp_path):
    directory = tmp_path / "var-lib-decky-sunshine"
    directory.mkdir()
    (directory / "bwrap").write_text("fake binary")
    return directory


@pytest.fixture
def legacy_copy(tmp_path):
    """The pre-/var/lib location, inside the plugin's own runtime dir."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "bwrap").write_text("fake legacy binary")
    (runtime / "other.txt").write_text("keep me")
    return runtime / "bwrap"


def test_the_bwrap_directory_is_removed_entirely(make_controller, bwrap_dir, logger):
    assert make_controller(bwrap_dir).removeBwrapCopy() is True
    assert not bwrap_dir.exists()
    assert f"Removed the bwrap copy directory {bwrap_dir}" in logger.infos, \
        "a setuid-root binary going away is worth a line naming where it was"


def test_removal_is_idempotent(make_controller, tmp_path):
    """Running it again after the directory is gone is not a failure."""
    assert make_controller(tmp_path / "gone").removeBwrapCopy() is True


def test_the_legacy_copy_is_removed_but_not_its_directory(
        make_controller, tmp_path, legacy_copy, logger):
    """The runtime dir belongs to the loader, not to us."""
    runtime = legacy_copy.parent

    assert make_controller(tmp_path / "gone", legacy_path=legacy_copy).removeBwrapCopy() is True
    assert not legacy_copy.exists()
    assert runtime.is_dir()
    assert (runtime / "other.txt").exists()
    assert f"Removed the legacy bwrap copy {legacy_copy}" in logger.infos


def test_an_unknown_or_absent_legacy_path_is_not_a_failure(make_controller, tmp_path):
    assert make_controller(tmp_path / "gone", legacy_path=None).removeBwrapCopy() is True
    assert make_controller(tmp_path / "gone",
                           legacy_path=tmp_path / "nothing-here").removeBwrapCopy() is True


def test_a_failed_directory_removal_still_removes_the_legacy_copy(
        make_controller, tmp_path, legacy_copy, logger):
    """The two steps are independent, so one failing may not skip the other."""
    not_a_dir = tmp_path / "not-a-dir"
    not_a_dir.write_text("a file where a directory is expected")

    controller = make_controller(not_a_dir, legacy_path=legacy_copy)

    assert controller.removeBwrapCopy() is False
    assert not legacy_copy.exists()
    assert logger.raised_with_traceback(
        f"An error occurred when removing the bwrap copy directory {not_a_dir}")


# --- Plugin._uninstall --------------------------------------------------------

class FakeController:
    def __init__(self, remove_raises=False, dispatch_raises=False):
        self.calls = []
        self.remove_raises = remove_raises
        self.dispatch_raises = dispatch_raises

    def removeBwrapCopy(self):
        self.calls.append("remove")
        if self.remove_raises:
            raise RuntimeError("remove boom")
        return True

    def dispatchUninstallCleanup(self, log_path):
        self.calls.append(("dispatch", log_path))
        if self.dispatch_raises:
            raise RuntimeError("dispatch boom")
        return True


@pytest.fixture
def uninstall(load_main, decky_stub):
    """Builds a Plugin and hands back its _uninstall coroutine plus the
    log path the dispatch is expected to be given."""
    import os
    import types

    from conftest import FakeSettingsManager

    decky_stub.DECKY_PLUGIN_LOG_DIR = "/tmp/decky-sunshine-test-logs"
    sunshine = types.ModuleType("sunshine")
    sunshine.SunshineController = FakeController
    main = load_main(sunshine)

    def _make(controller):
        plugin = main.Plugin()
        plugin.sunshineController = controller
        plugin.settingManager = FakeSettingsManager()
        return plugin

    _make.expected_log = os.path.join(decky_stub.DECKY_PLUGIN_LOG_DIR, "uninstall-cleanup.log")
    return _make


def test_the_cleanup_completes_without_ever_suspending(uninstall):
    """Driving the coroutine by hand proves it: the first send() has to finish
    it. Anything after a suspension point is not guaranteed to run at all when
    the loop is stopped mid-uninstall."""
    controller = FakeController()
    coroutine = uninstall(controller)._uninstall()

    with pytest.raises(StopIteration):
        coroutine.send(None)


def test_the_helper_is_dispatched_before_the_removal(uninstall, log):
    """Ordered by cost, because the process can die at any moment: the ~2 ms
    dispatch first, then the removals. There is no in-process stop at all - it
    never ran to completion in the field."""
    controller = FakeController()

    asyncio.run(uninstall(controller)._uninstall())

    assert controller.calls == [("dispatch", uninstall.expected_log), "remove"]
    # The plugin's log is about to be the only place this ever happened, and
    # the closing line is what says the cleanup was not cut short.
    assert "Uninstalling Decky Sunshine..." in log.infos
    assert "Decky Sunshine uninstall cleanup done" in log.infos


@pytest.mark.parametrize("failing, reported", [
    ("dispatch_raises", "Error dispatching the uninstall cleanup: dispatch boom"),
    ("remove_raises", "Error removing the bwrap copy during uninstall: remove boom"),
])
def test_one_step_failing_neither_skips_the_other_nor_reaches_the_loader(uninstall, log,
                                                                         failing, reported):
    """An exception here aborts the loader's own "Uninstalled <name>" handling,
    and any later reordering could then skip cleanup steps silently.

    The swallowed exception has to name which step it was and what went wrong:
    a setuid-root binary may have been left behind, and nobody will look for it
    unless the log says so.
    """
    controller = FakeController(**{failing: True})

    asyncio.run(uninstall(controller)._uninstall())    # must not raise

    assert controller.calls == [("dispatch", uninstall.expected_log), "remove"]
    assert reported in log.errors
    assert "Decky Sunshine uninstall cleanup done" in log.infos


def test_an_uninstall_before_main_ever_ran_does_not_crash(uninstall):
    plugin = uninstall(FakeController())
    plugin.sunshineController = None

    asyncio.run(plugin._uninstall())


# --- dispatchUninstallCleanup -------------------------------------------------
# The helper runs detached, because it has to survive the plugin process dying
# at any point - which the loader's SIGKILL five seconds after SIGTERM does not
# guarantee. On the Deck the process died before an in-process stop got anywhere.

@pytest.fixture
def real_controller(bare_controller):
    return bare_controller(
        _getSessionUsername=lambda: "deck",
        # Any dict will do: the test below asserts that this very object is
        # handed to Popen, not what is in it. __init__ builds the real one by
        # stripping the loader's bundled libraries out of LD_LIBRARY_PATH.
        environment_variables={"LD_LIBRARY_PATH": "/opt/vendor/lib"},
    )


@pytest.fixture
def recorded_popen(monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(sunshine_module.subprocess, "Popen", FakePopen)
    return calls


def test_the_helper_kills_sunshine_and_releases_the_atom_as_the_session_user(
        real_controller, recorded_popen):
    assert real_controller.dispatchUninstallCleanup("/var/log/dir with space/cleanup.log") is True
    assert len(recorded_popen) == 1

    args, kwargs = recorded_popen[0]

    assert kwargs.get("start_new_session") is True, "it needs its own session to survive"
    assert args[:2] == ["sh", "-c"], "any other flag makes sh read the script as a filename"
    script = args[2]
    assert script.startswith("exec >> '/var/log/dir with space/cleanup.log' 2>&1\n"), \
        "everything the helper prints has to land in the log, and the path has to be quoted"
    assert "flatpak kill dev.lizardbyte.app.Sunshine" in script
    assert "su deck -c" in script
    assert "GAMESCOPE_COMPOSITE_FORCE 0" in script
    assert 'echo "$(date) - uninstall cleanup done"' in script.splitlines(), \
        "the helper\'s own log is all there is once the plugin is gone"


def test_the_helper_gets_the_sanitized_environment(real_controller, recorded_popen):
    """Not the raw inherited one: the plugin runs inside the PyInstaller-packed
    loader whose LD_LIBRARY_PATH points at bundled libraries, and sh (= bash)
    then dies on the bundled libreadline - "undefined symbol:
    rl_trim_arg_from_keyseq", and the helper was gone instantly."""
    real_controller.dispatchUninstallCleanup("/tmp/x.log")

    _, kwargs = recorded_popen[0]

    assert kwargs.get("env") is real_controller.environment_variables


def test_without_a_session_user_the_kill_is_still_dispatched(real_controller, recorded_popen):
    """Killing Sunshine must not depend on the atom part working out."""
    real_controller._getSessionUsername = lambda: None

    assert real_controller.dispatchUninstallCleanup("/tmp/x.log") is True

    script = recorded_popen[0][0][2]
    assert "flatpak kill dev.lizardbyte.app.Sunshine" in script
    assert "su " not in script
    assert ('echo "no session user found - not touching the composition override"'
            in script.splitlines()), \
        "and the helper\'s log has to say why it skipped that half"


def test_a_spawn_failure_is_reported_rather_than_raised(real_controller, monkeypatch,
                                                        logger):
    class RaisingPopen:
        def __init__(self, args, **kwargs):
            raise OSError("spawn failed")

    monkeypatch.setattr(sunshine_module.subprocess, "Popen", RaisingPopen)

    assert real_controller.dispatchUninstallCleanup("/tmp/x.log") is False
    assert logger.raised_with_traceback(
        "An error occurred when dispatching the uninstall cleanup helper")


def test_a_dispatched_helper_says_so(real_controller, recorded_popen, logger):
    """The helper writes to its own log file, which does not exist yet when
    this line is written - so this is the only place the plugin's own log ever
    admits that something was left running behind it."""
    real_controller.dispatchUninstallCleanup("/tmp/x.log")

    assert "Dispatched the detached uninstall cleanup helper" in logger.infos
