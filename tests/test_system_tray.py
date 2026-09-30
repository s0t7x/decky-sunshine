"""SunshineController.ensureSystemTrayDisabled and its place in start_async.

Under the plugin Sunshine never has a system tray: it runs as root, with no
desktop session to put one in. Up to 2026.914 a tray that failed to start only
cost a warning. From 2026.929 on, Sunshine shuts itself down when its tray loop
ends - and a tray that never started ends it at once, so every start failed
before the Web UI came up. `system_tray = disabled` keeps Sunshine from trying.

The key belongs to the user's config, though. A missing key gets the plugin's
value; a key the user set is theirs, and one that enables the tray is only
reported, with what it will cost them.

Truthiness follows Sunshine's own parser (config.cpp, to_bool): true, yes,
enable, enabled, on, or any value containing a 1.
"""
import pytest


ADDED = ("Set system_tray = disabled in sunshine.conf: Sunshine runs without a desktop "
         "here, and from 2026.929 on it shuts down when its tray cannot start")
ENABLED = ("system_tray is enabled in sunshine.conf. Sunshine runs without a desktop here, "
           "so its tray cannot start, and from 2026.929 on Sunshine then shuts down right "
           "after starting. Set system_tray = disabled, or remove the line and the plugin "
           "will set it.")
UNREADABLE = "Could not check system_tray in sunshine.conf"


@pytest.fixture
def config_path(tmp_path):
    """Nested on purpose - the plugin has to create the directory itself."""
    return tmp_path / "conf" / "sunshine.conf"


@pytest.fixture
def make_controller(bare_controller, config_path):
    def _make(path=None):
        return bare_controller(SunshineConfigPath=str(path if path is not None else config_path))

    return _make


@pytest.fixture
def write_config(config_path):
    def _write(content):
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(content)

    return _write


def test_a_missing_key_is_added_and_the_rest_is_kept(make_controller, config_path,
                                                     write_config, logger):
    write_config("encoder = vaapi\ncsrf_allowed_origins = https://192.168.1.50:47990\n")

    make_controller().ensureSystemTrayDisabled()

    assert config_path.read_text() == (
        "encoder = vaapi\n"
        "csrf_allowed_origins = https://192.168.1.50:47990\n"
        "system_tray = disabled\n"
    )
    assert logger.infos == [ADDED], \
        "a change to the user's config has to show up in the log"


def test_a_missing_config_is_created_with_the_key(make_controller, config_path):
    """Before Sunshine's first start there is no config yet - and that first
    start is exactly the one that must not end in a shutdown."""
    make_controller().ensureSystemTrayDisabled()

    assert config_path.read_text() == "system_tray = disabled\n"


def test_a_commented_out_key_counts_as_missing(make_controller, config_path,
                                               write_config):
    """Sunshine skips a line that starts with '#', so the tray is on."""
    write_config("# system_tray = disabled\n")

    make_controller().ensureSystemTrayDisabled()

    assert config_path.read_text() == "# system_tray = disabled\nsystem_tray = disabled\n"


def test_an_equals_sign_in_the_value_does_not_hide_the_key(make_controller, config_path,
                                                         write_config):
    """Sunshine splits at the first '=' and keeps a trailing comment as part of
    the value - so this line disables the tray, and it is the user's."""
    write_config("system_tray = disabled # was: system_tray = enabled\n")

    make_controller().ensureSystemTrayDisabled()

    assert config_path.read_text() == "system_tray = disabled # was: system_tray = enabled\n"


@pytest.mark.parametrize("line", [
    "system_tray = enabled",
    "system_tray = true",
    "system_tray = yes",
    "system_tray = on",
    "system_tray = enable",
    "system_tray = 1",
    "system_tray=enabled",
    # Sunshine means to compare case-insensitively; its lowering is a no-op
    # today (the lambda's result is discarded). Warning here errs on the side
    # of telling the user too much.
    "system_tray = Enabled",
])
def test_an_enabled_tray_is_left_alone_and_warned_about(make_controller, config_path,
                                                        write_config, logger, line):
    write_config(f"encoder = vaapi\n{line}\n")

    make_controller().ensureSystemTrayDisabled()

    assert config_path.read_text() == f"encoder = vaapi\n{line}\n", \
        "the user set it - overriding them silently is not ours to do"
    assert logger.warnings == [ENABLED], \
        "the warning has to say what it costs, not just that the key is set"


@pytest.mark.parametrize("value", ["disabled", "false", "no", "off", "0"])
def test_a_disabled_tray_needs_nothing(make_controller, config_path, write_config,
                                       logger, value):
    write_config(f"system_tray = {value}\n")

    make_controller().ensureSystemTrayDisabled()

    assert config_path.read_text() == f"system_tray = {value}\n"
    assert logger.warnings == []
    assert logger.infos == []


def test_an_unwritable_config_is_logged_not_raised(make_controller, tmp_path, logger):
    """A directory where the file should be: every read and write fails. The
    start must go on regardless - the worst case is then a Sunshine that tries
    its tray, which is no worse than not starting at all."""
    blocked = tmp_path / "sunshine.conf"
    blocked.mkdir()

    make_controller(path=blocked).ensureSystemTrayDisabled()

    assert logger.raised_with_traceback(UNREADABLE)
