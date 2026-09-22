"""The crash watchdog and the restart path in main.py.

Bringing Sunshine back when it dies on its own is the other half of "keep it
running", and it has three ways to go wrong: not restarting at all, restarting
against the user's wishes, and restarting forever into something that cannot
come up.

A) _watch_for_crash - restart a Sunshine that went away by itself, never one
   the user stopped, and never without a limit.
B) restart/stop/update - every intentional gap in Sunshine's uptime has to be
   invisible to the watchdog, and the user's run intent (lastRunState) has to
   survive a failed automatic restart.
C) The wake-up wiring - the panel's poll and the watchdog's wait have to be the
   same event, which the virtual clock in A cannot show.

Nothing here is visible from the panel while it happens, so the log is the
only account of it there will ever be - and it is checked as such.
"""
import asyncio
import types

import pytest

from conftest import StartStopController


class FakeController(StartStopController):
    """Adds the update path, which stops and starts in one go, and defaults to
    a Sunshine that is already up - the state the watchdog exists for."""

    def __init__(self, running=True):
        super().__init__(running=running)
        self.update_succeeds = True

    async def updateSunshine_async(self):
        await self.stop_async()
        if not self.update_succeeds:
            return False
        return await self.start_async()


class FlakyController(FakeController):
    """Fails its first start and succeeds from then on."""

    async def start_async(self):
        self.start_calls += 1
        self.start_succeeds = True
        self.running = self.start_calls > 1
        return self.running


@pytest.fixture
def main_module(load_main):
    sunshine = types.ModuleType("sunshine")
    sunshine.SunshineController = FakeController
    return load_main(sunshine)


@pytest.fixture
def make_plugin(main_module):
    from conftest import FakeSettingsManager

    def _make(controller, last_run_state="start"):
        """:param last_run_state: the recorded intent, or None for a fresh install"""
        plugin = main_module.Plugin()
        plugin.sunshineController = controller
        plugin.settingManager = FakeSettingsManager()
        if last_run_state is not None:
            plugin.settingManager.setSetting("lastRunState", last_run_state)
        return plugin

    return _make


# --- A) the watchdog loop, on a virtual clock --------------------------------

class StopLoop(Exception):
    """Raised in place of the wait that would start tick max_ticks + 1."""


class Clock:
    """Drives _watch_for_crash without spending real time.

    Both ways of waiting are recorded. "wait" is the interruptible one
    (asyncio.wait_for on the wake-up event, used while nothing has failed),
    "sleep" is the plain backoff after a failed restart - telling them apart is
    what makes "only failed starts back off" checkable at all.

    Ticks listed in wake_at simulate the panel nudging the watchdog awake. That
    the watchdog really waits on the event the nudge sets is a separate
    question, checked in section C; this class only decides when a wake-up
    happens.
    """

    def __init__(self, max_ticks, on_tick=None, wake_at=()):
        self.now = 0.0
        self.waits = []                  # (kind, seconds actually spent)
        self.max_ticks = max_ticks
        self.on_tick = on_tick
        self.wake_at = set(wake_at)

    @property
    def durations(self):
        return [seconds for _, seconds in self.waits]

    @property
    def kinds(self):
        return [kind for kind, _ in self.waits]

    async def _advance(self, kind, seconds):
        if len(self.waits) >= self.max_ticks:
            raise StopLoop
        tick = len(self.waits) + 1
        woken = kind == "wait" and tick in self.wake_at
        spent = 0.5 if woken else seconds
        self.waits.append(("woken" if woken else kind, spent))
        self.now += spent
        if self.on_tick:
            self.on_tick(tick)
        return woken

    async def sleep(self, seconds):
        await self._advance("sleep", seconds)

    async def wait_for(self, awaitable, timeout):
        awaitable.close()                # the Event.wait() coroutine never runs
        if not await self._advance("wait", timeout):
            raise asyncio.TimeoutError


