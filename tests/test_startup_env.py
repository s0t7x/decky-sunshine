"""The preconditions that made the plugin unusable.

Starting Sunshine and keeping it up is the plugin's job, and all three of these
broke that before the process ever got far enough to log anything useful:

A) LD_LIBRARY_PATH - the Decky loader is a PyInstaller one-file binary and
   points the variable at its own bundled libraries. That value must not reach
   the system binaries we spawn.
B) The display gate - when drm_info is not installed the check can never
   succeed, so it has to be skipped rather than block Sunshine forever.
C) The environment Sunshine is spawned with - its Qt tray aborts the whole
   process when Qt finds no usable platform plugin.

A start that stalls at the gate shows the user nothing but "Stopped", so the
log is the whole explanation of a minute spent waiting - and is checked as
part of each gate.
"""
import asyncio
import subprocess

import pytest

from sunshine import SunshineController


# --- A) LD_LIBRARY_PATH sanitizing -------------------------------------------

sanitize = SunshineController._sanitizedLibraryPath


@pytest.mark.parametrize("environment, expected, why", [
    ({"LD_LIBRARY_PATH": "/tmp/_MEIabc123", "LD_LIBRARY_PATH_ORIG": "/opt/lib"}, "/opt/lib",
     "PyInstaller keeps the original - that is what subprocesses must see"),
    ({"LD_LIBRARY_PATH": "/tmp/_MEIffP9EH"}, None,
     "the loader's own environment: nothing but the bundled path, so nothing is set"),
    ({"LD_LIBRARY_PATH": "/opt/a:/tmp/_MEIabc123:/opt/b"}, "/opt/a:/opt/b",
     "real entries survive in order, the bundled one is dropped"),
    ({"LD_LIBRARY_PATH": "/tmp/_MEIabc123/:/opt/a"}, "/opt/a",
     "a trailing slash must not defeat the match"),
    ({"LD_LIBRARY_PATH": ":/opt/a::"}, "/opt/a",
     "empty entries mean the current directory to the linker"),
    ({}, None,
     "unset stays unset"),
    ({"LD_LIBRARY_PATH": "/tmp/mylibs:/opt/a"}, "/tmp/mylibs:/opt/a",
     "an unrelated path below /tmp is not ours to remove"),
])
def test_the_bundled_library_path_is_kept_from_subprocesses(environment, expected, why):
    assert sanitize(environment) == expected, why


# --- B) the display gate ------------------------------------------------------

@pytest.fixture
def gate_controller(bare_controller, logger):
    """A controller stubbed down to the gate and the step right behind it.

    _copyBwrap fails, so start_async returns immediately after the gate - which
    makes "did the gate let us through" observable as a call count rather than
    as a side effect somewhere further down.
    """

    def _make(path_dir, display_available, audio_available=True):
        controller = bare_controller(
            environment_variables={"PATH": str(path_dir), "FLATPAK_BWRAP": "/nonexistent/bwrap"},
            force_composition=False,
            display_checks=0,
            audio_checks=0,
            copy_calls=0,
        )

        async def not_running():
            return False

        def check_display():
            controller.display_checks += 1
            return display_available

        def check_audio():
            controller.audio_checks += 1
            return audio_available

        def copy_bwrap():
            controller.copy_calls += 1
            return False

        controller.isSunshineRunning_async = not_running
        controller._isDisplayAvailable = check_display
        controller._isAudioAvailable = check_audio
        controller._copyBwrap = copy_bwrap
        return controller

    return _make


