"""What the plugin does when the loader starts it (_main).

This is the path behind "Sunshine is back after a reboot": the loader calls
_main once, and everything the plugin needs for the rest of its life is set up
here - the controller, the settings, the stored credentials, the composition
preference - before the auto-start decides whether Sunshine comes up.

Three things make it worth its own file. It is the only place that builds its
own collaborators instead of getting them handed in; it is the only start that
runs with record_intent=False, so a failure here must not rewrite what the user
asked for; and it is unreachable from the panel, so anything that goes wrong
here is only ever visible in the log - so what it says is checked here too.
"""
import os
import types

import pytest

from conftest import StartStopController


class FakeController(StartStopController):
    """The controller as _main uses it, plus the start path it ends in."""

    def __init__(self, logger=None):
        super().__init__()
        self.logger = logger
        self.authHeader = None
        self.force_composition = None
        self.dependencies_ok = True
        self.environment_logged = 0

    async def logEnvironment_async(self):
        self.environment_logged += 1

    async def ensureDependencies_async(self):
        return self.dependencies_ok


@pytest.fixture
def make_plugin(load_main, monkeypatch, tmp_path):
    """A Plugin whose _main can run: the settings directory the loader would
    provide is the one variable _main reads straight out of the environment."""
    from conftest import FakeSettingsManager

    monkeypatch.setenv("DECKY_PLUGIN_SETTINGS_DIR", str(tmp_path))
    sunshine = types.ModuleType("sunshine")
    sunshine.SunshineController = FakeController
    main = load_main(sunshine)

    def _make(controller=None, settings=None, **stored):
        """:param settings: a settings manager to hand in, or None to let
                            _main build its own (the production case)"""
        plugin = main.Plugin()
        # Assigned only when given: what Plugin.__init__ leaves behind is what
        # _main's "is None" guards look at, and overwriting it with another
        # None would hide whether they look at the right thing.
        if controller is not None:
            plugin.sunshineController = controller
        if settings is None and stored:
            settings = FakeSettingsManager()
        if settings is not None:
            for key, value in stored.items():
                settings.setSetting(key, value)
            settings.writes.clear()
            plugin.settingManager = settings
        return plugin

    return _make


# --- the collaborators _main builds ------------------------------------------

async def test_a_load_without_anything_prepared_builds_both_collaborators(make_plugin, log):
    plugin = make_plugin()

    await plugin._main()

    assert isinstance(plugin.sunshineController, FakeController)
    assert plugin.sunshineController.logger is not None, \
        "the controller logs through decky's logger, so it has to get one"
    assert plugin.settingManager is not None
    # The version is the first thing a bug report needs, and the two settings
    # lines bracket the read that is the most likely thing to hang or throw.
    assert "Decky Sunshine version: test" in log.infos
    assert "Reading settings..." in log.infos
    assert "Read settings" in log.infos


async def test_a_controller_that_is_already_there_is_kept(make_plugin):
    """A second _main must not replace the controller the first one built -
    it carries the state of the Sunshine that is running right now."""
    controller = FakeController()
    plugin = make_plugin(controller, settings=None)

    await plugin._main()
    await plugin._main()

    assert plugin.sunshineController is controller
    assert controller.environment_logged == 2, \
        "the second load logged nothing - a reload has to say what it came up against"


async def test_the_settings_go_where_the_loader_said(make_plugin, tmp_path):
    """The name decides the file, and the file is the one _migration moves out
    of the old location - a different name silently starts from scratch."""
    plugin = make_plugin()

    await plugin._main()

    assert plugin.settingManager.name == "decky-sunshine"
    assert plugin.settingManager.settings_directory == str(tmp_path)


async def test_the_settings_are_read_from_disk_once(make_plugin):
    plugin = make_plugin()

    await plugin._main()
    settings = plugin.settingManager
    await plugin._main()

    assert plugin.settingManager is settings


# --- dependencies ------------------------------------------------------------

async def test_missing_dependencies_abort_the_load(make_plugin, log):
    """Without bwrap or Sunshine itself there is nothing to start, and going on
    would only produce a second, less useful error."""
    controller = FakeController()
    controller.dependencies_ok = False
    plugin = make_plugin(controller, lastRunState="start")

    await plugin._main()

    assert controller.start_calls == 0
    assert "Couldn't ensure dependencies" in log.errors
    assert "Decky Sunshine loaded" not in log.infos


# --- credentials -------------------------------------------------------------

async def test_credentials_from_a_fresh_install_are_stored(make_plugin, log):
    """A controller that comes back from ensureDependencies_async with an
    authHeader has just installed Sunshine with default credentials - the only
    moment they can be captured."""
    controller = FakeController()
    controller.authHeader = "Basic c3VuOnNoaW5l"
    plugin = make_plugin(controller, lastRunState="stop")

    await plugin._main()

    assert plugin.settingManager.getSetting("lastAuthHeader") == "Basic c3VuOnNoaW5l"
    assert "Stored newly created credentials" in log.infos


async def test_stored_credentials_are_restored_into_the_controller(make_plugin, log):
    controller = FakeController()
    plugin = make_plugin(controller, lastRunState="stop",
                         lastAuthHeader="Basic c3RvcmVk")

    await plugin._main()

    assert controller.authHeader == "Basic c3RvcmVk"
    assert "Setting auth header from settings" in log.infos


async def test_a_load_without_any_credentials_carries_on(make_plugin, log):
    """The panel then asks for them. Nothing here may stop Sunshine from
    starting: it runs fine, it just cannot be paired from the panel yet."""
    controller = FakeController()
    plugin = make_plugin(controller, lastRunState="start")

    await plugin._main()

    assert "No lastAuthHeader found in settings" in log.errors
    assert controller.start_calls == 1