@pytest.fixture
def run_watch(main_module):
    """Runs the watchdog on a Clock.

    Its own MonkeyPatch context rather than the test's: asyncio.sleep is the
    global one and may not stay replaced past the call, and undo() on the
    shared recorder would also roll back conftest's sys.modules stubs.

    :return: "returned" if the watchdog ended by itself, "watching" if it was
             still going when the tick budget ran out.
    """

    async def _run(plugin, clock):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(asyncio, "sleep", clock.sleep)
            patch.setattr(asyncio, "wait_for", clock.wait_for)
            patch.setattr(main_module.time, "monotonic", lambda: clock.now)
            # In production the loop IS the registered task, and it checks
            # that each round: without this the watchdog would read itself as
            # retired and return after its first wait, and the restart would
            # spawn a second watchdog on top.
            plugin._crash_watch_task = asyncio.current_task()
            try:
                await plugin._watch_for_crash()
                return "returned"
            except StopLoop:
                return "watching"

    return _run


async def test_a_crashed_sunshine_is_restarted_once(make_plugin, run_watch, log):
    controller = FakeController(running=False)
    plugin = make_plugin(controller)

    outcome = await run_watch(plugin, Clock(max_ticks=3))

    assert outcome == "watching"
    assert controller.start_calls == 1
    assert controller.running
    assert "Sunshine restarted after it went away" in log.infos


async def test_no_restart_against_a_recorded_stop(make_plugin, run_watch):
    """The user stopped it, so the watchdog ends rather than fight the intent."""
    controller = FakeController(running=False)
    plugin = make_plugin(controller, last_run_state="stop")

    outcome = await run_watch(plugin, Clock(max_ticks=3))

    assert outcome == "returned"
    assert controller.start_calls == 0


async def test_restarts_are_capped_and_then_abandoned(make_plugin, run_watch, main_module, log):
    controller = FakeController(running=False)
    controller.start_succeeds = False
    plugin = make_plugin(controller)

    outcome = await run_watch(plugin, Clock(max_ticks=10))

    assert outcome == "returned"
    assert controller.start_calls == main_module.Plugin.CRASH_RESTART_LIMIT
    assert any("giving up" in line for line in log.all())
    assert "Couldn't restart Sunshine after it went away" in log.errors


async def test_a_failed_automatic_restart_keeps_the_run_intent(make_plugin, run_watch):
    """The boot-time auto-start ran with record_intent=False, so nothing may
    overwrite what the user last asked for."""
    controller = FakeController(running=False)
    controller.start_succeeds = False
    plugin = make_plugin(controller)

    await run_watch(plugin, Clock(max_ticks=10))

    assert plugin.settingManager.getSetting("lastRunState") == "start"


async def test_only_failed_starts_back_off_and_do_so_uninterruptibly(make_plugin, run_watch):
    controller = FakeController(running=False)
    controller.start_succeeds = False
    plugin = make_plugin(controller)
    clock = Clock(max_ticks=10)

    await run_watch(plugin, clock)

    assert clock.durations == [20, 40, 80, 160]
    assert clock.kinds == ["wait", "sleep", "sleep", "sleep"]


async def test_a_successful_restart_keeps_the_normal_interval(make_plugin, run_watch):
    """A restart that worked must not
    slow the next check down - the crash after it is a new event, not a retry."""
    controller = FakeController(running=False)
    plugin = make_plugin(controller)
    # Two kills with a healthy tick in between
    clock = Clock(max_ticks=4,
                  on_tick=lambda n: setattr(controller, "running", False) if n == 3 else None)

    await run_watch(plugin, clock)

    assert clock.durations == [20] * 4
    assert controller.start_calls == 2


async def test_a_recovered_restart_clears_the_backoff(make_plugin, run_watch):
    """Without this, the crash after a recovered restart would be noticed at
    80 seconds instead of the normal 20."""
    controller = FlakyController(running=False)
    plugin = make_plugin(controller)
    clock = Clock(max_ticks=4,
                  on_tick=lambda n: setattr(controller, "running", False) if n == 3 else None)

    await run_watch(plugin, clock)

    assert clock.durations == [20, 40, 20, 20]
    assert clock.kinds[:2] == ["wait", "sleep"], \
        "only a failed attempt may back off - this backed off before the first try"


