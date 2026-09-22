"""_copyBwrap replacing a bwrap copy that is still in use.

The plugin refreshes its setuid bwrap copy on every start. Copying onto the
target fails with ETXTBSY while a process still runs that file as its program
image - which is exactly the state right after stopping Sunshine, because
flatpak reports the instance gone before the bwrap process it was exec'd from
has finished tearing down. With the restart button, stop and start happen in
one call and leave no time for that teardown, so every restart failed here.

The directory the copy lives in matters as much as the copy: it holds a
setuid-root binary, so anyone who can write there can have their own program
run as root.
"""
import errno
import os
import shutil
import stat
import subprocess
import time

import pytest

import sunshine as sunshine_module


# A real binary to stand in for bwrap - it has to be executable for the
# "still running" case to produce ETXTBSY at all.
SOURCE = shutil.which("sleep")


@pytest.fixture
def target_dir(tmp_path):
    return tmp_path / "copy"


@pytest.fixture
def target(target_dir):
    return target_dir / "bwrap"


@pytest.fixture
def make_controller(bare_controller, target):
    def _make(source=SOURCE, path=None):
        return bare_controller(
            environment_variables={"FLATPAK_BWRAP": str(path if path is not None else target),
                                  "PATH": os.environ["PATH"]},
            BwrapSourcePath=str(source),
        )

    return _make


def test_a_fresh_copy_is_created(make_controller, target):
    assert make_controller()._copyBwrap() is True
    assert target.exists()


