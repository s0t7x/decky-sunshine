"""Version and update reporting for Sunshine.

Every version string flatpak prints comes from the remote's cached appstream
data, while "is there an update" comes from the ostree summary. The panel only
refreshed the appstream behind its "Check for updates" button, so on open it
labelled a real update with the version from a cache left over from the
previous release - and it read as a rebuild of what was already installed.

A) _getInstalledSunshineInfo - parse version and origin out of `flatpak info`
B) _getRemoteUpdateInfo - an update must be reported even without a label
C) getSunshineVersionInfo - refresh the appstream exactly when the label looks
   stale, scoped to the origin remote, and never when nothing would be shown
"""
import pytest

from sunshine import SunshineController


# Real `flatpak info --system dev.lizardbyte.app.Sunshine` output from a Deck
INFO_OUTPUT = """
Sunshine - GameStream host for Moonlight

          ID: dev.lizardbyte.app.Sunshine
         Ref: app/dev.lizardbyte.app.Sunshine/x86_64/stable
        Arch: x86_64
      Branch: stable
     Version: 2026.516.143833
     License: GPL-3.0-only
      Origin: flathub
  Collection: org.flathub.Stable
Installation: system
   Installed: 107.8 MB
     Runtime: org.freedesktop.Platform/x86_64/24.08
      Commit: 62e90ef28d2c760d77e85233e1c5754c29f56e430b726947cdd79867915901e2
"""

# `flatpak remote-ls --app --updates --system --columns=application,version`,
# once with cached appstream data and once without
REMOTE_LS_WITH_VERSIONS = """com.heroicgameslauncher.hgl            v2.22.3
dev.lizardbyte.app.Sunshine            2026.914.233613
org.mozilla.firefox                    156.0
"""
REMOTE_LS_WITHOUT_VERSIONS = """com.heroicgameslauncher.hgl
dev.lizardbyte.app.Sunshine
org.mozilla.firefox
"""


@pytest.fixture
def make_controller(logger):
    """Answers the two flatpak queries from a script and records every command."""

    class FakeController(SunshineController):
        def __init__(self, info=INFO_OUTPUT, remote_ls=(REMOTE_LS_WITH_VERSIONS,)):
            self.logger = logger
            self.calls = []
            self.contexts = []
            self._info = info
            self._remote_ls = list(remote_ls)

        def _run_and_capture_stdout(self, args, context=None):
            self.calls.append(list(args))
            self.contexts.append(context)
            if args[1] == "info":
                return self._info
            if args[1] == "remote-ls":
                # Later calls repeat the last scripted answer
                return self._remote_ls.pop(0) if len(self._remote_ls) > 1 else self._remote_ls[0]
            raise AssertionError(f"unexpected command {args}")

        def _run_and_check(self, args, context=None):
            self.calls.append(list(args))
            self.contexts.append(context)
            return True

        def appstream_refreshes(self):
            return [c for c in self.calls if c[:3] == ["flatpak", "update", "--appstream"]]

    return FakeController


# --- A) parsing `flatpak info` ------------------------------------------------

def test_the_installed_version_and_origin_are_parsed(make_controller):
    info = make_controller()._getInstalledSunshineInfo()

    assert info.get("version") == "2026.516.143833"
    assert info.get("origin") == "flathub"
    assert set(info) == {"version", "origin"}, \
        "the header line carries no colon, and the other fields are none of our business"


def test_a_sunshine_that_is_not_installed_yields_nothing(make_controller):
    assert make_controller(info=None)._getInstalledSunshineInfo() == {}


def test_a_value_containing_a_colon_is_not_cut_in_half(make_controller):
    """flatpak prints `key: value`, and the values are free text - the Ref and
    the Commit are already URL-shaped. Splitting on the last colon instead of
    the first would silently truncate them."""
    controller = make_controller(info="      Origin: flathub:stable\n")

    assert controller._getInstalledSunshineInfo() == {"origin": "flathub:stable"}


def test_the_info_query_matches_the_install_scope(make_controller):
    """The install path is `flatpak install --system`, so the query has to be
    --system too or it looks at a different installation."""
    controller = make_controller()

    controller._getInstalledSunshineInfo()

    assert controller.calls == [
        ["flatpak", "info", "--system", SunshineController.SunshineFlatpakAppId],
    ]
    assert controller.contexts == ["getting Sunshine version info"]


# --- B) reading the update list -----------------------------------------------

def test_an_update_and_its_label_are_reported(make_controller):
    assert make_controller()._getRemoteUpdateInfo() == (True, "2026.914.233613")


def test_the_update_query_asks_for_exactly_these_two_columns(make_controller):
    """--updates is what makes the answer the pending updates rather than the
    whole remote, and the two columns are what the parser splits on: drop the
    version column and every update comes back unlabelled, drop --app and
    runtimes appear alongside the applications."""
    controller = make_controller()

    controller._getRemoteUpdateInfo()

    assert controller.calls == [
        ["flatpak", "remote-ls", "--app", "--updates", "--system",
         "--columns=application,version"],
    ]
    assert controller.contexts == ["checking for Sunshine updates"]


