"""The csrfRestartPending flow in main.py.

`editing_ready` tells the panel whether the Web UI can be opened for editing.
It must reflect whether the *running* Sunshine instance enforces an allowance
for the current LAN origin - and an instance reads its config once, at start.
So the ground truth is what the config said when that instance came up, not
what it says now, and not who wrote the entry.

The case this exists for: a user whose Sunshine had been running since before
the plugin ever wrote an allowance saw the "restart to edit" hint forever,
while another user with a surviving instance and a loaded entry saw it wrongly.
"""
import types

import pytest

from sunshine import SunshineController

# The real matching rather than a copy of it: a second implementation here
# would keep passing against semantics the production one no longer has.
origin_matches_any = SunshineController._originMatchesAny


class FakeController:
    """Sunshine reduced to what this flow can observe.

    conf_origins is the file; loaded_origins is what the running instance read
    when it started. Keeping them apart is the whole point - collapse them into
    one list and the bug this file covers becomes untestable.
    """

    WebUiPort = 47990

    def __init__(self):
        self.running = False
        self.lan_ip = "192.168.1.38"
        self.conf_origins = []
        self.loaded_origins = []
        self.update_fails = False
        # Every previously_managed it was handed: the value itself is a
        # contract between main.py and the controller, checked in the section
        # "what the controller is handed".
        self.managed_seen = []

    def getLanIp(self):
        return self.lan_ip

    def origin(self):
        return f"https://{self.lan_ip}:{self.WebUiPort}" if self.lan_ip else None

    async def isSunshineRunning_async(self):
        return self.running

    async def isCsrfOriginAllowed_async(self, origin):
        return origin_matches_any(origin, self.conf_origins)

    async def ensureCsrfAllowedOrigin_async(self, previously_managed):
        self.managed_seen.append(previously_managed)
        origin = self.origin()
        if not origin:
            return previously_managed, False
        if (previously_managed and previously_managed != origin
                and previously_managed in self.conf_origins):
            self.conf_origins.remove(previously_managed)
        added_now = not origin_matches_any(origin, self.conf_origins)
        if added_now:
            self.conf_origins.append(origin)
        return (origin if origin in self.conf_origins else ""), added_now

    async def start_async(self):
        if not self.running:
            self.running = True
            self.loaded_origins = list(self.conf_origins)
        return True

    async def stop_async(self):
        self.running = False
        return True

    async def updateSunshine_async(self):
        if self.update_fails:
            return False          # a failed stop leaves the instance untouched
        await self.stop_async()
        return await self.start_async()

    def truly_editable(self):
        """What the panel's hint should be measured against."""
        return self.running and origin_matches_any(self.origin(), self.loaded_origins)


@pytest.fixture
def controller():
    return FakeController()


@pytest.fixture
def plugin(load_main, controller):
    from conftest import FakeSettingsManager

    sunshine = types.ModuleType("sunshine")
    sunshine.SunshineController = FakeController
    main = load_main(sunshine)
    instance = main.Plugin()
    instance.sunshineController = controller
    instance.settingManager = FakeSettingsManager()
    return instance


async def assert_hint_matches_truth(plugin, controller):
    """The one assertion this file is about, in both directions."""
    info = await plugin.get_web_ui_info()
    assert info["editing_ready"] == controller.truly_editable(), (
        f"panel says {info['editing_ready']}, instance says {controller.truly_editable()}"
    )
    return info


async def simulate_plugin_load(plugin):
    """The autostart branch of _main, where lastRunState was "start"."""
    await plugin._start_sunshine(record_intent=False)


async def test_fresh_start_is_ready(plugin, controller):
    await plugin.start_sunshine()
    info = await assert_hint_matches_truth(plugin, controller)
    assert info["editing_ready"] is True


async def test_surviving_instance_with_loaded_entry_shows_no_hint(plugin, controller):
    """The reported false positive: plugin updated, settings fresh, Sunshine up
    the whole time with the entry already in its loaded config."""
    controller.conf_origins = ["https://192.168.1.38:47990"]
    controller.loaded_origins = ["https://192.168.1.38:47990"]
    controller.running = True

    await simulate_plugin_load(plugin)

    info = await assert_hint_matches_truth(plugin, controller)
    assert info["editing_ready"] is True


async def test_surviving_instance_without_entry_keeps_the_hint(plugin, controller):
    controller.running = True

    await simulate_plugin_load(plugin)

    info = await assert_hint_matches_truth(plugin, controller)
    assert info["editing_ready"] is False


async def test_restart_heals_an_instance_that_predates_the_entry(plugin, controller):
    controller.running = True
    await simulate_plugin_load(plugin)

    await plugin.stop_sunshine()
    await plugin.start_sunshine()

    info = await assert_hint_matches_truth(plugin, controller)
    assert info["editing_ready"] is True


