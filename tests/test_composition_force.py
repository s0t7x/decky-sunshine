"""The GAMESCOPE_COMPOSITE_FORCE override - see setCompositionForce for what
it fixes and why the atom rather than the convars.

Everything here exists because the write is expensive and unreliable:

  * expensive - Sunshine runs as root with no session, so each write is an
    `su <user> -c "DISPLAY=:0 xprop ..."` subprocess that fails noisily where
    that does not work. Hence: only while streaming, only while docked, and
    only when the value actually changes.
  * unreliable - on a cold boot the gamescope session finishes initializing
    after the plugin has already written, and resets the atom to 0. Hence the
    bounded re-verification window after every write.

A) setCompositionForce and the session user it needs
B) _isExternalDisplayConnected - the dock state, from sysfs
C) _getCompositionForce - reading the atom back
D) _reconcileCompositionForce - the write decision and the verify window
E) _watchCompositionForce - the loop, and what ends it
F) applyCompositionPreference_async - the panel toggle while Sunshine runs
"""
import asyncio

import pytest

import sunshine as sunshine_module


@pytest.fixture
def runner(bare_controller):
    """A controller that records subprocess calls instead of making them."""

    def _make(stdout=None, succeeds=True, **attributes):
        controller = bare_controller(commands=[], contexts=[], **attributes)

        def check(args, context=None):
            controller.commands.append(list(args))
            controller.contexts.append(context)
            return succeeds

        def capture(args, context=None):
            controller.commands.append(list(args))
            controller.contexts.append(context)
            return stdout

        controller._run_and_check = check
        controller._run_and_capture_stdout = capture
        return controller

    return _make


# --- A) the write and the user it runs as ------------------------------------

def test_the_atom_is_set_as_the_session_user_on_display_zero(runner):
    controller = runner()
    controller._getSessionUsername = lambda: "deck"

    assert controller.setCompositionForce(True) is True
    assert controller.commands == [[
        "su", "deck", "-c",
        "DISPLAY=:0 xprop -root -f GAMESCOPE_COMPOSITE_FORCE 32c "
        "-set GAMESCOPE_COMPOSITE_FORCE 1",
    ]]


def test_the_write_says_what_it_was_doing(runner):
    """su/xprop fails noisily on anything that is not a gamescope session, and
    this context is how that failure names itself in the log."""
    controller = runner()
    controller._getSessionUsername = lambda: "deck"

    controller.setCompositionForce(True)

    assert controller.contexts == ["setting GAMESCOPE_COMPOSITE_FORCE=1"]


def test_releasing_writes_a_zero_rather_than_deleting_the_atom(runner):
    controller = runner()
    controller._getSessionUsername = lambda: "deck"

    controller.setCompositionForce(False)

    assert controller.commands[0][-1].endswith("GAMESCOPE_COMPOSITE_FORCE 0")


def test_without_a_session_user_nothing_is_written(runner, logger):
    """There is no session to write into, and spawning su for a user that does
    not exist only produces noise in the log."""
    controller = runner()
    controller._getSessionUsername = lambda: None

    assert controller.setCompositionForce(True) is False
    assert controller.commands == []
    assert any("No session user found" in line for line in logger.warnings)


def test_a_failed_write_is_reported_as_such(runner):
    """The caller records the applied state off this return value; a false
    success would leave the override stuck in whatever state it is in."""
    controller = runner(succeeds=False)
    controller._getSessionUsername = lambda: "deck"

    assert controller.setCompositionForce(True) is False


def test_the_deck_user_is_preferred(bare_controller, monkeypatch):
    controller = bare_controller()
    monkeypatch.setattr(sunshine_module.pwd, "getpwnam",
                        lambda name: type("Entry", (), {"pw_name": name})())

    assert controller._getSessionUsername() == "deck"


def test_the_logged_in_users_are_looked_for_in_the_runtime_directories(bare_controller,
                                                                       monkeypatch):
    """/run/user/<uid> is what says somebody has a session; the passwd file
    would list every account on the system, logged in or not."""
    patterns = []
    controller = bare_controller()
    monkeypatch.setattr(sunshine_module.pwd, "getpwnam", _raises_key_error)
    monkeypatch.setattr(sunshine_module.glob, "glob",
                        lambda pattern: patterns.append(pattern) or [])

    controller._getSessionUsername()

    assert patterns == ["/run/user/*"]


