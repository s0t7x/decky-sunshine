"""The calls the panel makes into main.py, other than start/stop.

Everything here is a thin layer over the controller, which is exactly why it is
worth pinning: the panel has no other way in, and a wrong key, a dropped call
or a swallowed return value looks like a controller bug from the outside.

A) settings passthrough and the composition toggle
B) credentials and pairing
C) the version info, whose only job beyond passing the answer on is to keep the
   five-second poll from filling the log with unchanged numbers

Every one of these calls also leaves a line in the log, and that line is the
only account of a call the panel made - so it is checked with the call.
"""
import types

import pytest

from conftest import FakeController as BaseController


class FakeController(BaseController):
    """Records what it was asked to do and answers from scripted values."""

    def __init__(self, logger=None):
        super().__init__()
        self.logger = logger
        self.force_composition = None
        self.composition_applied = 0
        self.credentials_valid = True
        self.credentials = {"username": "sunshine", "password": "pass"}
        self.pair_result = True
        self.pair_calls = []
        self.version_info = None

    async def applyCompositionPreference_async(self):
        self.composition_applied += 1

    async def areCredentialsValid_async(self):
        return self.credentials_valid

    def setCredentials(self, username, password):
        return f"Basic {username}:{password}"

    def getCredentials(self):
        return self.credentials

    async def pair_async(self, pin, client_name):
        self.pair_calls.append((pin, client_name))
        return self.pair_result

    async def getSunshineVersionInfo_async(self):
        return self.version_info


@pytest.fixture
def make_plugin(load_main):
    from conftest import FakeSettingsManager

    sunshine = types.ModuleType("sunshine")
    sunshine.SunshineController = FakeController
    main = load_main(sunshine)

    def _make(controller=None, **stored):
        plugin = main.Plugin()
        plugin.sunshineController = controller if controller is not None else FakeController()
        plugin.settingManager = FakeSettingsManager()
        for key, value in stored.items():
            plugin.settingManager.setSetting(key, value)
        plugin.settingManager.writes.clear()
        return plugin

    return _make


# --- A) settings and the composition toggle ----------------------------------

async def test_a_setting_written_from_the_panel_reaches_the_settings_file(make_plugin):
    plugin = make_plugin()

    await plugin.set_setting("someKey", "someValue")

    assert plugin.settingManager.writes == [("someKey", "someValue")]


async def test_a_setting_read_from_the_panel_falls_back_to_the_default(make_plugin):
    plugin = make_plugin(someKey="stored")

    assert await plugin.get_setting("someKey", "fallback") == "stored"
    assert await plugin.get_setting("otherKey", "fallback") == "fallback"


async def test_the_composition_toggle_is_persisted_and_handed_on(make_plugin, log):
    """Both, because they answer different questions: the setting survives a
    reboot, the controller attribute is what the next start_async reads."""
    controller = FakeController()
    plugin = make_plugin(controller)

    assert await plugin.set_force_composition(True) is True

    assert plugin.settingManager.getSetting("forceComposition") is True
    assert controller.force_composition is True
    assert "forceComposition set to True" in log.infos


async def test_toggling_it_while_sunshine_runs_takes_effect_immediately(make_plugin):
    """Otherwise the user has to restart Sunshine to see the docked capture
    fix - which is the thing they just turned on to fix what they are seeing."""
    controller = FakeController()
    controller.running = True
    plugin = make_plugin(controller)

    await plugin.set_force_composition(True)

    assert controller.composition_applied == 1


async def test_toggling_it_while_sunshine_is_down_spawns_no_xprop(make_plugin):
    """Releasing or asserting the override spawns su/xprop, which fails noisily
    where that does not work - and there is no stream to fix anyway."""
    controller = FakeController()
    plugin = make_plugin(controller)

    await plugin.set_force_composition(False)

    assert controller.composition_applied == 0


async def test_the_toggle_reads_back_off_when_it_was_never_set(make_plugin):
    assert await make_plugin().get_force_composition() is False