async def test_a_failure_after_a_recovered_restart_backs_off_from_the_start(
        make_plugin, run_watch):
    """The mirror of the test above: there the backoff is cleared by a restart
    that worked, here the next failure has to start counting from that cleared
    state - 40 s, not the 80 s it would be if the earlier failure still counted,
    and not a counter that stopped counting at all.
    """
    controller = FakeController(running=False)
    plugin = make_plugin(controller)

    def second_crash(tick):
        if tick == 2:
            controller.running = False
            controller.start_succeeds = False

    clock = Clock(max_ticks=3, on_tick=second_crash)

    await run_watch(plugin, clock)

    assert clock.durations == [20, 20, 40]
    assert clock.kinds == ["wait", "wait", "sleep"]
    assert controller.start_calls == 3, \
        "one for the recovery, then the two the budget still allows"


async def test_a_stable_sunshine_gets_a_fresh_restart_budget(make_plugin, run_watch, log):
    """Pinned at the boundary rather than comfortably past it: 20 s per tick
    and the restart at tick 1 put the window's last second at tick 7, so the
    reset has to have happened by the crash at tick 8. One tick later and a
    `>` instead of `>=` would pass here too.
    """
    controller = FakeController(running=False)
    plugin = make_plugin(controller)
    clock = Clock(max_ticks=9,
                  on_tick=lambda n: setattr(controller, "running", False) if n == 8 else None)

    await run_watch(plugin, clock)

    lines = log.all()
    assert ("Sunshine has been stable since the last restart - resetting the restart count"
            in log.infos)
    assert controller.start_calls == 2
    assert sum(1 for line in lines if "restarting it (1/3)" in line) == 2, \
        "the second crash has to start counting from one again"


async def test_the_budget_is_not_refreshed_before_the_window_has_passed(
        make_plugin, run_watch, log):
    """The other side of the same boundary, and the reason the window is
    measured from the last restart rather than from anything else: a Sunshine
    that dies again after 100 s has not recovered, and the second crash has to
    come out of the same budget as the first.
    """
    controller = FakeController(running=False)
    plugin = make_plugin(controller)
    clock = Clock(max_ticks=7,
                  on_tick=lambda n: setattr(controller, "running", False) if n == 6 else None)

    await run_watch(plugin, clock)

    lines = log.all()
    assert not any("resetting the restart count" in line for line in lines)
    assert any("restarting it (2/3)" in line for line in lines), \
        "the budget was refreshed too early - the second crash looks like a first one"


async def test_a_healthy_sunshine_never_spends_a_budget_it_did_not_use(
        make_plugin, run_watch, log):
    """Nothing ever crashed here, so there is no restart count to reset - and
    the watchdog may not announce one. The guard is `attempts and ...`: drop
    the left half and every quiet watchdog logs a reset it never performed."""
    plugin = make_plugin(FakeController(running=True))

    await run_watch(plugin, Clock(max_ticks=10))

    assert not any("resetting the restart count" in line for line in log.all())


async def test_a_fresh_install_is_watched_like_a_recorded_start(make_plugin, run_watch):
    """No lastRunState at all is what _main also treats as "start" - a user who
    has never touched the toggle still expects Sunshine to come back."""
    controller = FakeController(running=False)
    plugin = make_plugin(controller, last_run_state=None)

    outcome = await run_watch(plugin, Clock(max_ticks=3))

    assert outcome == "watching"
    assert controller.start_calls == 1