async def test_stored_credentials_are_not_overwritten_by_an_empty_header(make_plugin):
    controller = FakeController()
    plugin = make_plugin(controller, lastRunState="stop",
                         lastAuthHeader="Basic c3RvcmVk")

    await plugin._main()

    assert plugin.settingManager.writes_of("lastAuthHeader") == []


# --- the composition preference ----------------------------------------------

async def test_the_composition_preference_reaches_the_controller(make_plugin):
    """It is applied by the controller's next start_async, which is the
    auto-start a few lines further down - so it has to be set before it."""
    controller = FakeController()
    plugin = make_plugin(controller, lastRunState="start", forceComposition=True)

    await plugin._main()

    assert controller.force_composition is True


async def test_an_unset_composition_preference_is_off(make_plugin):
    controller = FakeController()
    plugin = make_plugin(controller, lastRunState="stop")

    await plugin._main()

    assert controller.force_composition is False


# --- the auto-start ----------------------------------------------------------

async def test_a_recorded_start_brings_sunshine_back(make_plugin, log):
    controller = FakeController()
    plugin = make_plugin(controller, lastRunState="start")

    await plugin._main()

    assert controller.start_calls == 1
    assert plugin._crash_watch_task is not None, "and it is watched from then on"
    assert "Starting Sunshine" in log.infos
    await plugin._cancel_crash_watch()


async def test_a_fresh_install_starts_sunshine_too(make_plugin):
    """No recorded intent at all: a user who just installed the plugin expects
    it to do the thing it is for."""
    controller = FakeController()
    plugin = make_plugin(controller)

    await plugin._main()

    assert controller.start_calls == 1
    await plugin._cancel_crash_watch()


async def test_a_recorded_stop_is_respected(make_plugin, log):
    controller = FakeController()
    plugin = make_plugin(controller, lastRunState="stop")

    await plugin._main()

    assert controller.start_calls == 0
    assert plugin._crash_watch_task is None, "nothing is running, so nothing is watched"
    assert "Starting Sunshine" not in log.infos
    assert "Decky Sunshine loaded" in log.infos, \
        "the load finished - it just did not start anything"


async def test_the_auto_start_does_not_rewrite_the_intent(make_plugin):
    controller = FakeController()
    plugin = make_plugin(controller, lastRunState="start")

    await plugin._main()

    assert plugin.settingManager.writes_of("lastRunState") == []
    await plugin._cancel_crash_watch()


# --- the settings log --------------------------------------------------------
# It is the first thing in a bug report, so it has to be both complete and
# safe to paste in public.

def test_the_auth_header_is_logged_by_length_only(make_plugin, log):
    plugin = make_plugin(FakeController(),
                         lastAuthHeader="Basic c3VwZXJzZWNyZXQ=")

    plugin._log_settings()

    lines = "\n".join(log.infos)
    assert "c3VwZXJzZWNyZXQ" not in lines, "the header is a credential"
    assert "lastAuthHeader: [SET - 22 characters]" in lines


def test_an_empty_auth_header_is_not_reported_as_set(make_plugin, log):
    plugin = make_plugin(FakeController(), lastAuthHeader="")

    plugin._log_settings()

    assert any("lastAuthHeader: [EMPTY]" in line for line in log.infos)


def test_other_settings_are_logged_with_their_value(make_plugin, log):
    plugin = make_plugin(FakeController(), lastRunState="start",
                         csrfManagedOrigin="")

    plugin._log_settings()

    lines = "\n".join(log.infos)
    assert "Current settings:" in log.infos
    assert "lastRunState: 'start'" in lines
    assert "csrfManagedOrigin: [EMPTY]" in lines


def test_no_settings_at_all_is_said_plainly(make_plugin, log):
    """The state after a fresh install, and the one a report is most likely to
    be about - "Settings: [EMPTY]" says more than an absent section."""
    from conftest import FakeSettingsManager

    plugin = make_plugin(FakeController(), settings=FakeSettingsManager())

    plugin._log_settings()

    assert log.infos == ["Settings: [EMPTY]"]


def test_a_settings_manager_that_throws_is_logged_rather_than_raised(make_plugin, log):
    """Logging the settings is a courtesy; letting it raise would take the
    whole load - and Sunshine with it - down over a log line."""
    from conftest import FakeSettingsManager

    class Broken(FakeSettingsManager):
        @property
        def settings(self):
            raise RuntimeError("no settings file")

        @settings.setter
        def settings(self, value):
            pass

    plugin = make_plugin(FakeController(), settings=Broken())

    plugin._log_settings()      # must not raise

    assert any("Error logging settings" in line for line in log.errors)


# --- the loader's other two callbacks ----------------------------------------

async def test_unloading_leaves_a_marker_in_the_log(make_plugin, log):
    """Deliberately all it does: Sunshine keeps running when the plugin is
    unloaded, and the line is what tells a report's reader that it was."""
    await make_plugin(FakeController())._unload()

    assert log.infos == ["Decky Sunshine unloaded"]


async def test_the_migration_names_the_old_settings_file(make_plugin, decky_stub):
    """decky.migrate_settings moves the file from before Decky managed the
    settings directory. A wrong path here loses the user's settings quietly -
    the plugin simply comes up as a fresh install."""
    migrated = []
    decky_stub.migrate_settings = migrated.append

    await make_plugin(FakeController())._migration()

    assert migrated == [os.path.join(decky_stub.DECKY_HOME, "settings", "decky-sunshine.json")]