def test_without_a_deck_user_the_first_regular_user_is_used(bare_controller, monkeypatch):
    """Not every handheld running this is a Deck, and hardcoding "deck" would
    make the override a Deck-only feature."""
    controller = bare_controller()
    monkeypatch.setattr(sunshine_module.pwd, "getpwnam", _raises_key_error)
    monkeypatch.setattr(sunshine_module.glob, "glob",
                        lambda pattern: ["/run/user/1001", "/run/user/0", "/run/user/1000"])
    monkeypatch.setattr(sunshine_module.pwd, "getpwuid",
                        lambda uid: type("Entry", (), {"pw_name": f"user{uid}"})())

    assert controller._getSessionUsername() == "user1000", \
        "sorted by uid as a number, and system users skipped"


def test_a_runtime_directory_without_a_passwd_entry_is_skipped(bare_controller, monkeypatch):
    controller = bare_controller()
    monkeypatch.setattr(sunshine_module.pwd, "getpwnam", _raises_key_error)
    monkeypatch.setattr(sunshine_module.glob, "glob",
                        lambda pattern: ["/run/user/1000", "/run/user/1001"])

    def getpwuid(uid):
        if uid == 1000:
            raise KeyError(uid)
        return type("Entry", (), {"pw_name": "second"})()

    monkeypatch.setattr(sunshine_module.pwd, "getpwuid", getpwuid)

    assert controller._getSessionUsername() == "second"


def test_no_regular_user_at_all_yields_nothing(bare_controller, monkeypatch):
    controller = bare_controller()
    monkeypatch.setattr(sunshine_module.pwd, "getpwnam", _raises_key_error)
    monkeypatch.setattr(sunshine_module.glob, "glob", lambda pattern: ["/run/user/0"])

    assert controller._getSessionUsername() is None


def _raises_key_error(*args, **kwargs):
    raise KeyError("no such user")


# --- B) the dock state -------------------------------------------------------

@pytest.fixture
def connectors(bare_controller, monkeypatch, tmp_path):
    """Builds a sysfs-shaped tree of DRM connectors and points the glob at it."""

    def _make(**states):
        """:param states: connector name (with - as _) -> status text"""
        paths = []
        for name, status in states.items():
            directory = tmp_path / f"card0-{name.replace('_', '-')}"
            directory.mkdir()
            (directory / "status").write_text(status + "\n")
            paths.append(str(directory / "status"))

        def fake_glob(pattern):
            # Recorded rather than ignored: the pattern is the only thing that
            # decides which files are looked at on a real system, and nothing
            # else in this file would notice it changing.
            patterns.append(pattern)
            return paths

        monkeypatch.setattr(sunshine_module.glob, "glob", fake_glob)
        return bare_controller(_display_check_warned=False)

    patterns = []
    _make.patterns = patterns
    return _make


def test_the_connectors_are_looked_for_where_the_kernel_puts_them(connectors):
    """card*-* rather than card*: the status file lives in the connector
    directory, and the card directory itself has none."""
    connectors(DP_2="connected")._isExternalDisplayConnected()

    assert connectors.patterns == ["/sys/class/drm/card*-*/status"]


def test_a_connected_external_display_is_a_dock(connectors):
    controller = connectors(eDP_1="connected", DP_2="connected")

    assert controller._isExternalDisplayConnected() is True


def test_the_internal_panel_alone_is_not_a_dock(connectors):
    """The Deck's own screen is always connected; counting it would keep the
    override on all the time and cost the direct-scanout power saving."""
    controller = connectors(eDP_1="connected", DP_2="disconnected")

    assert controller._isExternalDisplayConnected() is False


@pytest.mark.parametrize("internal", ["eDP_1", "LVDS_1", "DSI_1", "Writeback_1"])
def test_every_kind_of_internal_connector_is_excluded(connectors, internal):
    controller = connectors(**{internal: "connected"})

    assert controller._isExternalDisplayConnected() is False


