"""SunshineController.ensureCsrfAllowedOrigin / isCsrfOriginAllowed.

Sunshine refuses cross-origin requests to its Web UI unless the origin is in
csrf_allowed_origins. The plugin keeps exactly one entry of its own there - the
current LAN address - and has to do that without disturbing what the user put
in the same key, and without duplicating its own entry every time it runs.

isCsrfOriginAllowed answers "would the config allow this", which is what the
panel's "Web UI editable" state is keyed off. An error while reading has to
answer "no": claiming an unreadable config allows editing is the worse failure.
"""
import os

import pytest


@pytest.fixture
def config_path(tmp_path):
    """Nested on purpose - the plugin has to create the directory itself."""
    return tmp_path / "conf" / "sunshine.conf"


@pytest.fixture
def make_controller(bare_controller, config_path):
    def _make(ip="192.168.1.50", path=None):
        return bare_controller(
            SunshineConfigPath=str(path if path is not None else config_path),
            getLanIp=lambda: ip,
        )

    return _make


@pytest.fixture
def write_config(config_path):
    def _write(content):
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(content)

    return _write


OURS = "https://192.168.1.50:47990"


def test_a_config_that_needs_nothing_is_not_rewritten(make_controller, config_path,
                                                      write_config):
    """This is the user\'s Sunshine config. Rewriting it on every start would
    reformat whatever they wrote by hand, and would fail loudly on a config
    they made read-only on purpose - for a change that is not being made."""
    write_config(f"csrf_allowed_origins = {OURS}\n")
    config_path.chmod(0o444)
    try:
        if os.access(config_path, os.W_OK):
            pytest.skip("running as root - the mode bits are ignored here")

        managed, added = make_controller().ensureCsrfAllowedOrigin(OURS)

        assert (managed, added) == (OURS, False)
    finally:
        config_path.chmod(0o644)


def test_a_stale_entry_is_removed_even_when_nothing_is_added(make_controller,
                                                             config_path, write_config):
    """The IP changed, and at the new address a portless entry the user put
    there already covers us - so there is nothing to add, and the old entry of
    ours still has to go. Without the removal being counted as a change the
    file is never rewritten and the stale address stays forever."""
    write_config("csrf_allowed_origins = https://10.0.0.7:47990,https://192.168.1.50\n")

    managed, added = make_controller().ensureCsrfAllowedOrigin("https://10.0.0.7:47990")

    assert added is False, "a user entry already covers this origin"
    assert managed == "", "and none of the entries is ours to own"
    assert config_path.read_text() == "csrf_allowed_origins = https://192.168.1.50\n"


def test_a_missing_config_is_created_with_our_entry(make_controller, config_path, logger):
    managed, added = make_controller().ensureCsrfAllowedOrigin("")

    assert (managed, added) == (OURS, True)
    assert config_path.read_text() == f"csrf_allowed_origins = {OURS}\n"
    assert (f"Allowed the Web UI origin {OURS} for CSRF-protected requests "
            "in sunshine.conf") in logger.infos, \
        "we edited the user's Sunshine config - that may not happen silently"


def test_running_twice_changes_nothing(make_controller, config_path):
    controller = make_controller()
    managed, _ = controller.ensureCsrfAllowedOrigin("")
    before = config_path.read_text()

    managed_again, added = controller.ensureCsrfAllowedOrigin(managed)

    assert config_path.read_text() == before
    assert (managed_again, added) == (OURS, False)


def test_other_keys_and_user_origins_survive(make_controller, write_config, config_path):
    write_config("encoder = vaapi\n"
                 "csrf_allowed_origins = https://myapp.local, https://custom.domain.com\n"
                 "min_log_level = 2\n")

    _, added = make_controller().ensureCsrfAllowedOrigin("")

    content = config_path.read_text()
    assert content.startswith("encoder = vaapi\n")
    assert content.endswith("min_log_level = 2\n")
    assert (f"csrf_allowed_origins = https://myapp.local,https://custom.domain.com,{OURS}"
            in content)
    assert added is True


