"""Version and update reporting for Sunshine.

Every version string flatpak prints comes from the remote's cached appstream
data, while "is there an update" comes from the ostree summary. The panel only
refreshed the appstream behind its "Check for updates" button, so on open it
labelled a real update with the version from a cache left over from the
previous release - and it read as a rebuild of what was already installed.

A) _getInstalledSunshineInfo - parse version and origin out of `flatpak info`
B) _getRemoteUpdateInfo - an update must be reported even without a label
C) getSunshineVersionInfo - refresh the appstream only while an update is
   pending and the data is a day old, scoped to the origin remote. Going by
   the label instead ("missing, or the installed version") refreshed on every
   panel open for as long as a rebuild went uninstalled - and Sunshine's
   rebuilds have waited months for the next release.
"""
import os

import pytest

import sunshine as sunshine_module
from sunshine import SunshineController


# What the clock reads during a test, so that ages are exact
NOW = 1_800_000_000.0
HOUR = 60 * 60


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


def timestamp_path(root, origin="flathub"):
    """Where flatpak records a remote's last appstream refresh - its own
    `.timestamp`, which it rewrites on every refresh that succeeds."""
    return os.path.join(root, "appstream", origin, os.uname().machine, ".timestamp")


def write_timestamp(root, age, origin="flathub"):
    path = timestamp_path(root, origin)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    os.utime(path, (NOW - age, NOW - age))


@pytest.fixture
def make_controller(logger, tmp_path, monkeypatch):
    """Answers the two flatpak queries from a script and records every command.
    The appstream data was refreshed an hour ago unless a test says otherwise
    (None: never), and a refresh behaves like flatpak's: it rewrites the
    timestamp."""
    monkeypatch.setattr(sunshine_module.time, "time", lambda: NOW)

    class FakeController(SunshineController):
        FlatpakSystemPath = str(tmp_path)

        def __init__(self, info=INFO_OUTPUT, remote_ls=(REMOTE_LS_WITH_VERSIONS,),
                     appstream_age=HOUR, refresh_succeeds=True, refresh_writes_timestamp=True):
            self.logger = logger
            self.calls = []
            self.contexts = []
            self._info = info
            self._remote_ls = list(remote_ls)
            self._refresh_succeeds = refresh_succeeds
            self._refresh_writes_timestamp = refresh_writes_timestamp
            if appstream_age is not None:
                write_timestamp(tmp_path, appstream_age)

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
            if self._refresh_succeeds and self._refresh_writes_timestamp:
                write_timestamp(tmp_path, 0, origin=args[3] if len(args) > 3 else "flathub")
            return self._refresh_succeeds

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

def test_data_refreshed_within_the_day_is_trusted(make_controller, logger):
    controller = make_controller(appstream_age=24 * HOUR - 1)

    result = controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes() == []
    assert logger.infos == [], "and says nothing about a refresh it did not do"
    assert result == {"current_version": "2026.516.143833", "update_available": True,
                      "update_version": "2026.914.233613"}


def test_data_a_day_old_is_refreshed_once_and_scoped_to_the_origin(make_controller):
    """A day, as flatpak's own FLATPAK_APPSTREAM_TTL: the label may name a
    release that has since been superseded - here the refresh brings the
    real one."""
    controller = make_controller(appstream_age=24 * HOUR,
                                 remote_ls=("dev.lizardbyte.app.Sunshine  2026.906.222525\n",
                                            REMOTE_LS_WITH_VERSIONS))

    result = controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes() == [
        ["flatpak", "update", "--appstream", "flathub"]]
    assert "refreshing Flatpak appstream data" in controller.contexts
    assert result["update_version"] == "2026.914.233613"


def test_the_refresh_is_visible_in_the_log(make_controller, logger):
    """It is the one branch that cannot be seen from the panel, so it has to be
    readable in a log a user attaches to a bug report. The age is rounded to
    the nearest hour: seven days and 31 minutes are 169 hours."""
    controller = make_controller(appstream_age=7 * 24 * HOUR + 31 * 60)

    controller.getSunshineVersionInfo()

    assert logger.infos == [
        "The update is labelled 2026.914.233613; refreshing the appstream data "
        "of flathub, which is 169 hours old"]