async def test_a_portless_user_entry_covers_the_origin(plugin, controller):
    controller.conf_origins = ["https://192.168.1.38"]
    controller.loaded_origins = ["https://192.168.1.38"]
    controller.running = True

    await simulate_plugin_load(plugin)

    info = await assert_hint_matches_truth(plugin, controller)
    assert info["editing_ready"] is True
    assert controller.conf_origins == ["https://192.168.1.38"], "nothing should be appended"


async def test_an_ip_change_brings_the_hint_back(plugin, controller):
    await plugin.start_sunshine()
    controller.lan_ip = "10.0.0.7"

    info = await assert_hint_matches_truth(plugin, controller)
    assert info["editing_ready"] is False


async def test_restart_after_an_ip_change_replaces_the_stale_entry(plugin, controller):
    await plugin.start_sunshine()
    controller.lan_ip = "10.0.0.7"

    await plugin.stop_sunshine()
    await plugin.start_sunshine()

    await assert_hint_matches_truth(plugin, controller)
    assert controller.conf_origins == ["https://10.0.0.7:47990"]


async def test_an_update_restarts_sunshine_and_clears_the_hint(plugin, controller):
    await plugin.start_sunshine()
    controller.lan_ip = "10.0.0.8"

    await plugin.update_sunshine()

    info = await assert_hint_matches_truth(plugin, controller)
    assert info["editing_ready"] is True


async def test_a_failed_update_leaves_the_hint_honest(plugin, controller):
    """The instance keeps running with its old config, so the hint must stay."""
    await plugin.start_sunshine()
    controller.lan_ip = "10.0.0.9"
    controller.update_fails = True

    await plugin.update_sunshine()

    info = await assert_hint_matches_truth(plugin, controller)
    assert info["editing_ready"] is False


async def test_without_a_lan_ip_nothing_is_ready_and_nothing_crashes(plugin, controller):
    controller.lan_ip = None
    await plugin.start_sunshine()

    info = await plugin.get_web_ui_info()

    assert info["editing_ready"] is False
    assert info["ip"] is None


async def test_an_entry_removed_from_the_file_brings_the_hint_back(plugin, controller):
    await plugin.start_sunshine()
    controller.conf_origins = []

    info = await plugin.get_web_ui_info()

    assert info["editing_ready"] is False


async def test_restart_re_adds_an_entry_the_user_removed(plugin, controller):
    await plugin.start_sunshine()
    controller.conf_origins = []

    await plugin.stop_sunshine()
    await plugin.start_sunshine()

    info = await assert_hint_matches_truth(plugin, controller)
    assert info["editing_ready"] is True


# --- the flag itself, not just the hint it produces ---------------------------
# editing_ready reads csrfRestartPending through `not ...`, so an absent flag
# and a False one look the same from the panel. These two pin the write, which
# is what a later run and the next instance actually see.

async def test_a_start_that_brought_sunshine_up_clears_the_pending_flag(plugin, controller):
    controller.running = True
    await simulate_plugin_load(plugin)
    assert plugin.settingManager.getSetting("csrfRestartPending") is True, \
        "precondition: the surviving instance has not loaded the new entry"

    await plugin.stop_sunshine()
    await plugin.start_sunshine()

    assert plugin.settingManager.getSetting("csrfRestartPending") is False


async def test_a_successful_update_clears_the_pending_flag(plugin, controller):
    """The update is a restart, so the new instance has the entry - and the
    flag has to say so even though nothing about the config changed here."""
    controller.running = True
    await simulate_plugin_load(plugin)
    assert plugin.settingManager.getSetting("csrfRestartPending") is True

    await plugin.update_sunshine()

    assert plugin.settingManager.getSetting("csrfRestartPending") is False


# --- what the controller is handed --------------------------------------------

async def test_a_first_run_says_that_nothing_is_managed_yet(plugin, controller):
    """csrfManagedOrigin is the entry a previous run added, and the controller
    removes it from the file when the IP has changed since. Before the first
    start there is no such entry, and the documented way to say so is the empty
    string - which is also the only value the plugin ever stores there.
    """
    await plugin.start_sunshine()

    assert controller.managed_seen == [""]


async def test_a_later_run_hands_back_what_the_first_one_stored(plugin, controller):
    """The other half: the value that went into the settings file has to come
    out of it again, or the stale entry is never cleaned up."""
    await plugin.start_sunshine()
    stored = plugin.settingManager.getSetting("csrfManagedOrigin")
    assert stored == "https://192.168.1.38:47990", "precondition: it was stored"

    await plugin.stop_sunshine()
    await plugin.start_sunshine()

    assert controller.managed_seen == ["", stored]
