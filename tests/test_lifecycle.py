"""Stopping Sunshine, and the start/stop symmetry.

Keeping Sunshine running is what this plugin is for, which makes a stop that
half-worked worse than one that failed outright: main.py keys the user's run
intent off the return value, so a stop that reports success while Sunshine is
still up strands the panel in a state the user cannot get out of.

Two things have to happen on every stop path, including the one where Sunshine
turns out not to be running at all: the composition watcher is cancelled, and
the gamescope override is released.
"""

import pytest

import sunshine as sunshine_module
from sunshine import SunshineController


@pytest.fixture
def make_controller(logger):
    """A controller whose Sunshine stops after `running_for` further checks.

    Everything it does lands in `events` in order, because half of what this
    file checks is sequence rather than outcome.
    """

    class FakeController(SunshineController):
        def __init__(self, running=True, running_for=0, force_composition=False,
                     composition_applied=None, composition_release_ok=True):
            self.logger = logger
            self.force_composition = force_composition
            self._composition_applied = composition_applied
            self._composition_release_ok = composition_release_ok
            self._running = running
            self._running_for = running_for
            self.events = []
            self.commands = []
            self.contexts = []
            self.running_checks = 0

        async def isSunshineRunning_async(self):
            self.running_checks += 1
            if not self._running or self._running_for <= 0:
                return False
            self._running_for -= 1
            return True

        async def _cancelCompositionWatch(self):
            self.events.append("cancel-watch")

        async def setCompositionForce_async(self, enabled):
            self.events.append(f"composition:{enabled}")
            return self._composition_release_ok

        def _run_and_check(self, args, context=None):
            self.events.append("kill")
            self.commands.append(list(args))
            self.contexts.append(context)
            return True

    return FakeController


@pytest.fixture
def slept():
    """How long each retry asked to wait, recorded rather than dropped.

    The step length times the retry count is what decides whether a Deck under
    load gets its five seconds, so the duration is as much the subject as the
    number of retries is.
    """
    return []


@pytest.fixture
def stop(slept):
    """Runs stop_async without spending the real retry delay.

    Its own MonkeyPatch context rather than the test's: asyncio.sleep is the
    global one and may not stay replaced past the call, and undo() on the
    shared recorder would also roll back conftest's sys.modules stubs.
    """

    async def _stop(controller):
        real_sleep = sunshine_module.asyncio.sleep

        async def instant(seconds):
            slept.append(seconds)
            await real_sleep(0)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(sunshine_module.asyncio, "sleep", instant)
            return await controller.stop_async()

    return _stop


# --- the stop itself ---------------------------------------------------------

async def test_stopping_an_already_stopped_sunshine_succeeds(make_controller, stop):
    controller = make_controller(running=False)

    assert await stop(controller) is True
    assert "kill" not in controller.events, "nothing to kill, so nothing may be killed"


async def test_a_running_sunshine_is_killed_through_flatpak(make_controller, stop):
    controller = make_controller(running=True, running_for=1)

    assert await stop(controller) is True
    assert controller.commands == [
        ["flatpak", "kill", SunshineController.SunshineFlatpakAppId]
    ]
    assert controller.contexts == ["killing Sunshine via flatpak"], \
        "the context is what a failed kill says in the log"


async def test_a_slow_teardown_is_waited_out_rather_than_failed(make_controller, stop, logger):
    """flatpak reports the instance gone a moment after the kill returns, so a
    stop that gives up immediately would report failure on a healthy system."""
    controller = make_controller(running=True, running_for=5)

    assert await stop(controller) is True
    assert "Sunshine process not ended yet. Checking again in 0.25 seconds" in logger.infos, \
        "a slow stop has to be visible in the log"


async def test_a_sunshine_that_never_stops_reports_failure(make_controller, stop, logger):
    controller = make_controller(running=True, running_for=999)

    assert await stop(controller) is False
    assert "Aborting wait for Sunshine process to end." in logger.errors


async def test_the_wait_is_bounded_at_twenty_retries(make_controller, stop, slept):
    """One check at the gate before the kill, then twenty in the retry loop.

    Pinned exactly rather than as an upper bound: the point of the number is
    that it is finite AND that it gives teardown enough time, and a loose "<= 21"
    would still pass if the loop gave up after the first round.
    """
    controller = make_controller(running=True, running_for=999)

    await stop(controller)

    assert controller.running_checks == 21
    assert slept == [0.25] * 19, "quarter-second steps, so about five seconds in all"


# --- the composition override ------------------------------------------------
# Releasing it spawns su/xprop, which fails noisily on systems where that does
# not work - so it may only happen when the override could have been applied.

async def test_no_override_is_released_when_the_toggle_is_off(make_controller, stop):
    controller = make_controller(running=False, force_composition=False)

    await stop(controller)

    assert not any(e.startswith("composition") for e in controller.events)


async def test_no_override_is_released_when_it_is_known_not_to_be_applied(make_controller, stop):
    controller = make_controller(running=False, force_composition=True,
                                 composition_applied=False)

    await stop(controller)

    assert not any(e.startswith("composition") for e in controller.events)


async def test_an_applied_override_is_released_and_remembered(make_controller, stop):
    controller = make_controller(running=False, force_composition=True,
                                 composition_applied=True)

    await stop(controller)

    assert "composition:False" in controller.events
    assert controller._composition_applied is False


async def test_an_override_of_unknown_state_is_released_too(make_controller, stop):
    """We may have applied it, so releasing is the safe side of the guess."""
    controller = make_controller(running=False, force_composition=True,
                                 composition_applied=None)

    await stop(controller)

    assert "composition:False" in controller.events


async def test_a_failed_release_is_not_recorded_as_done(make_controller, stop):
    """Recording it would make the next stop skip the release entirely, and the
    override would stay on a machine that is no longer streaming."""
    controller = make_controller(running=False, force_composition=True,
                                 composition_applied=True, composition_release_ok=False)

    await stop(controller)

    assert controller._composition_applied is True


# --- ordering ----------------------------------------------------------------

async def test_the_watcher_is_cancelled_before_the_override_is_released(make_controller, stop):
    """Otherwise the watcher re-asserts the value the release just cleared."""
    controller = make_controller(running=True, running_for=1, force_composition=True,
                                 composition_applied=True)

    await stop(controller)

    events = controller.events
    assert events.index("cancel-watch") < events.index("composition:False")


async def test_the_watcher_is_cancelled_even_when_sunshine_is_not_running(make_controller, stop):
    """It would otherwise keep re-asserting the override against a Sunshine
    that is gone."""
    controller = make_controller(running=False, force_composition=True,
                                 composition_applied=True)

    await stop(controller)

    assert "cancel-watch" in controller.events
    assert "composition:False" in controller.events