@pytest.fixture
def no_sleep(monkeypatch):
    """60 retries of real waiting is not something a test may spend - but how
    long was asked for is the point, so it is recorded rather than dropped."""
    slept = []

    async def instant(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", instant)
    return slept


@pytest.fixture
def bin_with_drm_info(tmp_path):
    directory = tmp_path / "bin-with-drm-info"
    directory.mkdir()
    drm_info = directory / "drm_info"
    drm_info.write_text("#!/bin/sh\n")
    drm_info.chmod(0o755)
    return directory


@pytest.fixture
def bin_without_drm_info(tmp_path):
    directory = tmp_path / "bin-without-drm-info"
    directory.mkdir()
    return directory


async def test_the_gate_is_skipped_when_drm_info_is_missing(
        gate_controller, bin_without_drm_info, no_sleep):
    """Without drm_info the check can never succeed, so waiting for it
    would block Sunshine forever on a machine that is perfectly able to run."""
    controller = gate_controller(bin_without_drm_info, display_available=False)

    result = await controller.start_async()

    assert result is False, "expected the stubbed _copyBwrap to fail the start"
    assert controller.display_checks == 0
    assert ("drm_info is not installed - cannot check whether a display is ready. "
            "Starting Sunshine without that check; it may fail if no display is "
            "available yet.") in controller.logger.warnings
    assert "Audio subsystem available" in controller.logger.infos, \
        "and the line may not claim a display was checked"


async def test_drm_info_is_looked_for_on_the_path_sunshine_will_get(
        gate_controller, bin_with_drm_info, monkeypatch, no_sleep):
    """Not the plugin process's own PATH. The controller sanitizes the
    environment it hands to subprocesses, and the check has to be made against
    that same one - otherwise the gate decides using a PATH the tools it
    guards will never see."""
    controller = gate_controller(bin_with_drm_info, display_available=True)
    del controller.environment_variables["PATH"]
    monkeypatch.setenv("PATH", str(bin_with_drm_info))

    await controller.start_async()

    assert controller.display_checks == 0, \
        "with no PATH of its own the search falls back to the default one, " \
        "which does not hold this drm_info"


async def test_an_available_display_passes_the_gate_on_the_first_check(
        gate_controller, bin_with_drm_info, no_sleep):
    controller = gate_controller(bin_with_drm_info, display_available=True)

    await controller.start_async()

    assert controller.display_checks == 1
    assert "Display and audio subsystem available" in controller.logger.infos


async def test_a_missing_audio_subsystem_is_waited_out_but_not_fatal(
        gate_controller, bin_with_drm_info, no_sleep, logger):
    """The two halves of the gate are deliberately asymmetric: Sunshine without
    sound is worth having, Sunshine without a display is not."""
    controller = gate_controller(bin_with_drm_info, display_available=True,
                                 audio_available=False)

    await controller.start_async()

    assert controller.audio_checks == 60
    assert controller.copy_calls == 1, "the start goes ahead anyway"
    assert ("Audio subsystem not available after waiting. Starting Sunshine anyway..."
            in logger.warnings)
    assert "Audio subsystem not available yet. Checking again in 1 second" in logger.infos
    assert "Display available" in logger.infos, \
        "the half that did work has to be named too, or the line reads like nothing came up"


async def test_a_missing_display_stops_the_start_at_the_gate(
        gate_controller, bin_with_drm_info, no_sleep, logger):
    controller = gate_controller(bin_with_drm_info, display_available=False)

    await controller.start_async()

    assert controller.copy_calls == 0, "nothing past the gate may run"
    assert "Display not available yet. Checking again in 1 second" in logger.infos
    assert "Aborting wait for display." in logger.errors


async def test_the_display_gate_is_bounded_at_sixty_checks(
        gate_controller, bin_with_drm_info, no_sleep):
    """One check per second, so a minute of waiting for a display that is not
    coming. Pinned exactly rather than as an upper bound: the number has to be
    finite AND long enough for a cold boot, and a loose "<= 60" would still
    pass on a gate that gave up after the first look."""
    controller = gate_controller(bin_with_drm_info, display_available=False)

    assert await controller.start_async() is False

    assert controller.display_checks == 60
    assert no_sleep == [1] * 59, "one second a check, so about a minute in all"


# --- C) the environment Sunshine is spawned with ------------------------------
# We run Sunshine as root, which has no session of its own. Its Qt tray falls
# back to a headless platform plugin when no display variable is set, but a
# DISPLAY naming an endpoint root cannot reach sends Qt looking for xcb instead:
# it finds no usable plugin and aborts the process with SIGABRT before the main
# loop, so every start failed.

@pytest.fixture
def spawn_controller(logger, bin_without_drm_info):
    """Stubbed down to everything start_async does between the gate and the
    spawn, so the Popen arguments are the only thing under test."""

    class SpawnController(SunshineController):
        def __init__(self, ever_runs=True, already_running=False,
                     force_composition=False, root_steps_succeed=True,
                     setuid_effective=True, failing_step=None):
            self.logger = logger
            self.environment_variables = {"PATH": str(bin_without_drm_info),
                                          "FLATPAK_BWRAP": "/nonexistent/bwrap"}
            self.force_composition = force_composition
            self._seen_running = already_running
            self._ever_runs = ever_runs
            self.running_checks = 0
            self.root_steps = []
            # The tool name alone answers "in what order"; the whole call is
            # what answers "with what", and both are worth pinning.
            self.root_calls = []
            self._root_steps_succeed = root_steps_succeed
            self._failing_step = failing_step
            self._setuid_effective = setuid_effective
            self.composition_applications = 0

        async def isSunshineRunning_async(self):
            # False at the entry check, True once spawned, so start_async
            # neither returns early nor waits for a process that never exists.
            self.running_checks += 1
            if not self._ever_runs:
                return False
            was_running, self._seen_running = self._seen_running, True
            return was_running

        def _isAudioAvailable(self):
            return True

        def _copyBwrap(self):
            return True

        def _run_and_check(self, args, context=None):
            self.root_steps.append(args[0])
            self.root_calls.append((list(args), context))
            return args[0] != self._failing_step and self._root_steps_succeed

        def _verifySetuidBit(self, path):
            self.root_steps.append("verify")
            self.root_calls.append((["verify", path], None))
            return self._setuid_effective

        async def _applyCompositionForce(self):
            self.composition_applications += 1

    return SpawnController


@pytest.fixture
def recorded_spawn(monkeypatch):
    """Captures the Popen call instead of starting anything."""
    spawned = {}

    def fake_popen(args, env=None, start_new_session=None):
        spawned["args"] = list(args)
        # The object itself, not a copy: whether Sunshine is handed the
        # environment the controller built is a question about identity.
        spawned["env_object"] = env
        spawned["env"] = dict(env or {})
        spawned["start_new_session"] = start_new_session
        return None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return spawned


async def test_a_successful_spawn_reports_success(spawn_controller, recorded_spawn):
    assert await spawn_controller().start_async() is True


async def test_sunshine_is_spawned_with_exactly_this_command_line(spawn_controller,
                                                                   recorded_spawn):
    """Every part of it was put there for a reason and none of it is visible
    anywhere else - a wrong one produces a Sunshine that dies on startup with
    an error about something entirely different.

    --system, because the plugin runs as root and the user's per-user flatpak
    installation is not ours to reach into. --socket=wayland, because that is
    what the capture needs. QT_QPA_PLATFORM=offscreen, because Sunshine's tray
    is Qt-based and aborts the whole process when Qt finds no usable platform
    plugin - and running as root there is nothing to draw on.
    """
    await spawn_controller().start_async()

    assert recorded_spawn["args"] == [
        "flatpak", "run", "--system", "--socket=wayland",
        "--env=QT_QPA_PLATFORM=offscreen", SunshineController.SunshineFlatpakAppId,
    ]


async def test_sunshine_outlives_the_plugin_process(spawn_controller, recorded_spawn):
    """A new session of its own, so the loader restarting or killing the
    plugin does not take the stream down with it. It is also why start_async
    has to cope with finding Sunshine already running."""
    await spawn_controller().start_async()

    assert recorded_spawn["start_new_session"] is True


async def test_sunshine_inherits_the_environment_the_controller_built(spawn_controller,
                                                                      recorded_spawn):
    """Not the plugin's own: PULSE_SERVER, the sanitized LD_LIBRARY_PATH and
    the absent DISPLAY are all decided in this dict, and handing Sunshine
    anything else silently undoes every one of them."""
    controller = spawn_controller()
    controller.environment_variables["PULSE_SERVER"] = "unix:/run/user/1000/pulse/native"

    await controller.start_async()

    assert recorded_spawn["env_object"] is controller.environment_variables


async def test_no_display_is_handed_to_sunshine(spawn_controller, recorded_spawn):
    await spawn_controller().start_async()

    assert "DISPLAY" not in recorded_spawn["env"], sorted(recorded_spawn["env"])




async def test_a_sunshine_that_never_comes_up_reports_failure(
        spawn_controller, recorded_spawn, no_sleep, logger):
    """main.py keys the run intent and the watchdog's failure count off this
    return value: a false success resets the count, and the restart limit stops
    limiting anything."""
    assert await spawn_controller(ever_runs=False).start_async() is False
    assert "Aborting wait for Sunshine process to start." in logger.errors
    assert "Sunshine process not found yet. Checking again in 0.25 seconds" in logger.infos


async def test_the_wait_for_the_process_is_bounded_at_twenty_retries(
        spawn_controller, recorded_spawn, no_sleep):
    """One check before the spawn decides whether to start at all, then twenty
    in the wait - the same shape as the stop side, and pinned for the same
    reason: the step length times the bound is what decides whether a Deck
    under load gets its five seconds."""
    controller = spawn_controller(ever_runs=False)

    await controller.start_async()

    assert no_sleep == [0.25] * 19, "quarter-second steps, so about five seconds"

    assert controller.running_checks == 21


async def test_a_spawn_that_raises_reports_failure(spawn_controller, monkeypatch, logger):
    failure = OSError("flatpak not found")

    def raising_popen(args, env=None, start_new_session=None):
        raise failure

    monkeypatch.setattr(subprocess, "Popen", raising_popen)

    assert await spawn_controller().start_async() is False
    assert ("An error occurred when starting Sunshine", failure) in logger.raised, \
        "the reason exists nowhere else - the panel only ever says Stopped"


def test_the_bwrap_copy_goes_where_only_root_may_write(monkeypatch, logger):
    """Not the plugin's runtime directory, which the deck user may write: the
    copy is setuid root, so anyone who can write there can have their own
    program run as root. The path is handed to flatpak through the environment
    and appears nowhere else."""
    controller = SunshineController(logger)

    assert controller.environment_variables["FLATPAK_BWRAP"] == \
        "/var/lib/decky-sunshine/bwrap"


def test_a_fresh_controller_assumes_nothing_about_the_override(monkeypatch, logger):
    """All four start from "not done, not known". The composition override
    writes to gamescope as another user, so a controller that came up already
    believing it had applied one would skip the release on the next stop and
    leave the Deck compositing forever."""
    controller = SunshineController(logger)

    assert controller.force_composition is False
    assert controller._composition_applied is None, \
        "None means \"never looked\", which is what makes the first reconcile write"
    assert controller._composition_verify_remaining == 0
    assert controller._composition_watch_task is None
    assert controller._display_check_warned is False


def test_the_constructor_adds_no_display_of_its_own(monkeypatch, logger):
    """Whatever the loader passes down is inherited, but we invent none."""
    monkeypatch.delenv("DISPLAY", raising=False)

    controller = SunshineController(logger)

    assert "DISPLAY" not in controller.environment_variables


def test_the_constructor_hands_sunshine_the_socket_it_found(monkeypatch, logger):
    """Sunshine inherits this environment, and on a cold boot the socket the
    loader's own environment names may not be the right one yet. Which socket
    is the right one is test_audio_socket.py's subject; this is the wiring."""
    monkeypatch.delenv("PULSE_SERVER", raising=False)
    monkeypatch.setattr(SunshineController, "_findPulseAudioSocketPath",
                        lambda self: "/run/user/1003/pulse/native")

    controller = SunshineController(logger)

    assert controller.environment_variables["PULSE_SERVER"] == "unix:/run/user/1003/pulse/native"


def test_an_externally_configured_audio_socket_is_left_alone(monkeypatch, logger):
    """Somebody configured it deliberately - a systemd drop-in for the loader
    service, say - and knows better than the discovery does."""
    monkeypatch.setenv("PULSE_SERVER", "tcp:192.168.1.5:4713")

    controller = SunshineController(logger)

    assert controller.environment_variables["PULSE_SERVER"] == "tcp:192.168.1.5:4713"
    assert any("externally configured" in line for line in logger.infos)


def test_the_constructor_drops_a_path_that_is_only_the_loaders(monkeypatch, logger):
    """The loader's own environment names nothing but its bundled directory.
    Handing that on is what killed sh with "undefined symbol:
    rl_trim_arg_from_keyseq" and took the uninstall helper with it, so the
    variable has to disappear rather than be passed on empty.

    Both this and the test below set the variable explicitly, because a
    machine that happens to have none covers this line by accident - which is
    how it stayed uncovered on a CI runner while passing locally.
    """
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIffP9EH")

    controller = SunshineController(logger)

    assert "LD_LIBRARY_PATH" not in controller.environment_variables


def test_the_constructor_invents_no_library_path(monkeypatch, logger):
    """The other half: a system with none to begin with must not come back
    with an empty one, which some loaders read as "the current directory"."""
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

    controller = SunshineController(logger)

    assert "LD_LIBRARY_PATH" not in controller.environment_variables


def test_the_constructor_keeps_a_library_path_that_is_not_the_loaders(monkeypatch, logger):
    """Dropping it outright would break subprocesses on a system that needs it;
    only the loader's own bundled directory has to go. Section A checks the
    sanitizing itself - this checks that the constructor applies it."""
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/vendor/lib:/tmp/_MEIabc123")

    controller = SunshineController(logger)

    assert controller.environment_variables["LD_LIBRARY_PATH"] == "/opt/vendor/lib"


def test_the_legacy_bwrap_path_follows_the_runtime_directory(monkeypatch, logger):
    monkeypatch.setenv("DECKY_PLUGIN_RUNTIME_DIR", "/tmp/decky-runtime")

    assert SunshineController(logger).legacyBwrapPath == "/tmp/decky-runtime/bwrap"


def test_without_a_runtime_directory_there_is_no_legacy_path(monkeypatch, logger):
    monkeypatch.delenv("DECKY_PLUGIN_RUNTIME_DIR", raising=False)

    assert SunshineController(logger).legacyBwrapPath is None


# --- D) the steps between the gate and the spawn ------------------------------
# bwrap is re-copied from the trusted system binary on every start and made
# setuid root, because Sunshine needs it for KMS/DRM capture. None of the three
# steps may be skipped over: a bwrap that is not setuid root leaves Sunshine
# without a DRM handle and no encoder, and it dies without a usable error.

async def test_a_failed_ownership_change_stops_the_start(spawn_controller, recorded_spawn):
    controller = spawn_controller(root_steps_succeed=False)

    assert await controller.start_async() is False
    assert controller.root_steps == ["chown"], "nothing past it may run"
    assert "args" not in recorded_spawn, "and Sunshine is not spawned"


async def test_a_failed_setuid_chmod_stops_the_start(spawn_controller, recorded_spawn):
    controller = spawn_controller(failing_step="chmod")

    assert await controller.start_async() is False
    assert controller.root_steps == ["chown", "chmod"]
    assert "args" not in recorded_spawn


async def test_a_setuid_bit_that_did_not_take_stops_the_start(spawn_controller,
                                                              recorded_spawn):
    """chmod can succeed without the bit taking effect - a filesystem that does
    not store it, or a nosuid mount that stores and ignores it. Sunshine would
    then start and fail later without saying why."""
    controller = spawn_controller(setuid_effective=False)

    assert await controller.start_async() is False
    assert controller.root_steps == ["chown", "chmod", "verify"]
    assert "args" not in recorded_spawn


async def test_a_successful_start_walks_all_three_steps(spawn_controller, recorded_spawn):
    controller = spawn_controller()

    assert await controller.start_async() is True
    assert controller.root_steps == ["chown", "chmod", "verify"]


async def test_each_step_is_aimed_at_the_bwrap_copy_with_the_right_arguments(
        spawn_controller, recorded_spawn):
    """root:root and u+s on the copy named by FLATPAK_BWRAP - the whole point
    of the exercise. Any of these three going somewhere else, or asking for
    something else, produces a Sunshine without a DRM handle that dies without
    saying why; and the context is what the failure says in the log."""
    controller = spawn_controller()
    bwrap = controller.environment_variables["FLATPAK_BWRAP"]

    await controller.start_async()

    assert controller.root_calls == [
        (["chown", "0:0", bwrap], "setting owner on bwrap to root"),
        (["chmod", "u+s", bwrap], "setting setuid on bwrap"),
        (["verify", bwrap], None),
    ]


# --- E) the composition override around a start -------------------------------

async def test_the_override_is_applied_after_a_successful_start(spawn_controller,
                                                                recorded_spawn):
    controller = spawn_controller(force_composition=True)

    await controller.start_async()

    assert controller.composition_applications == 1


async def test_it_is_left_alone_when_the_toggle_is_off(spawn_controller, recorded_spawn):
    controller = spawn_controller()

    await controller.start_async()

    assert controller.composition_applications == 0


async def test_a_sunshine_that_is_already_running_is_not_started_again(
        spawn_controller, recorded_spawn):
    """It survived a plugin_loader restart via setsid. Spawning a second one
    would leave two instances fighting over the same ports."""
    controller = spawn_controller(already_running=True)

    assert await controller.start_async() is True
    assert "args" not in recorded_spawn
    assert controller.root_steps == []


async def test_a_surviving_instance_still_gets_the_override_re_asserted(
        spawn_controller, recorded_spawn):
    """The plugin was reloaded, so what we last wrote is forgotten while the
    atom may be anything - the setting and the atom have to be brought back
    together even though nothing was started."""
    controller = spawn_controller(already_running=True, force_composition=True)

    await controller.start_async()

    assert controller.composition_applications == 1


async def test_without_drm_info_a_missing_audio_subsystem_still_starts_sunshine(
        gate_controller, bin_without_drm_info, no_sleep, logger):
    """No drm_info and a cold audio stack at once: neither check can say yes,
    and Sunshine still has to be started rather than never."""
    controller = gate_controller(bin_without_drm_info, display_available=False,
                                 audio_available=False)

    await controller.start_async()

    assert controller.display_checks == 0
    assert controller.audio_checks == 60
    assert controller.copy_calls == 1, "the start goes ahead"
    assert any("Starting Sunshine anyway" in line for line in logger.warnings)
