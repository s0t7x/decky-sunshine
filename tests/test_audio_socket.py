"""The PulseAudio socket discovery that feeds PULSE_SERVER.

Sunshine gets its audio through a socket this plugin has to locate, and the
search has to survive systems that are not a stock Steam Deck: other user
names, several logged-in users, a greeter running its own PipeWire, and a
socket that exists but is not accepting connections yet during boot.

A) _expandSocketPattern - deterministic order, system users skipped
B) _canConnectToAudioSocket - a real socket answers, a plain file does not
C) _findPulseAudioSocketPath - candidate order, de-duplication, fallback
"""
import os
import shutil
import socket
import tempfile

import pytest

import sunshine as sunshine_module
from sunshine import SunshineController


DECK = "/run/user/1000/pulse/native"
OTHER = "/run/user/1001/pulse/native"
ROOT = "/run/user/0/pulse/native"


# --- A) _expandSocketPattern --------------------------------------------------
# glob returns readdir order, which differs between boots. The search has to be
# reproducible, and a greeter's socket must never outrank the session user's.

@pytest.fixture
def scripted_glob(monkeypatch):
    def _set(matches):
        monkeypatch.setattr(sunshine_module.glob, "glob", lambda pattern: list(matches))

    return _set


def test_sockets_are_sorted_by_uid_and_system_users_skipped(scripted_glob):
    scripted_glob([OTHER, DECK, "/run/user/120/pulse/native"])

    assert SunshineController._expandSocketPattern("/run/user/*/pulse/native") == [DECK, OTHER]


def test_uids_are_ordered_by_value_not_by_string(scripted_glob):
    """The two have to differ in digit count for this to be visible at all:
    as strings "10002" < "1002", as numbers the other way round."""
    scripted_glob(["/run/user/10002/pulse/native", "/run/user/1002/pulse/native"])

    assert SunshineController._expandSocketPattern("/run/user/*/pulse/native") == [
        "/run/user/1002/pulse/native", "/run/user/10002/pulse/native"]


def test_uid_less_matches_are_kept_and_sorted_lexically(scripted_glob):
    """/tmp/pulse-* carries no uid and must not be mistaken for uid 0 and dropped."""
    scripted_glob(["/tmp/pulse-abc/native", "/tmp/pulse-aaa/native"])

    assert SunshineController._expandSocketPattern("/tmp/pulse-*/native") == [
        "/tmp/pulse-aaa/native", "/tmp/pulse-abc/native"]


def test_uid_less_matches_sort_last(scripted_glob):
    """So a real session always beats something in /tmp."""
    scripted_glob(["/tmp/pulse-abc/native", DECK])

    assert SunshineController._expandSocketPattern("*") == [DECK, "/tmp/pulse-abc/native"]


def test_no_matches_yields_an_empty_list(scripted_glob):
    scripted_glob([])

    assert SunshineController._expandSocketPattern("/run/user/*/pulse/native") == []


# --- B) _canConnectToAudioSocket ----------------------------------------------
# Against real AF_UNIX sockets: the probe decides whether PULSE_SERVER points at
# something usable, and "the file exists" is not "it accepts connections".

@pytest.fixture(scope="module")
def socket_dir():
    """A short directory, not tmp_path.

    A unix socket path is capped at ~108 bytes, and the cap counts the whole
    absolute path - a long TMPDIR (a CI runner's workspace, a nested scratch
    dir) blows it with no room left for a file name, and the tests would fail
    for a reason that has nothing to do with the code.
    """
    directory = tempfile.mkdtemp(prefix="ds-sock-", dir="/tmp" if os.path.isdir("/tmp") else None)
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture
def probe(bare_controller):
    return bare_controller()


def test_the_probe_gives_up_after_a_second(probe, socket_dir, monkeypatch):
    """start_async probes this once a second for a minute while waiting for
    the audio stack. Without a timeout a socket that accepts but never answers
    blocks the whole start, and the panel sits at "Starting..." forever."""
    opened, timeouts = [], []

    class FakeSocket:
        def __init__(self, family, kind):
            opened.append((family, kind))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def settimeout(self, seconds):
            timeouts.append(seconds)

        def connect(self, address):
            pass

    monkeypatch.setattr(sunshine_module.socket, "socket", FakeSocket)

    assert probe._canConnectToAudioSocket("/run/user/1000/pulse/native") is True
    assert opened == [(sunshine_module.socket.AF_UNIX, sunshine_module.socket.SOCK_STREAM)], \
        "a unix stream socket - the same kind PulseAudio serves"
    assert timeouts == [1]