def test_a_machine_without_any_connectors_is_not_docked(connectors):
    assert connectors()._isExternalDisplayConnected() is False


@pytest.fixture
def unreadable_connector(bare_controller, monkeypatch, tmp_path):
    """A connector path that is never created, so the read really fails.

    Under tmp_path rather than /sys/class/drm: a machine with a GPU has that
    connector, and the test would then read a real file instead of failing.
    The directory name is kept so the connector-name parsing still runs.
    """
    missing = tmp_path / "card0-DP-1" / "status"
    monkeypatch.setattr(sunshine_module.glob, "glob", lambda pattern: [str(missing)])
    return bare_controller(_display_check_warned=False)


def test_an_unreadable_sysfs_assumes_a_dock(unreadable_connector, logger):
    """The fallback is the behaviour from before dock detection existed:
    always applied. Guessing the other way would silently turn the fix off on
    exactly the machines whose sysfs we cannot read."""
    assert unreadable_connector._isExternalDisplayConnected() is True
    assert logger.raised_with_traceback(
        "Could not determine the external display state - assuming one is connected"), \
        "the line has to say which way it guessed, or the override looks broken"


def test_the_failure_is_logged_once_not_once_every_five_seconds(unreadable_connector,
                                                                logger):
    for _ in range(5):
        unreadable_connector._isExternalDisplayConnected()

    assert len(logger.exceptions) == 1


# Parametrised over both outcomes because the reset sits on both return paths:
# a read that worked is a read that worked, docked or not.
@pytest.mark.parametrize("status", ["connected", "disconnected"])
def test_the_warning_re_arms_after_a_reading_that_worked(connectors, status):
    """A transient failure should be reported again if it comes back later -
    docked or not, because both outcomes mean the read worked."""
    controller = connectors(DP_1=status)
    controller._display_check_warned = True

    controller._isExternalDisplayConnected()

    assert controller._display_check_warned is False


# --- C) reading the atom back ------------------------------------------------

def test_the_atom_value_is_parsed(runner):
    controller = runner(stdout="GAMESCOPE_COMPOSITE_FORCE(CARDINAL) = 1\n")
    controller._getSessionUsername = lambda: "deck"

    assert controller._getCompositionForce() == 1


def test_the_atom_is_read_with_exactly_this_command(runner):
    """su -c runs it as the session user, which is the only one with a
    connection to gamescope's display; DISPLAY=:0 is where that display is.
    Both belong to the command string rather than to our environment, because
    su does not carry ours across."""
    controller = runner(stdout="GAMESCOPE_COMPOSITE_FORCE(CARDINAL) = 1\n")
    controller._getSessionUsername = lambda: "deck"

    controller._getCompositionForce()

    assert controller.commands == [
        ["su", "deck", "-c", "DISPLAY=:0 xprop -root GAMESCOPE_COMPOSITE_FORCE"],
    ]
    assert controller.contexts == ["reading GAMESCOPE_COMPOSITE_FORCE"]


def test_an_absent_atom_reads_as_zero(runner):
    """xprop says "no such atom" - which is gamescope having (re)started
    without the override, not an error."""
    controller = runner(stdout='GAMESCOPE_COMPOSITE_FORCE:  not found.\n')
    controller._getSessionUsername = lambda: "deck"

    assert controller._getCompositionForce() == 0


def test_a_failed_read_is_not_a_zero(runner):
    """Zero would trigger a re-assert; None means "do not act on this"."""
    controller = runner(stdout=None)
    controller._getSessionUsername = lambda: "deck"

    assert controller._getCompositionForce() is None


def test_without_a_session_user_nothing_is_read(runner):
    controller = runner(stdout="= 1")
    controller._getSessionUsername = lambda: None

    assert controller._getCompositionForce() is None
    assert controller.commands == []


# --- D) the write decision ---------------------------------------------------