async def test_the_toggle_reads_back_what_was_stored(make_plugin):
    plugin = make_plugin(forceComposition=True)

    assert await plugin.get_force_composition() is True


# --- B) credentials and pairing ----------------------------------------------

async def test_the_credentials_check_is_passed_through(make_plugin):
    controller = FakeController()
    controller.credentials_valid = False
    plugin = make_plugin(controller)

    assert await plugin.are_credentials_valid() is False


async def test_an_unchanged_credentials_state_is_logged_once(make_plugin, log):
    """Same reason as the running-state poll: the panel asks every five
    seconds while it is open."""
    plugin = make_plugin()

    for _ in range(3):
        await plugin.are_credentials_valid()

    assert [line for line in log.infos if "Credentials valid state changed" in line] == [
        "Credentials valid state changed: unknown → True"]


async def test_a_change_in_the_credentials_state_is_logged(make_plugin, log):
    controller = FakeController()
    plugin = make_plugin(controller)
    await plugin.are_credentials_valid()

    controller.credentials_valid = False
    await plugin.are_credentials_valid()

    assert "Credentials valid state changed: True → False" in log.infos


async def test_credentials_that_can_no_longer_be_checked_read_as_unknown(make_plugin, log):
    """areCredentialsValid_async answers None while Sunshine is down, which is
    not the same as "wrong" - and a line reading "True → None" would send the
    reader of a bug report looking for a bug in the plugin."""
    controller = FakeController()
    plugin = make_plugin(controller)
    await plugin.are_credentials_valid()

    controller.credentials_valid = None
    await plugin.are_credentials_valid()

    assert "Credentials valid state changed: True → unknown" in log.infos


async def test_new_credentials_are_stored_and_verified(make_plugin, log):
    controller = FakeController()
    plugin = make_plugin(controller)

    result = await plugin.set_credentials("user", "secret")

    assert plugin.settingManager.getSetting("lastAuthHeader") == "Basic user:secret"
    assert result is True, "the panel shows the outcome of the check, not of the write"
    assert "Setting credentials..." in log.infos
    assert "Credentials set" in log.infos


async def test_incomplete_credentials_are_refused_before_anything_is_written(make_plugin, log):
    """An empty field would otherwise overwrite working credentials with a
    header that cannot authenticate."""
    plugin = make_plugin()

    assert await plugin.set_credentials("user", "") is None
    assert await plugin.set_credentials("", "secret") is None
    assert plugin.settingManager.writes == []
    assert "Invalid username or password provided for setting credentials" in log.infos


async def test_credentials_are_handed_to_the_panel(make_plugin, log):
    controller = FakeController()
    plugin = make_plugin(controller)

    assert await plugin.get_credentials() == controller.credentials
    assert "Getting credentials..." in log.infos
    assert "Credentials found" in log.infos, "and not the credentials themselves"


async def test_absent_credentials_come_back_as_nothing(make_plugin, log):
    controller = FakeController()
    controller.credentials = None
    plugin = make_plugin(controller)

    assert await plugin.get_credentials() is None
    assert "No credentials found" in log.infos


async def test_pairing_passes_pin_and_name_through(make_plugin, log):
    controller = FakeController()
    plugin = make_plugin(controller)

    assert await plugin.pair("1234", "Living Room TV") is True
    assert controller.pair_calls == [("1234", "Living Room TV")]
    assert "Trying to pair with PIN 1234 for client Living Room TV" in log.infos
    assert "Pairing returned True" in log.infos


async def test_a_failed_pairing_is_reported_as_such(make_plugin, log):
    controller = FakeController()
    controller.pair_result = False
    plugin = make_plugin(controller)

    assert await plugin.pair("1234", "TV") is False
    assert "Pairing returned False" in log.infos