async def test_a_nudge_from_the_panel_wakes_the_watchdog_early(make_plugin, run_watch):
    """The panel polls every 5 s and notices a gone Sunshine first, so the
    watchdog acts now rather than at the end of its 20 s interval."""
    controller = FakeController(running=False)
    plugin = make_plugin(controller)
    clock = Clock(max_ticks=1, wake_at={1})

    await run_watch(plugin, clock)

    assert clock.kinds == ["woken"]
    assert clock.now < 20
    assert controller.start_calls == 1


# --- B) the intentional gaps -------------------------------------------------

async def test_stop_cancels_the_watchdog(make_plugin):
    plugin = make_plugin(FakeController())
    plugin._ensure_crash_watch()
    task = plugin._crash_watch_task

    await plugin.stop_sunshine()

    assert plugin._crash_watch_task is None
    assert task.cancelled()


async def test_restart_bridges_the_gap_itself_and_keeps_watching(make_plugin):
    controller = FakeController()
    plugin = make_plugin(controller)
    plugin._ensure_crash_watch()

    result = await plugin.restart_sunshine()

    assert result
    assert (controller.stop_calls, controller.start_calls) == (1, 1)
    assert controller.running
    assert plugin._crash_watch_task is not None


async def test_the_old_watchdog_is_cancelled_and_a_new_one_armed(make_plugin):
    """A task that is merely "not None" can still be the old one, which
    would have restarted Sunshine into the gap the restart just made."""
    plugin = make_plugin(FakeController())
    plugin._ensure_crash_watch()
    task = plugin._crash_watch_task

    await plugin.restart_sunshine()

    assert task.cancelled()
    assert plugin._crash_watch_task is not task


async def test_a_restart_whose_stop_fails_leaves_the_instance_alone(make_plugin, log):
    controller = FakeController()
    controller.stop_succeeds = False
    plugin = make_plugin(controller)
    plugin._ensure_crash_watch()

    result = await plugin.restart_sunshine()

    assert result is False
    assert controller.start_calls == 0
    assert controller.running, "the instance that would not stop is still up"
    assert plugin._crash_watch_task is not None, "and still watched"
    assert "Couldn't stop Sunshine for the restart" in log.infos, \
        "the restart button did nothing - the reason is only ever in the log"


async def test_an_update_re_arms_the_watchdog_for_the_new_instance(make_plugin, log):
    """An update stops Sunshine on purpose - that gap is not a crash."""
    plugin = make_plugin(FakeController())
    plugin._ensure_crash_watch()
    task = plugin._crash_watch_task

    await plugin.update_sunshine()

    assert task.cancelled()
    assert plugin._crash_watch_task not in (None, task)
    assert "Updating Sunshine..." in log.infos
    assert "Sunshine updated successfully" in log.infos


async def test_a_failed_update_leaves_no_watchdog_behind(make_plugin, log):
    """Sunshine may be down afterwards, and restarting into that would fight
    whatever left it down."""
    controller = FakeController()
    controller.update_succeeds = False
    plugin = make_plugin(controller)
    plugin._ensure_crash_watch()

    await plugin.update_sunshine()

    assert plugin._crash_watch_task is None
    assert not controller.running
    assert "Couldn't update Sunshine" in log.infos


async def test_the_panel_poll_nudges_the_watchdog(make_plugin):
    """The wiring behind the early wake-up: the panel's own poll is what sets
    the event."""
    plugin = make_plugin(FakeController(running=False))
    plugin._ensure_crash_watch()
    await asyncio.sleep(0)               # let the watchdog create its event

    await plugin.is_sunshine_running()

    assert plugin._crash_watch_wakeup is not None
    assert plugin._crash_watch_wakeup.is_set()
    await plugin._cancel_crash_watch()


async def test_no_nudge_while_sunshine_is_running(make_plugin):
    plugin = make_plugin(FakeController(running=True))
    plugin._ensure_crash_watch()
    await asyncio.sleep(0)

    await plugin.is_sunshine_running()

    assert plugin._crash_watch_wakeup is not None
    assert not plugin._crash_watch_wakeup.is_set()
    await plugin._cancel_crash_watch()