@pytest.fixture
def reconcile(bare_controller):
    """A controller whose dock state and atom writes are scripted."""

    def _make(docked, applied=None, verify_remaining=0, write_succeeds=True, atom=None):
        controller = bare_controller(
            force_composition=True,
            _composition_applied=applied,
            _composition_verify_remaining=verify_remaining,
            _composition_watch_task=None,
            writes=[],
        )
        controller._isExternalDisplayConnected = lambda: docked

        async def set_force(enabled):
            controller.writes.append(enabled)
            return write_succeeds

        controller.setCompositionForce_async = set_force
        controller._getCompositionForce = lambda: atom
        return controller

    return _make


async def test_docking_applies_the_override(reconcile):
    controller = reconcile(docked=True, applied=False)

    await controller._reconcileCompositionForce()

    assert controller.writes == [True]
    assert controller._composition_applied is True
    assert ("Applying the composition override (external display connected)"
            in controller.logger.infos), \
        "the override changes how the stream looks - the log has to say which way"


async def test_undocking_releases_it_again(reconcile):
    controller = reconcile(docked=False, applied=True)

    await controller._reconcileCompositionForce()

    assert controller.writes == [False]
    assert controller._composition_applied is False
    assert ("Releasing the composition override (external display not connected)"
            in controller.logger.infos)


async def test_an_unchanged_dock_state_writes_nothing(reconcile):
    """Every write is an su/xprop subprocess, and this runs every five
    seconds for as long as the stream lasts."""
    controller = reconcile(docked=True, applied=True)

    await controller._reconcileCompositionForce()

    assert controller.writes == []


async def test_the_first_reconcile_after_a_start_always_writes(reconcile):
    """An unknown last value counts as differing: the atom may be anything
    when we arrive, including left over from a previous session."""
    controller = reconcile(docked=False, applied=None)

    await controller._reconcileCompositionForce()

    assert controller.writes == [False]


async def test_a_failed_write_is_not_recorded_as_applied(reconcile):
    """Recording it would make the next reconcile skip the retry."""
    controller = reconcile(docked=True, applied=False, write_succeeds=False)

    await controller._reconcileCompositionForce()

    assert controller._composition_applied is False


async def test_applying_opens_the_verification_window(reconcile):
    controller = reconcile(docked=True, applied=False)

    await controller._reconcileCompositionForce()

    assert controller._composition_verify_remaining == 24


async def test_releasing_closes_it(reconcile):
    """Nothing to defend once the override is off."""
    controller = reconcile(docked=False, applied=True, verify_remaining=24)

    await controller._reconcileCompositionForce()

    assert controller._composition_verify_remaining == 0


async def test_an_atom_gamescope_reset_is_written_again(reconcile):
    """The cold-boot case this window exists for: our write landed, and the
    gamescope session's own initialization overwrote it afterwards."""
    controller = reconcile(docked=True, applied=True, verify_remaining=5, atom=0)

    await controller._reconcileCompositionForce()

    assert controller.writes == [True]
    assert controller._composition_verify_remaining == 24, "the window starts over"
    assert ("GAMESCOPE_COMPOSITE_FORCE was reset (likely by gamescope session "
            "initialization) - re-asserting") in controller.logger.infos, \
        "an override that keeps being overwritten is only visible here"


async def test_a_failed_re_assert_does_not_reopen_the_window(reconcile):
    """Nothing was written, so there is nothing new to defend - the window
    keeps counting down and the next tick tries again."""
    controller = reconcile(docked=True, applied=True, verify_remaining=5, atom=0,
                           write_succeeds=False)

    await controller._reconcileCompositionForce()

    assert controller.writes == [True]
    assert controller._composition_verify_remaining == 4


async def test_the_last_check_of_the_window_still_verifies(reconcile):
    """The boundary of the window rather than its middle: with one check left
    it still has to look, and only that tells `> 0` from `> 1` apart."""
    controller = reconcile(docked=True, applied=True, verify_remaining=1, atom=0)

    await controller._reconcileCompositionForce()

    assert controller.writes == [True], "the last check has to re-assert too"
    assert controller._composition_verify_remaining == 24


async def test_a_closed_window_stops_looking(reconcile):
    controller = reconcile(docked=True, applied=True, verify_remaining=0, atom=0)

    await controller._reconcileCompositionForce()

    assert controller.writes == []