async def test_pairing_without_a_pin_or_a_name_never_reaches_sunshine(make_plugin, log):
    """Sunshine answers a half-filled pairing request with an error the panel
    cannot explain; refusing here keeps the message honest."""
    controller = FakeController()
    plugin = make_plugin(controller)

    assert await plugin.pair("", "TV") is False
    assert await plugin.pair("1234", "") is False
    assert controller.pair_calls == []
    assert "No pin or client name provided for pairing" in log.infos


# --- C) the version info -----------------------------------------------------

VERSION = {"current_version": "2026.516.143833", "update_available": True,
           "update_version": "2026.914.233613"}


async def test_the_version_info_is_passed_through(make_plugin):
    controller = FakeController()
    controller.version_info = VERSION
    plugin = make_plugin(controller)

    assert await plugin.get_sunshine_version_info() == VERSION


async def test_unchanged_version_info_is_logged_once(make_plugin, log):
    controller = FakeController()
    controller.version_info = VERSION
    plugin = make_plugin(controller)

    for _ in range(3):
        await plugin.get_sunshine_version_info()

    assert len([line for line in log.infos if "version info changed" in line]) == 2, \
        "once for the installed version, once for the update - and then never again"


async def test_a_new_update_is_logged(make_plugin, log):
    controller = FakeController()
    controller.version_info = VERSION
    plugin = make_plugin(controller)
    await plugin.get_sunshine_version_info()
    log.infos.clear()

    controller.version_info = dict(VERSION, update_version="2026.920.101010")
    await plugin.get_sunshine_version_info()

    assert any("2026.914.233613 → 2026.920.101010" in line for line in log.infos)


async def test_a_missing_version_reads_as_unknown_rather_than_none(make_plugin, log):
    """Sunshine is installed but the appstream cache carries no label yet. That
    is not an update appearing, so it is not worth a line - and once the label
    does turn up, the line must name it rather than print None."""
    controller = FakeController()
    controller.version_info = {"current_version": "1.0", "update_available": False,
                               "update_version": None}
    plugin = make_plugin(controller)

    await plugin.get_sunshine_version_info()

    assert any("Sunshine version info changed: unknown \u2192 1.0" in line
               for line in log.infos)
    assert not any("update version info changed" in line for line in log.infos)

    controller.version_info = dict(controller.version_info, update_version="2.0")
    await plugin.get_sunshine_version_info()

    assert any("update version info changed: unknown \u2192 2.0" in line
               for line in log.infos)


async def test_a_version_that_was_unknown_and_turns_up_is_named(make_plugin, log):
    """The other half of the same wording: the remembered side falls back to
    "unknown" too, so the line is readable in both directions."""
    controller = FakeController()
    controller.version_info = dict(VERSION, current_version=None)
    plugin = make_plugin(controller)
    await plugin.get_sunshine_version_info()
    log.infos.clear()

    controller.version_info = dict(VERSION, current_version="1.0")
    await plugin.get_sunshine_version_info()

    assert any("Sunshine version info changed: unknown \u2192 1.0" in line
               for line in log.infos)


async def test_a_version_that_disappears_is_named_unknown(make_plugin, log):
    """Sunshine uninstalled from elsewhere while the panel is open. The line
    has to read "1.0 \u2192 unknown" - "1.0 \u2192 None" reads like a bug in the
    plugin rather than like Sunshine being gone."""
    controller = FakeController()
    controller.version_info = dict(VERSION, current_version="1.0")
    plugin = make_plugin(controller)
    await plugin.get_sunshine_version_info()
    log.infos.clear()

    controller.version_info = dict(VERSION, current_version=None)
    await plugin.get_sunshine_version_info()

    assert any("Sunshine version info changed: 1.0 \u2192 unknown" in line
               for line in log.infos)


async def test_no_version_info_at_all_is_not_remembered(make_plugin):
    """flatpak failed, Sunshine is not installed - whatever the reason, an
    empty answer must not become the baseline the next comparison uses."""
    controller = FakeController()
    plugin = make_plugin(controller)

    assert await plugin.get_sunshine_version_info() is None
    assert plugin._last_version_info is None