async def test_a_manual_start_arms_a_new_watchdog_after_the_old_one_gave_up(make_plugin):
    """_ensure_crash_watch checks done() for exactly this: the watchdog hit its
    restart limit and ended, and the user then starts Sunshine by hand."""
    plugin = make_plugin(FakeController(running=False))

    async def finished():
        return

    plugin._crash_watch_task = asyncio.ensure_future(finished())
    await asyncio.sleep(0)
    spent = plugin._crash_watch_task
    assert spent.done(), "precondition: the old watchdog really is finished"

    await plugin.start_sunshine()

    assert plugin._crash_watch_task not in (None, spent)
    assert not plugin._crash_watch_task.done()
    await plugin._cancel_crash_watch()


async def test_a_start_while_the_watchdog_lives_does_not_arm_a_second_one(make_plugin):
    """The other half of the same guard, and the one that matters: the
    watchdog restarts Sunshine itself, and that restart calls
    _ensure_crash_watch again. A second task would double the flatpak polling
    every crash, and _cancel_crash_watch only ever holds the newest - so Stop
    would leave the older ones alive to restart Sunshine straight back up."""
    plugin = make_plugin(FakeController(running=False))
    plugin._ensure_crash_watch()
    await asyncio.sleep(0)
    watchdog = plugin._crash_watch_task
    assert not watchdog.done(), "precondition: the first watchdog is running"

    await plugin.start_sunshine()

    assert plugin._crash_watch_task is watchdog
    await plugin._cancel_crash_watch()


async def test_polling_without_a_watchdog_is_harmless(make_plugin):
    plugin = make_plugin(FakeController(running=False))

    await plugin.is_sunshine_running()   # must not raise


async def test_a_nudge_before_the_watchdog_armed_itself_is_harmless(make_plugin):
    """The window between create_task and the watchdog's first line: the task
    is there and not done, but its event does not exist yet. The panel polls
    every five seconds and lands in that window on every plugin load."""
    plugin = make_plugin(FakeController(running=False))
    plugin._ensure_crash_watch()

    plugin._nudge_crash_watch()          # must not raise

    assert plugin._crash_watch_wakeup is None
    await plugin._cancel_crash_watch()


async def test_cancelling_the_watchdog_clears_its_wake_up_handle(make_plugin):
    """Otherwise the next poll sets an event nobody waits on, and the watchdog
    started after it inherits a wake-up that was meant for its predecessor."""
    plugin = make_plugin(FakeController(running=True))
    plugin._ensure_crash_watch()
    await asyncio.sleep(0)
    assert plugin._crash_watch_wakeup is not None, "precondition: it armed itself"

    await plugin._cancel_crash_watch()

    assert plugin._crash_watch_wakeup is None


async def test_a_repeated_poll_does_not_repeat_the_log(make_plugin, log):
    """The open panel polls every five seconds. Logging each poll would bury
    everything else in the log a user attaches to a bug report - so only a
    change in the state is worth a line."""
    plugin = make_plugin(FakeController(running=True))

    for _ in range(3):
        await plugin.is_sunshine_running()

    assert [line for line in log.all() if "running state changed" in line] == [
        "Sunshine running state changed: unknown → True"]


async def test_a_change_in_the_running_state_is_logged(make_plugin, log):
    """The other half of the same line: "unknown" is only what the remembered
    side reads before the first poll, and a line that always said it would make
    every crash in a bug report look like the plugin's first look at Sunshine.
    """
    controller = FakeController(running=True)
    plugin = make_plugin(controller)
    await plugin.is_sunshine_running()

    controller.running = False
    await plugin.is_sunshine_running()

    assert "Sunshine running state changed: True → False" in log.infos


async def wait_until_armed(plugin, timeout=2.0):
    """Block until the watchdog has published its wake-up handle.

    Before that, _nudge_crash_watch is a silent no-op - a fixed sleep either
    guesses too long or, on a loaded machine, nudges nothing and the test
    fails two seconds later with an assertion that names the wrong cause.
    """
    for _ in range(int(timeout / 0.01)):
        if plugin._crash_watch_wakeup is not None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the watchdog never reached its wait")