def wait_until_running(target, process, timeout=5.0):
    """Block until the kernel holds `target` as a running program image.

    That is the state both tests below need, and it arrives when the child
    reaches exec - a fixed sleep either guesses too long or, on a loaded
    machine, stops testing the case at all.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert process.poll() is None, "the stand-in binary exited"
        try:
            os.close(os.open(target, os.O_WRONLY))
        except OSError as error:
            if error.errno == errno.ETXTBSY:
                return
            raise
        time.sleep(0.01)
    raise AssertionError("the stand-in never took a reference on its program image")


def test_plain_cp_onto_a_running_binary_is_refused(make_controller, target):
    """The precondition for the test below - without this, that one could pass
    for the wrong reason on a system that does not enforce ETXTBSY."""
    make_controller()._copyBwrap()
    running = subprocess.Popen([str(target), "30"])
    wait_until_running(str(target), running)
    try:
        result = subprocess.run(["cp", SOURCE, str(target)], capture_output=True, text=True)

        assert result.returncode != 0
        assert "busy" in result.stderr.lower(), result.stderr
    finally:
        running.kill()
        running.wait()


def test_the_copy_is_replaced_even_while_it_runs(make_controller, target):
    make_controller()._copyBwrap()
    running = subprocess.Popen([str(target), "30"])
    wait_until_running(str(target), running)
    try:
        assert make_controller()._copyBwrap() is True
        assert target.exists()
        assert running.poll() is None, "the running process must be left alone"
    finally:
        running.kill()
        running.wait()


def test_a_successful_replace_leaves_no_staging_file(make_controller, target_dir):
    make_controller()._copyBwrap()

    make_controller()._copyBwrap()

    assert os.listdir(target_dir) == ["bwrap"]


def test_a_missing_source_fails_cleanly(make_controller, target_dir, tmp_path):
    make_controller()._copyBwrap()

    assert make_controller(source=tmp_path / "does-not-exist")._copyBwrap() is False
    assert os.listdir(target_dir) == ["bwrap"], "and leaves the previous copy in place"


def test_a_copy_that_fails_partway_still_cleans_up(make_controller, target_dir):
    """The test above only covers the variant where cp never gets far enough to
    create the staging file. This one is what a disk running full looks like."""
    make_controller()._copyBwrap()
    controller = make_controller()

    def write_then_fail(args, context=None):
        controller.contexts.append(context)
        open(args[2], "w").write("half a binary")
        return False

    controller.contexts = []
    controller._run_and_check = write_then_fail

    assert controller._copyBwrap() is False
    assert os.listdir(target_dir) == ["bwrap"]
    assert controller.contexts == ["copying bwrap to its dedicated directory"], \
        "a disk running full shows up as this line and nothing else"


def test_the_directory_is_not_writable_by_group_or_others(make_controller, tmp_path):
    """This is the entire reason the copy moved out of the deck-writable plugin
    runtime dir. makedirs obeys the umask, so a permissive umask - not unusual
    for a root service - would otherwise produce a 0777 directory holding a
    setuid-root binary.
    """
    permissive = tmp_path / "umask-zero"
    saved = os.umask(0)
    try:
        created = make_controller(path=permissive / "bwrap")._copyBwrap()
        mode = os.stat(permissive).st_mode
    finally:
        os.umask(saved)

    assert created is True
    assert mode & (stat.S_IWGRP | stat.S_IWOTH) == 0, oct(mode)


# --- is a copy there at all ---------------------------------------------------

def test_a_copy_in_place_is_recognised(make_controller, target, target_dir):
    target_dir.mkdir()
    target.write_text("")

    assert make_controller()._wasBwrapCopied() is True


def test_no_copy_yet_is_not_an_error(make_controller):
    assert make_controller()._wasBwrapCopied() is False


# --- the failure paths around the copy ----------------------------------------
# All of these end in a False the caller turns into "Sunshine cannot start", so
# the log is the only place the reason can appear.

def test_an_unusable_target_path_is_not_a_crash(bare_controller, logger):
    """FLATPAK_BWRAP comes out of the environment the loader hands us."""
    controller = bare_controller(environment_variables={})

    assert controller._wasBwrapCopied() is False
    assert logger.raised_with_traceback(
        "An error occurred when checking if bwrap was copied")


def test_a_directory_that_cannot_be_created_fails_the_copy(make_controller, tmp_path,
                                                           logger):
    """The target sits under /var/lib, which only root may write - on a system
    where the plugin does not run as root this is where it stops."""
    blocked = tmp_path / "file-in-the-way"
    blocked.write_text("")
    controller = make_controller(path=blocked / "sub" / "bwrap")

    assert controller._copyBwrap() is False
    assert logger.raised_with_traceback(
        "An error occurred when creating the bwrap directory")


def test_a_replace_that_fails_leaves_no_staging_file(make_controller, target_dir,
                                                     monkeypatch, logger):
    """The staging copy is setuid-root material too; leaving it behind would
    put an unowned root-capable binary next to the real one."""

    controller = make_controller()

    def failing_replace(source, destination):
        raise OSError("Invalid cross-device link")

    monkeypatch.setattr(sunshine_module.os, "replace", failing_replace)

    assert controller._copyBwrap() is False
    assert list(target_dir.iterdir()) == []
    assert logger.raised_with_traceback(
        f"An error occurred when moving the bwrap copy into place at {target_dir / 'bwrap'}")


def test_removing_something_that_cannot_be_removed_is_reported(bare_controller,
                                                               tmp_path, logger):
    controller = bare_controller()

    controller._removeIfPresent(str(tmp_path))     # a directory, not a file

    assert logger.raised_with_traceback(f"An error occurred when removing {tmp_path}")


def test_a_legacy_copy_that_cannot_be_removed_fails_the_uninstall(bare_controller,
                                                                  tmp_path, logger):
    """The uninstall reports it so the user learns a setuid-root binary is
    still on their system rather than finding out never."""
    legacy = tmp_path / "legacy"
    legacy.mkdir()                                  # os.remove refuses a directory
    controller = bare_controller(
        environment_variables={"FLATPAK_BWRAP": str(tmp_path / "gone" / "bwrap")},
        legacyBwrapPath=str(legacy),
    )

    assert controller.removeBwrapCopy() is False
    assert logger.raised_with_traceback(
        f"An error occurred when removing the legacy bwrap copy {legacy}")