async def test_an_atom_that_still_holds_is_left_alone(reconcile):
    controller = reconcile(docked=True, applied=True, verify_remaining=5, atom=1)

    await controller._reconcileCompositionForce()

    assert controller.writes == []
    assert controller._composition_verify_remaining == 4


async def test_an_unreadable_atom_is_not_treated_as_a_reset(reconcile):
    controller = reconcile(docked=True, applied=True, verify_remaining=5, atom=None)

    await controller._reconcileCompositionForce()

    assert controller.writes == []


async def test_the_window_is_bounded(reconcile):
    """Past it the atom is left alone: gamescope is initialized by then, and
    an xprop read every five seconds for the whole stream is not free."""
    controller = reconcile(docked=True, applied=True, verify_remaining=0, atom=0)

    await controller._reconcileCompositionForce()

    assert controller.writes == []


# --- E) the watcher ----------------------------------------------------------

class StopLoop(Exception):
    """Ends the watcher after a fixed number of ticks."""


@pytest.fixture
def watch(bare_controller, monkeypatch):
    """Runs _watchCompositionForce on a virtual clock.

    :return: "returned" if the watcher ended by itself, "watching" otherwise
    """

    def _make(max_ticks, running=True, force_composition=True, applied=True,
              on_tick=None, write_succeeds=True):
        controller = bare_controller(
            force_composition=force_composition,
            _composition_applied=applied,
            _composition_verify_remaining=0,
            _composition_watch_task=None,
            ticks=0,
            reconciles=0,
            running_checks=0,
            writes=[],
            waits=[],
        )

        async def sleep(seconds):
            if controller.ticks >= max_ticks:
                raise StopLoop
            controller.ticks += 1
            # Recorded, not discarded: the tick length is half of what "every
            # 30 seconds" means, and nothing else can see it.
            controller.waits.append(seconds)
            if on_tick:
                on_tick(controller, controller.ticks)

        async def is_running():
            controller.running_checks += 1
            return running() if callable(running) else running

        async def reconcile():
            controller.reconciles += 1

        async def set_force(enabled):
            controller.writes.append(enabled)
            return write_succeeds

        monkeypatch.setattr(asyncio, "sleep", sleep)
        controller.isSunshineRunning_async = is_running
        controller._reconcileCompositionForce = reconcile
        controller.setCompositionForce_async = set_force
        return controller

    return _make


async def _run(controller):
    try:
        await controller._watchCompositionForce()
        return "returned"
    except StopLoop:
        return "watching"


async def test_the_watcher_reconciles_on_every_tick(watch):
    controller = watch(max_ticks=3)

    assert await _run(controller) == "watching"
    assert controller.reconciles == 3


async def test_sunshine_is_only_polled_every_sixth_tick(watch):
    """The dock state is a sysfs read; asking flatpak whether Sunshine is
    alive is a subprocess, so it runs on a coarser grid - every 30 seconds.

    Both halves of that have to hold: six ticks, and five seconds a tick. Dock
    or undock mid-stream and the override is reconciled on this tick, so a
    longer one leaves the docked capture squeezed for that much longer."""
    controller = watch(max_ticks=12)

    await _run(controller)

    assert controller.running_checks == 2
    assert controller.waits == [5] * 12


async def test_turning_the_toggle_off_ends_the_watcher(watch):
    controller = watch(max_ticks=5,
                       on_tick=lambda c, n: setattr(c, "force_composition", False) if n == 2 else None)

    assert await _run(controller) == "returned"
    assert controller.reconciles == 1, "the tick that saw the toggle off does nothing else"


async def test_a_sunshine_that_died_releases_the_override(watch):
    """No stop_async will run for a crash, so this is the only place the
    override gets released - otherwise gamescope keeps compositing forever."""
    controller = watch(max_ticks=12, running=False)

    assert await _run(controller) == "returned"
    assert controller.writes == [False]
    assert controller._composition_applied is False
    assert controller.reconciles == 5, \
        "the sixth tick has to reconcile as well as check, not instead of it"
    assert "Sunshine is gone - releasing the composition override" in controller.logger.infos