def test_without_an_origin_every_remote_is_refreshed(make_controller, logger):
    """`flatpak info` did not say where Sunshine came from, so the refresh
    cannot be scoped - and the line has to say that rather than print None."""
    controller = make_controller(info="Version: 2026.516.143833\n",
                                 remote_ls=(REMOTE_LS_WITHOUT_VERSIONS,
                                            REMOTE_LS_WITH_VERSIONS))

    controller.getSunshineVersionInfo()

    assert ("The update is labelled with no version - refreshing the appstream data "
            "of every remote before trusting that") in logger.infos
    assert controller.appstream_refreshes() == [["flatpak", "update", "--appstream"]], \
        "and the command carries no remote either"


def test_an_update_is_reported_even_without_a_label(make_controller):
    """The regression: no appstream cache means no version column, and the
    update is real regardless."""
    controller = make_controller(remote_ls=(REMOTE_LS_WITHOUT_VERSIONS,))

    assert controller._getRemoteUpdateInfo() == (True, None)


def test_absence_from_the_list_means_up_to_date(make_controller):
    controller = make_controller(remote_ls=("org.mozilla.firefox  156.0\n",))

    assert controller._getRemoteUpdateInfo() == (False, None)


def test_a_failed_command_means_up_to_date(make_controller):
    assert make_controller(remote_ls=(None,))._getRemoteUpdateInfo() == (False, None)


def test_an_id_that_merely_contains_ours_is_not_a_match(make_controller):
    controller = make_controller(remote_ls=("dev.lizardbyte.app.SunshineExtra  1.0\n",))

    available, _ = controller._getRemoteUpdateInfo()

    assert available is False


# --- C) the appstream refresh decision ----------------------------------------

def test_a_fresh_label_needs_no_refresh(make_controller, logger):
    controller = make_controller()

    result = controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes() == []
    assert logger.infos == [], "and says nothing about a refresh it did not do"
    assert result == {"current_version": "2026.516.143833", "update_available": True,
                      "update_version": "2026.914.233613"}


def test_a_stale_label_triggers_one_scoped_refresh(make_controller):
    """The state this exists for: the cache is stale, so the first read labels the update
    with the installed version; after the refresh the real one appears."""
    controller = make_controller(remote_ls=("dev.lizardbyte.app.Sunshine  2026.516.143833\n",
                                            REMOTE_LS_WITH_VERSIONS))

    result = controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes() == [
        ["flatpak", "update", "--appstream", "flathub"]]
    assert result["update_version"] == "2026.914.233613"


def test_a_missing_label_gets_the_same_treatment(make_controller):
    controller = make_controller(remote_ls=(REMOTE_LS_WITHOUT_VERSIONS,
                                            REMOTE_LS_WITH_VERSIONS))

    result = controller.getSunshineVersionInfo()

    assert len(controller.appstream_refreshes()) == 1
    assert result["update_version"] == "2026.914.233613"


def test_no_pending_update_means_no_refresh(make_controller):
    """Never pay for the refresh when nothing would be shown, whatever the
    label says."""
    controller = make_controller(remote_ls=("org.mozilla.firefox  156.0\n",))

    result = controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes() == []
    assert (result["update_available"], result["update_version"]) == (False, None)


def test_a_genuine_rebuild_stays_an_update_and_refreshes_only_once(make_controller):
    """Same version on both sides even after the refresh."""
    controller = make_controller(remote_ls=("dev.lizardbyte.app.Sunshine  2026.516.143833\n",))

    result = controller.getSunshineVersionInfo()

    assert len(controller.appstream_refreshes()) == 1
    assert (result["update_available"], result["update_version"]) == (True, "2026.516.143833")


def test_an_update_survives_a_label_that_is_still_missing_after_the_refresh(make_controller):
    controller = make_controller(remote_ls=(REMOTE_LS_WITHOUT_VERSIONS,))

    result = controller.getSunshineVersionInfo()

    assert (result["update_available"], result["update_version"]) == (True, None)


def test_a_sunshine_that_is_not_installed_reports_nothing(make_controller):
    """The fresh-setup state, which must not blow up."""
    controller = make_controller(info=None, remote_ls=("",))

    assert controller.getSunshineVersionInfo() == {
        "current_version": None, "update_available": False, "update_version": None}


def test_an_unknown_origin_falls_back_to_every_remote(make_controller):
    """Rather than skipping the refresh and keeping the stale label."""
    controller = make_controller(info="Version: 1.0\n",
                                 remote_ls=("dev.lizardbyte.app.Sunshine\n",
                                            REMOTE_LS_WITH_VERSIONS))

    controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes()[0] == ["flatpak", "update", "--appstream"]


def test_the_refresh_is_visible_in_the_log(make_controller, logger):
    """It is the one branch that cannot be seen from the panel, so it has to be
    readable in a log a user attaches to a bug report."""
    controller = make_controller(remote_ls=(REMOTE_LS_WITHOUT_VERSIONS,
                                            REMOTE_LS_WITH_VERSIONS))

    controller.getSunshineVersionInfo()

    assert ("The update is labelled with no version - refreshing the appstream data "
            "of flathub before trusting that") in logger.infos
    assert "refreshing Flatpak appstream data" in controller.contexts