# --- C) the wake-up is really wired up ---------------------------------------
# Section A drives the loop on a virtual clock that decides for itself when a
# wake-up happens, which leaves the connection untested: the panel's poll sets
# an event, and the watchdog has to be waiting on that same event. If it waited
# on anything else, every test above would still pass and a crash would only be
# noticed a full interval late.

async def test_a_nudge_wakes_the_watchdog_before_its_interval_elapses(make_plugin):
    controller = FakeController(running=True)
    plugin = make_plugin(controller)
    # Far longer than this test waits, so reacting at all can only be the nudge
    plugin.CRASH_WATCH_INTERVAL = 30

    checks = []
    real_check = controller.isSunshineRunning_async

    async def counting_check():
        checks.append(1)
        return await real_check()

    controller.isSunshineRunning_async = counting_check
    plugin._ensure_crash_watch()
    try:
        await wait_until_armed(plugin)
        before = len(checks)

        plugin._nudge_crash_watch()

        # Generous: it only has to react within 2 s of a 30 s interval
        for _ in range(200):
            await asyncio.sleep(0.01)
            if len(checks) > before:
                break

        assert len(checks) > before
    finally:
        await plugin._cancel_crash_watch()


async def test_the_watchdog_goes_back_to_sleep_after_a_nudge(make_plugin):
    """Otherwise the test above would pass on a watchdog that simply polls as
    fast as it can - and this is the half that pins the wake-up event being
    cleared again. Leave it set and every later wait returns immediately.
    """
    controller = FakeController(running=True)
    plugin = make_plugin(controller)
    plugin.CRASH_WATCH_INTERVAL = 30

    checks = []
    real_check = controller.isSunshineRunning_async

    async def counting_check():
        checks.append(1)
        return await real_check()

    controller.isSunshineRunning_async = counting_check
    plugin._ensure_crash_watch()
    try:
        await wait_until_armed(plugin)
        plugin._nudge_crash_watch()
        for _ in range(200):                 # let it act on the nudge
            await asyncio.sleep(0.01)
            if checks:
                break
        settled = len(checks)

        await asyncio.sleep(0.3)

        assert len(checks) == settled, \
            "it woke again without being nudged - the wake-up was never cleared"
    finally:
        await plugin._cancel_crash_watch()


async def test_a_swallowed_cancellation_still_ends_the_watchdog(make_plugin):
    """Python 3.11's asyncio.wait_for returns the result of a wait that
    finished rather than re-raising the cancellation that arrived with it, so
    on that version a cancelled watchdog runs one more round: it restarts the
    very Sunshine the stop behind the cancel is taking down, and then reaches
    for the wake-up event that same stop has already dropped.

    The stand-in below swallows the cancellation unconditionally - when 3.11
    does it is 3.11's business, that it can happen at all is ours.
    """
    controller = FakeController(running=False)
    plugin = make_plugin(controller)
    # Long enough that the wait can only end by being cancelled
    plugin.CRASH_WATCH_INTERVAL = 30
    real_wait_for = asyncio.wait_for

    async def wait_for_that_swallows_the_cancel(awaitable, timeout):
        try:
            return await real_wait_for(awaitable, timeout)
        except asyncio.CancelledError:
            return True

    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(asyncio, "wait_for", wait_for_that_swallows_the_cancel)
            plugin._ensure_crash_watch()
            watchdog = plugin._crash_watch_task
            await wait_until_armed(plugin)

            await plugin._cancel_crash_watch()
    finally:
        # A watchdog that survives its cancellation registers a successor on
        # the way out. Reaped here, outside the stand-in, because a stray one
        # waits out the whole session rather than failing this test.
        await plugin._cancel_crash_watch()

    assert watchdog.done()
    assert controller.start_calls == 0, \
        "it restarted Sunshine while the stop that cancelled it was still running"