def test_a_changed_ip_replaces_our_entry_and_leaves_the_user_theirs(
        make_controller, write_config, config_path):
    write_config("csrf_allowed_origins = https://myapp.local\n")
    managed, _ = make_controller().ensureCsrfAllowedOrigin("")

    managed_new, added = make_controller(ip="10.0.0.7").ensureCsrfAllowedOrigin(managed)

    content = config_path.read_text()
    assert "192.168.1.50" not in content, "the stale entry should be gone"
    assert "https://10.0.0.7:47990" in content
    assert "https://myapp.local" in content
    assert (managed_new, added) == ("https://10.0.0.7:47990", True)


def test_our_entry_is_never_duplicated(make_controller, config_path):
    controller = make_controller()
    managed, _ = controller.ensureCsrfAllowedOrigin("")

    _, added = controller.ensureCsrfAllowedOrigin(managed)

    assert config_path.read_text().count(OURS) == 1
    assert added is False


def test_without_a_lan_ip_the_config_is_left_alone(make_controller, write_config, config_path):
    write_config(f"csrf_allowed_origins = {OURS}\n")
    before = config_path.read_text()

    managed, added = make_controller(ip=None).ensureCsrfAllowedOrigin(OURS)

    assert config_path.read_text() == before
    assert (managed, added) == (OURS, False)


def test_the_key_present_but_empty_is_filled_in(make_controller, write_config, config_path):
    write_config("  csrf_allowed_origins =   \n")

    _, added = make_controller().ensureCsrfAllowedOrigin("")

    assert config_path.read_text() == f"csrf_allowed_origins = {OURS}\n"
    assert added is True


def test_an_unwritable_path_reports_no_change_instead_of_raising(make_controller, logger):
    controller = make_controller(path="/proc/does/not/exist/sunshine.conf")

    managed, added = controller.ensureCsrfAllowedOrigin("keepme")

    assert (managed, added) == ("keepme", False)
    assert logger.raised_with_traceback(
        "Could not update csrf_allowed_origins in sunshine.conf")


def test_a_portless_user_entry_covers_our_origin(make_controller, write_config, config_path):
    """Sunshine matches an entry without a port against any port on that host,
    so adding ours as well would be a duplicate in everything but spelling."""
    write_config("csrf_allowed_origins = https://192.168.1.50\n")

    managed, added = make_controller().ensureCsrfAllowedOrigin("")

    assert config_path.read_text() == "csrf_allowed_origins = https://192.168.1.50\n"
    assert (managed, added) == ("", False)


@pytest.mark.parametrize("origin, allowed, why", [
    ("https://192.168.1.50", True, "exactly the entry"),
    ("https://192.168.1.50:47990", True, "a port is a host boundary"),
    ("https://192.168.1.50/config", True, "so is a path"),
    ("https://192.168.1.500:47990", False, "a longer host, not a boundary"),
    ("https://192.168.1.50.attacker.example", False, "a suffix is not a boundary either"),
])
def test_origin_matching_follows_sunshine_semantics(make_controller, write_config,
                                                    origin, allowed, why):
    write_config("csrf_allowed_origins = https://192.168.1.50\n")

    assert make_controller().isCsrfOriginAllowed(origin) is allowed, why


def test_a_config_that_cannot_be_read_is_not_allowed(make_controller, tmp_path, logger):
    """editing_ready keys off this, so a True here would tell the panel the Web
    UI is editable when the file could not be opened at all.

    It has to be an existing file with the mode bits denied: a missing file (or
    an unreachable directory) never reaches the error path, because the read is
    skipped and an empty origin list answers instead.
    """
    unreadable = tmp_path / "unreadable.conf"
    unreadable.write_text(f"csrf_allowed_origins = {OURS}\n")
    unreadable.chmod(0o000)
    if os.access(unreadable, os.R_OK):
        pytest.skip("running as root - the mode bits are ignored here")

    try:
        assert make_controller(path=unreadable).isCsrfOriginAllowed(OURS) is False
    finally:
        unreadable.chmod(0o644)

    assert logger.raised_with_traceback(
        "Could not read csrf_allowed_origins from sunshine.conf")


def test_a_missing_config_is_not_allowed(make_controller, tmp_path):
    """The fresh-install state - a different path to the same answer."""
    absent = tmp_path / "absent" / "sunshine.conf"

    assert make_controller(path=absent).isCsrfOriginAllowed(OURS) is False