async def test_a_release_that_failed_is_not_recorded_as_done(watch):
    """The watcher ends either way - Sunshine is gone - but the override is
    still on, and the next start has to know that."""
    controller = watch(max_ticks=12, running=False, write_succeeds=False)

    assert await _run(controller) == "returned"
    assert controller.writes == [False]
    assert controller._composition_applied is True


async def test_nothing_is_released_that_was_never_applied(watch):
    controller = watch(max_ticks=12, running=False, applied=False)

    assert await _run(controller) == "returned"
    assert controller.writes == []


# --- F) the panel toggle while Sunshine is running ---------------------------

@pytest.fixture
def preference(bare_controller):
    def _make(force_composition, applied=None, write_succeeds=True):
        controller = bare_controller(
            force_composition=force_composition,
            _composition_applied=applied,
            _composition_verify_remaining=0,
            _composition_watch_task=None,
            writes=[],
            cancels=0,
            applies=0,
        )

        async def set_force(enabled):
            controller.writes.append(enabled)
            return write_succeeds

        async def cancel():
            controller.cancels += 1

        async def apply():
            controller.applies += 1

        controller.setCompositionForce_async = set_force
        controller._cancelCompositionWatch = cancel
        controller._applyCompositionForce = apply
        return controller

    return _make


async def test_turning_it_on_applies_and_starts_watching(preference):
    controller = preference(force_composition=True)

    await controller.applyCompositionPreference_async()

    assert controller.applies == 1


async def test_turning_it_off_stops_watching_before_releasing(preference):
    """The other order would let the watcher re-assert the value the release
    just cleared."""
    controller = preference(force_composition=False, applied=True)

    await controller.applyCompositionPreference_async()

    assert (controller.cancels, controller.writes) == (1, [False])
    assert controller._composition_applied is False


async def test_turning_off_something_that_was_never_applied_writes_nothing(preference):
    controller = preference(force_composition=False, applied=False)

    await controller.applyCompositionPreference_async()

    assert controller.cancels == 1, "the watcher still has to go"
    assert controller.writes == []


async def test_an_unknown_applied_state_is_released_to_be_safe(preference):
    controller = preference(force_composition=False, applied=None)

    await controller.applyCompositionPreference_async()

    assert controller.writes == [False]


async def test_the_watcher_is_started_once_and_then_left_alone(bare_controller):
    """_applyCompositionForce is called from every start and from the panel;
    a second task would double every write."""
    controller = bare_controller(force_composition=True, _composition_watch_task=None,
                                 _composition_applied=True,
                                 _composition_verify_remaining=0)

    async def reconcile():
        pass

    async def forever():
        await asyncio.Event().wait()

    controller._reconcileCompositionForce = reconcile
    controller._watchCompositionForce = forever

    await controller._applyCompositionForce()
    task = controller._composition_watch_task
    await controller._applyCompositionForce()

    assert controller._composition_watch_task is task
    await controller._cancelCompositionWatch()
    assert controller._composition_watch_task is None


async def test_a_watcher_that_ended_is_replaced(bare_controller):
    """It ends by itself when Sunshine dies; a later start has to get a new
    one rather than a finished task that watches nothing."""
    controller = bare_controller(force_composition=True, _composition_watch_task=None,
                                 _composition_applied=True,
                                 _composition_verify_remaining=0)

    async def reconcile():
        pass

    async def finished():
        return

    controller._reconcileCompositionForce = reconcile
    controller._watchCompositionForce = finished

    await controller._applyCompositionForce()
    spent = controller._composition_watch_task
    await asyncio.sleep(0)
    assert spent.done()

    await controller._applyCompositionForce()

    assert controller._composition_watch_task is not spent
    await controller._cancelCompositionWatch()


async def test_cancelling_without_a_watcher_is_harmless(bare_controller):
    controller = bare_controller(_composition_watch_task=None)

    await controller._cancelCompositionWatch()


async def test_a_release_the_panel_asked_for_that_failed_is_not_recorded(preference):
    """Recording it would make the next toggle skip the retry and leave
    gamescope compositing with nothing streaming."""
    controller = preference(force_composition=False, applied=True, write_succeeds=False)

    await controller.applyCompositionPreference_async()

    assert controller._composition_applied is True