def test_a_listening_socket_is_connectable(probe, socket_dir):
    path = os.path.join(socket_dir, "listening.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    try:
        assert probe._canConnectToAudioSocket(path) is True
    finally:
        server.close()
        os.unlink(path)


def test_a_bound_but_unserved_socket_is_not_connectable(probe, socket_dir, logger):
    """The state during boot: pipewire-pulse created the socket but is not
    serving on it yet."""
    path = os.path.join(socket_dir, "dead.sock")
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(path)
    dead.close()
    try:
        assert probe._canConnectToAudioSocket(path) is False
    finally:
        os.unlink(path)

    assert any(line.startswith(f"Cannot connect to audio socket {path}: ")
               for line in logger.debugs), \
        "the errno is what tells a cold boot apart from a permission problem"


def test_a_plain_file_is_not_connectable(probe, socket_dir):
    path = os.path.join(socket_dir, "plain.file")
    open(path, "w").close()
    try:
        assert probe._canConnectToAudioSocket(path) is False
    finally:
        os.unlink(path)


def test_a_missing_path_is_not_connectable(probe, socket_dir):
    assert probe._canConnectToAudioSocket(os.path.join(socket_dir, "absent.sock")) is False


# --- C) _findPulseAudioSocketPath ---------------------------------------------
# The search itself. Nothing here may touch the real /run/user.

@pytest.fixture
def make_controller(logger):
    """Answers "does it exist" and "can I connect" from a script."""

    class FakeController(SunshineController):
        def __init__(self, existing=(), connectable=()):
            self.logger = logger
            self._socket_fallback_warned = False
            self.existing = set(existing)
            self.connectable = set(connectable)
            self.probed = []

        def _canConnectToAudioSocket(self, path):
            self.probed.append(path)
            return path in self.connectable

    return FakeController


@pytest.fixture
def find(monkeypatch):
    """Runs the search against a synthetic /run/user, with no filesystem access."""

    def _find(controller, env=None, deck_uid=1000, globs=None):
        def fake_getpwnam(name):
            if name == "deck" and deck_uid is not None:
                return type("pw", (), {"pw_uid": deck_uid})()
            raise KeyError(name)

        monkeypatch.setattr(sunshine_module.os, "environ", env if env is not None else {})
        monkeypatch.setattr(sunshine_module.os.path, "exists", lambda p: p in controller.existing)
        monkeypatch.setattr(sunshine_module.pwd, "getpwnam", fake_getpwnam)
        monkeypatch.setattr(sunshine_module.glob, "glob",
                            lambda pattern: list((globs or {}).get(pattern, [])))
        return controller._findPulseAudioSocketPath()

    return _find


def test_roots_own_socket_is_stepped_over_rather_than_stopped_at(make_controller, find):
    """The plugin runs as root, so /run/user/0 usually exists and is the one
    socket that is never the user\'s. Skipping it must not end the search -
    the readdir order decides whether it comes first."""
    root_socket = "/run/user/0/pulse/native"
    controller = make_controller(existing=[root_socket, DECK], connectable=[root_socket, DECK])

    result = find(controller, globs={"/run/user/*/pulse/native": [root_socket, DECK]})

    assert result == DECK
    assert root_socket not in controller.probed, "and it is not probed either"


def test_a_socket_under_tmp_is_a_candidate_too(make_controller, find):
    """PulseAudio proper puts its socket in /tmp/pulse-<random>/native rather
    than under /run/user. The Deck runs pipewire-pulse, but the plugin also
    runs on handhelds that do not."""
    socket_path = "/tmp/pulse-abc123/native"
    controller = make_controller(existing=[socket_path], connectable=[socket_path])

    result = find(controller, globs={"/tmp/pulse-*/native": [socket_path]})

    assert result == socket_path


def test_the_deck_users_socket_is_found(make_controller, find):
    controller = make_controller(existing=[DECK], connectable=[DECK])

    assert find(controller) == DECK


def test_the_deck_user_outranks_another_logged_in_user(make_controller, find):
    """Not whoever readdir happened to return first."""
    controller = make_controller(existing=[DECK, OTHER], connectable=[DECK, OTHER])

    result = find(controller, globs={"/run/user/*/pulse/native": [OTHER, DECK]})

    assert result == DECK


def test_a_session_user_who_is_neither_deck_nor_in_the_environment_is_found(
        make_controller, find):
    """The plugin runs as root, so XDG_RUNTIME_DIR is root's or unset, and on
    anything but a Deck there is no user called deck either - the /run/user/*
    glob is then the only route to the socket, and without it Sunshine streams
    with no audio."""
    controller = make_controller(existing=[OTHER], connectable=[OTHER])

    result = find(controller, deck_uid=None,
                  globs={"/run/user/*/pulse/native": [OTHER]})

    assert result == OTHER


def test_xdg_runtime_dir_is_used_when_there_is_no_deck_user(make_controller, find):
    """The strongest hint we have when the user is not called deck."""
    controller = make_controller(existing=[OTHER], connectable=[OTHER])

    result = find(controller, env={"XDG_RUNTIME_DIR": "/run/user/1001"}, deck_uid=None)

    assert result == OTHER


def test_a_runtime_dir_that_looks_like_roots_is_not_made_a_candidate(make_controller, find):
    """We are spawned as root, and root's own socket is never the one Sunshine
    needs. Two guards cover that, and each is checked on its own because either
    alone would hide the other failing.

    /run/user/01 isolates the first: its substring test rejects the path, while
    the second guard ("/run/user/0/") does not match it at all.
    """
    odd = "/run/user/01/pulse/native"
    controller = make_controller(existing=[odd, DECK], connectable=[odd, DECK])

    result = find(controller, env={"XDG_RUNTIME_DIR": "/run/user/01"},
                  globs={"/run/user/*/pulse/native": [DECK]})

    assert result == DECK
    assert odd not in controller.probed


def test_a_candidate_under_run_user_zero_is_skipped_before_it_is_probed(make_controller, find):
    """The second guard, reached when the user we resolve is itself root - the
    glob never produces it, since _expandSocketPattern drops uid < 1000 first."""
    controller = make_controller(existing=[ROOT, DECK], connectable=[ROOT, DECK])

    result = find(controller, deck_uid=0, globs={"/run/user/*/pulse/native": [DECK]})

    assert result == DECK
    assert ROOT not in controller.probed


def test_a_path_reached_by_three_patterns_is_probed_once(make_controller, find, logger):
    """Measured on the failing path on purpose: a connectable socket returns on
    the first hit and would walk no duplicates at all. Here XDG_RUNTIME_DIR, the
    deck uid and the glob all yield the same path."""
    controller = make_controller(existing=[DECK], connectable=[])

    find(controller, env={"XDG_RUNTIME_DIR": "/run/user/1000"},
         globs={"/run/user/*/pulse/native": [DECK]})

    assert controller.probed.count(DECK) == 1
    # Counted only in the list of unreachable sockets - the default path names
    # it a second time, legitimately
    listed = logger.warnings[0].split(" - using default")[0]
    assert listed.count(DECK) == 1


def test_an_unconnectable_socket_falls_back_to_the_default_path(make_controller, find, logger):
    """Boot order: the socket is there before anything listens on it.

    The socket that was found is deliberately not the default one, so the
    answer can only have come from the fallback."""
    controller = make_controller(existing=[OTHER], connectable=[])

    result = find(controller, globs={"/run/user/*/pulse/native": [OTHER]})

    assert result == DECK, "the deck-uid default, not the socket that was found"
    assert any("not accepting connections" in line and OTHER in line
               for line in logger.warnings)


def test_the_default_path_is_used_when_nothing_exists(make_controller, find, logger):
    controller = make_controller(existing=[], connectable=[])

    assert find(controller) == DECK
    assert any("No PulseAudio socket found" in line for line in logger.warnings), \
        "a different cause deserves a different message"


def test_the_default_falls_back_to_uid_1000_without_a_deck_user(make_controller, find):
    """Not a Steam Deck: no user called deck, so uid 1000 is the best guess left."""
    controller = make_controller(existing=[], connectable=[])

    assert find(controller, deck_uid=None) == DECK


def test_the_deck_users_real_uid_is_used_rather_than_a_hardcoded_1000(
        make_controller, find, logger):
    """A converted PC or a second account. The socket has to be *found*, not
    merely guessed: the fallback path would return the same string from
    deck_uid alone and hide a hardcoded pattern."""
    deck_1003 = "/run/user/1003/pulse/native"
    controller = make_controller(existing=[deck_1003], connectable=[deck_1003])

    result = find(controller, deck_uid=1003)

    assert result == deck_1003
    assert controller.probed == [deck_1003]
    assert logger.warnings == [], "a found socket needs no fallback warning"


def test_the_fallback_uses_the_deck_users_real_uid_too(make_controller, find):
    """Where a hardcoded 1000 would otherwise survive: converted PC, deck user
    on 1003, PipeWire not up yet."""
    controller = make_controller(existing=[], connectable=[])

    assert find(controller, deck_uid=1003) == "/run/user/1003/pulse/native"


def test_the_fallback_warning_is_logged_once_not_once_per_retry(
        make_controller, find, logger):
    """start_async probes once a second while waiting."""
    controller = make_controller(existing=[], connectable=[])

    find(controller)
    find(controller)
    find(controller)

    assert len(logger.warnings) == 1
    assert logger.debugs == [logger.warnings[0]] * 2, \
        "the repeats are still logged, at debug level - and say the same thing"


def test_the_warning_re_arms_after_a_successful_search(make_controller, find, logger):
    """A later regression has to be visible again."""
    controller = make_controller(existing=[DECK], connectable=[])
    find(controller)
    controller.connectable.add(DECK)
    find(controller)
    controller.connectable.clear()

    find(controller)

    assert sum("not accepting connections" in line for line in logger.warnings) == 2


def test_pipewire_zero_is_never_a_candidate(make_controller, find):
    """It speaks the wrong protocol: it would accept the connection and then be
    useless to Sunshine's libpulse client."""
    pipewire = "/run/user/1000/pipewire-0"
    controller = make_controller(existing=[pipewire, DECK], connectable=[pipewire, DECK])

    result = find(controller, globs={"/run/user/*/pulse/native": [DECK]})

    assert pipewire not in controller.probed
    assert result == DECK
