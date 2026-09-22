"""The user's run intent (lastRunState) in main.py.

lastRunState is the one setting that survives a reboot and decides whether
Sunshine comes back: _main starts it when the setting says "start" (or is
absent, the fresh-install case), and the crash watchdog stops watching the
moment it says anything else. Everything the plugin does to Sunshine therefore
has to leave that setting in the state the *user* asked for - not in the state
the last attempt happened to end in.

The distinction that carries all of it is record_intent:

  * True  - the user asked for this (start_sunshine, restart_sunshine,
            stop_sunshine), so the outcome becomes the intent.
  * False - the plugin is only carrying out an intent that is already
            recorded (the auto-start on load, the crash watchdog), so a
            failure must not silently turn the auto-start off.

Read the intent back rather than trusting the call to have happened: several
paths write the value that was already there, which is why the settings stub
records its writes.

Each of these paths also says in the log what it did, and that line is checked
along with the setting.
"""
import types

import pytest

from conftest import StartStopController


FakeController = StartStopController


@pytest.fixture
def make_plugin(load_main):
    from conftest import FakeSettingsManager

    sunshine = types.ModuleType("sunshine")
    sunshine.SunshineController = FakeController
    main = load_main(sunshine)

    def _make(controller, last_run_state):
        """:param last_run_state: the recorded intent, or None for a fresh install"""
        plugin = main.Plugin()
        plugin.sunshineController = controller
        plugin.settingManager = FakeSettingsManager()
        if last_run_state is not None:
            plugin.settingManager.setSetting("lastRunState", last_run_state)
            plugin.settingManager.writes.clear()
        return plugin

    return _make


# --- the intent the user expressed -------------------------------------------
# Each of these starts from the opposite intent, so "the setting says X
# afterwards" can only mean it was written - not that it was already there.

async def test_a_manual_start_records_the_intent(make_plugin, log):
    plugin = make_plugin(FakeController(running=False), last_run_state="stop")

    assert await plugin.start_sunshine() is True
    assert plugin.settingManager.getSetting("lastRunState") == "start"
    assert "Starting sunshine..." in log.infos
    assert "Sunshine started" in log.infos


async def test_a_failed_manual_start_records_that_sunshine_is_down(make_plugin, log):
    """The user tried and it did not come up. Recording "start" here would make
    every later boot retry a start that is known not to work."""
    plugin = make_plugin(FakeController(running=False, start_succeeds=False),
                         last_run_state="start")

    assert await plugin.start_sunshine() is False
    assert plugin.settingManager.getSetting("lastRunState") == "stop"
    assert "Couldn't start Sunshine" in log.infos


async def test_a_restart_records_the_intent(make_plugin, log):
    """A restart is a start the user asked for, whatever the setting said
    before - the panel offers it while Sunshine is running."""
    plugin = make_plugin(FakeController(running=True), last_run_state="stop")

    assert await plugin.restart_sunshine() is True
    assert plugin.settingManager.getSetting("lastRunState") == "start"
    assert "Restarting sunshine..." in log.infos
    assert "Sunshine restarted" in log.infos


async def test_a_restart_that_cannot_bring_sunshine_back_records_the_outcome(make_plugin, log):
    """The stop worked, so Sunshine really is down now - recording "start"
    here would leave the panel offering a Stop for something that is gone, and
    the line has to name the half that failed rather than the restart as a
    whole."""
    plugin = make_plugin(FakeController(running=True, start_succeeds=False),
                         last_run_state="start")

    assert await plugin.restart_sunshine() is False
    assert plugin.settingManager.getSetting("lastRunState") == "stop"
    assert "Couldn't start Sunshine again after stopping it" in log.infos


async def test_a_stop_records_the_intent(make_plugin, log):
    plugin = make_plugin(FakeController(running=True), last_run_state="start")

    assert await plugin.stop_sunshine() is True
    assert plugin.settingManager.getSetting("lastRunState") == "stop"
    assert "Stopping sunshine..." in log.infos
    assert "Sunshine stopped" in log.infos


async def test_a_failed_stop_records_that_sunshine_is_still_wanted(make_plugin, log):
    """Sunshine is still up, so "start" is the honest intent - and it has to be
    written, not merely left alone: the value is the same either way, but only
    a write keeps a later `lastRunState = stop` from a half-finished stop.
    """
    plugin = make_plugin(FakeController(running=True, stop_succeeds=False),
                         last_run_state="start")

    assert await plugin.stop_sunshine() is False
    assert plugin.settingManager.writes_of("lastRunState") == ["start"]
    assert "Couldn't stop Sunshine" in log.infos


# --- the intent the plugin only carries out ----------------------------------

async def test_the_auto_start_on_load_records_nothing(make_plugin):
    """_main's auto-start runs with record_intent=False. A start that fails
    there - no display attached yet, a broken installation - must not turn the
    auto-start off for good."""
    plugin = make_plugin(FakeController(running=False, start_succeeds=False),
                         last_run_state="start")

    assert await plugin._start_sunshine(record_intent=False) is False
    assert plugin.settingManager.writes_of("lastRunState") == []
    assert plugin.settingManager.getSetting("lastRunState") == "start"


async def test_a_successful_auto_start_records_nothing_either(make_plugin):
    """Not just the failure path: nothing about an automatic start is news
    about what the user wants."""
    plugin = make_plugin(FakeController(running=False), last_run_state="start")

    assert await plugin._start_sunshine(record_intent=False) is True
    assert plugin.settingManager.writes_of("lastRunState") == []