def test_data_that_was_never_refreshed_is_refreshed(make_controller, logger):
    """No timestamp means no appstream refresh has ever succeeded here - and
    after this one the timestamp is there, so there is nothing to warn about."""
    controller = make_controller(appstream_age=None, remote_ls=(REMOTE_LS_WITHOUT_VERSIONS,
                                                                REMOTE_LS_WITH_VERSIONS))

    result = controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes() == [
        ["flatpak", "update", "--appstream", "flathub"]]
    assert logger.infos == [
        "The update is labelled with no version; refreshing the appstream data "
        "of flathub, which is of unknown age"]
    assert logger.warnings == []
    assert result["update_version"] == "2026.914.233613"


def test_a_timestamp_from_the_future_counts_as_outdated(make_controller):
    """As flatpak treats it: a clock that was once ahead would otherwise keep
    the data from ever being refreshed again."""
    controller = make_controller(appstream_age=-1)

    controller.getSunshineVersionInfo()

    assert len(controller.appstream_refreshes()) == 1


def test_a_timestamp_written_this_second_is_fresh(make_controller):
    controller = make_controller(appstream_age=0)

    controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes() == []


def test_a_rebuild_does_not_refresh_while_the_data_is_fresh(make_controller):
    """Same version on both sides - the label is right, and refreshing on every
    panel open until the rebuild is installed would cost the most exactly when
    nothing changes."""
    controller = make_controller(remote_ls=("dev.lizardbyte.app.Sunshine  2026.516.143833\n",))

    result = controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes() == []
    assert (result["update_available"], result["update_version"]) == (True, "2026.516.143833")


def test_a_missing_label_does_not_refresh_fresh_data(make_controller):
    """Data refreshed an hour ago that has no label would have none after
    another refresh either."""
    controller = make_controller(remote_ls=(REMOTE_LS_WITHOUT_VERSIONS,))

    result = controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes() == []
    assert (result["update_available"], result["update_version"]) == (True, None)


def test_no_pending_update_means_no_refresh(make_controller):
    """Never pay for the refresh when nothing would be shown, however old the
    data is."""
    controller = make_controller(appstream_age=None, remote_ls=("org.mozilla.firefox  156.0\n",))

    result = controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes() == []
    assert (result["update_available"], result["update_version"]) == (False, None)


def test_an_update_survives_a_label_that_is_still_missing_after_the_refresh(make_controller):
    controller = make_controller(appstream_age=None, remote_ls=(REMOTE_LS_WITHOUT_VERSIONS,))

    result = controller.getSunshineVersionInfo()

    assert (result["update_available"], result["update_version"]) == (True, None)


def test_an_update_survives_a_second_read_that_fails(make_controller):
    """The second read is only there for the label. Whether an update exists
    was answered by the first, and a second read that fails - the network
    gone in between - would answer no."""
    controller = make_controller(appstream_age=None, remote_ls=(REMOTE_LS_WITH_VERSIONS, None))

    result = controller.getSunshineVersionInfo()

    assert result["update_available"] is True


def test_a_sunshine_that_is_not_installed_reports_nothing(make_controller):
    """The fresh-setup state, which must not blow up."""
    controller = make_controller(info=None, remote_ls=("",))

    assert controller.getSunshineVersionInfo() == {
        "current_version": None, "update_available": False, "update_version": None}


def test_without_an_origin_every_remote_is_refreshed(make_controller, logger):
    """`flatpak info` did not say where Sunshine came from, so there is no
    timestamp to go by and the refresh cannot be scoped - and the line has to
    say that rather than print None."""
    controller = make_controller(info="Version: 2026.516.143833\n")

    controller.getSunshineVersionInfo()

    assert controller.appstream_refreshes() == [["flatpak", "update", "--appstream"]]
    assert logger.infos == [
        "The update is labelled 2026.914.233613; refreshing the appstream data "
        "of every remote, which is of unknown age"]
    assert logger.warnings == [], "no remote, so no timestamp to have expected"


def test_a_timestamp_still_missing_after_a_refresh_is_a_warning(make_controller, logger, tmp_path):
    """flatpak writes it on every refresh that succeeds, so its absence means
    the path is wrong for this system - and every panel open with an update
    pending will refresh again."""
    controller = make_controller(appstream_age=None, refresh_writes_timestamp=False)

    controller.getSunshineVersionInfo()

    assert logger.warnings == [
        f"Refreshed the appstream data of flathub, but there is no timestamp at "
        f"{timestamp_path(str(tmp_path))} - every check with an update pending will "
        f"refresh it again"]


def test_a_failed_refresh_is_no_reason_to_expect_a_timestamp(make_controller, logger):
    controller = make_controller(appstream_age=None, refresh_succeeds=False)

    controller.getSunshineVersionInfo()

    assert logger.warnings == []
