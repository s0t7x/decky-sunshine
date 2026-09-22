"""The two gates a start has to pass: is there a display, is there audio.

Started too early in the boot, Sunshine finds no display to capture and no
audio device, and dies without saying anything useful. Both checks therefore
run before the process is spawned, and both answer "not yet" rather than
"never" - start_async waits on them (see test_startup_env.py). What this file
pins is the answers themselves.

The two are deliberately asymmetric, which is easiest to see here: the display
check asks drm_info what the kernel is actually scanning out, while the audio
check settles for a socket that accepts a connection - and hands the socket it
found to Sunshine.
"""
import json
import os
import socket

import pytest

import sunshine as sunshine_module


# --- the display --------------------------------------------------------------
# drm_info -j reports every card with its crtcs. A crtc whose fb_id is 0 is
# scanning nothing out, and Sunshine's own kmsgrab skips exactly those - so a
# card is only worth anything once one of its crtcs has a framebuffer.

def drm_info(*cards):
    """:param cards: one list of fb_ids per card"""
    return json.dumps({
        f"card{index}": {"crtcs": [{"fb_id": fb_id} for fb_id in fb_ids]}
        for index, fb_ids in enumerate(cards)
    })


@pytest.fixture
def display(bare_controller):
    """Answers drm_info from a scripted string and records the query."""

    def _make(output):
        controller = bare_controller(queries=[])

        def capture(args, context=None):
            controller.queries.append((list(args), context))
            return output

        controller._run_and_capture_stdout = capture
        return controller

    return _make


@pytest.mark.parametrize("output, expected, why", [
    (drm_info([0, 140]), True, "a framebuffer is being scanned out"),
    (drm_info([0], [0, 77]), True, "one card out of several is enough"),
    (drm_info([0, 0], [0]), False,
     "the cold-boot state this check exists for: cards are there, nothing is "
     "scanned out, and Sunshine started now would come up blind"),
    (json.dumps({"card0": {"crtcs": [{}]}}), False, "a crtc without an fb_id"),
    (json.dumps({"card0": {}}), False, "a card without crtcs"),
    ("{}", False, "no cards at all"),
    ("null", False, "valid JSON that is not an object - `data or {}` keeps this from raising"),
    (None, False,
     "_run_and_capture_stdout answers None when the command fails, and an "
     "answer we could not get is not a yes"),
])
def test_whether_a_display_is_scanning_out(display, output, expected, why):
    assert display(output)._isDisplayAvailable() is expected, why


def test_a_command_that_simply_failed_is_not_reported_as_an_exception(display, logger):
    """The cold-boot wait calls this once a second for a minute; a stack trace
    per call would bury the log."""
    assert display(None)._isDisplayAvailable() is False

    assert not logger.exceptions


def test_output_that_is_not_json_is_not_a_display(display, logger):
    controller = display("drm_info: /dev/dri/card0: Permission denied")

    assert controller._isDisplayAvailable() is False
    assert logger.raised_with_traceback(
        "An error occurred when parsing the output of drm_info"), \
        "the reason has to be in the log, not just the False"


def test_a_json_null_is_not_a_display(display):
    """Valid JSON that is not an object at all - `data or {}` keeps this
    from raising."""
    assert display("null")._isDisplayAvailable() is False


def test_the_query_asks_drm_info_for_json(display):
    controller = display(drm_info([1]))

    controller._isDisplayAvailable()

    assert controller.queries == [
        (["drm_info", "-j"], "checking for available display"),
    ], "-j because the answer is parsed as JSON; the context names the caller"


# --- audio --------------------------------------------------------------------

@pytest.fixture
def audio(bare_controller, monkeypatch, tmp_path):
    """A controller whose socket search and connect attempt are scripted.

    Both are stubbed rather than real: which socket is the right one has its
    own file (test_audio_socket.py), and what matters here is what
    _isAudioAvailable does with the answer.
    """
    monkeypatch.delenv("PULSE_SERVER", raising=False)

    def _make(found=None, connectable=True, environment=None, exists=True):
        path = str(found if found is not None else tmp_path / "pulse" / "native")
        if exists:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
        controller = bare_controller(
            environment_variables=dict(environment or {}),
            connect_attempts=[],
        )
        controller._findPulseAudioSocketPath = lambda: path
        def connect(socket_path):
            controller.connect_attempts.append(socket_path)
            return connectable
        controller._canConnectToAudioSocket = connect
        controller.socket_path = path
        return controller

    return _make


def test_a_working_socket_is_available(audio):
    controller = audio()

    assert controller._isAudioAvailable() is True
    assert controller.connect_attempts == [controller.socket_path], \
        "the socket that was found is the one that has to be probed"


def test_the_socket_that_was_found_is_handed_to_sunshine(audio, logger):
    """Sunshine is spawned with this environment, so finding the socket is only
    half the job - it has to end up where Sunshine looks for it."""
    controller = audio()

    controller._isAudioAvailable()

    assert controller.environment_variables["PULSE_SERVER"] == f"unix:{controller.socket_path}"
    assert f"Updated PULSE_SERVER to unix:{controller.socket_path}" in logger.infos, \
        "the value matters as much as the fact - it is what Sunshine will be given"


def test_an_unchanged_socket_is_not_announced_again(audio, logger):
    """The gate runs once a second while waiting; re-logging the same value
    would bury the line that says it changed."""
    controller = audio()
    controller.environment_variables["PULSE_SERVER"] = f"unix:{controller.socket_path}"

    controller._isAudioAvailable()

    assert not any("Updated PULSE_SERVER" in line for line in logger.infos)


def test_a_socket_path_that_does_not_exist_is_not_available(audio, tmp_path, logger):
    controller = audio(found=tmp_path / "nowhere" / "native", exists=False)

    assert controller._isAudioAvailable() is False
    assert controller.connect_attempts == [], "nothing to connect to"
    assert f"Audio socket does not exist: {controller.socket_path}" in logger.debugs, \
        "debug rather than info: the gate asks once a second while waiting"


def test_a_socket_that_does_not_answer_is_not_available(audio):
    """It exists - a leftover from a session that is gone, or one PipeWire has
    not started serving yet. Either way Sunshine would find no audio."""
    controller = audio(connectable=False)

    assert controller._isAudioAvailable() is False
    assert controller.environment_variables.get("PULSE_SERVER") is None, \
        "a socket that does not answer must not be handed on"


# --- audio, when the environment already says where it is ---------------------

def test_an_externally_configured_socket_wins_over_the_search(audio, monkeypatch):
    controller = audio()
    monkeypatch.setenv("PULSE_SERVER", f"unix:{controller.socket_path}")

    assert controller._isAudioAvailable() is True
    assert controller.connect_attempts == [controller.socket_path], \
        "the configured socket is the one that has to be probed, not another"
    assert controller.environment_variables.get("PULSE_SERVER") is None, \
        "it is already in the environment Sunshine inherits; nothing to update"


def test_an_externally_configured_socket_is_still_checked(audio, monkeypatch, tmp_path,
                                                          logger):
    controller = audio()
    external = f"unix:{tmp_path / 'gone'}"
    monkeypatch.setenv("PULSE_SERVER", external)

    assert controller._isAudioAvailable() is False
    assert (f"Externally configured PULSE_SERVER is not connectable (yet): {external}"
            in logger.debugs), \
        "somebody set this deliberately, so the line has to name what was tried"


def test_an_externally_configured_socket_that_does_not_answer_fails(audio, monkeypatch):
    controller = audio(connectable=False)
    monkeypatch.setenv("PULSE_SERVER", f"unix:{controller.socket_path}")

    assert controller._isAudioAvailable() is False


def test_a_network_pulse_server_is_taken_at_its_word(audio, monkeypatch):
    """Only unix: paths can be probed. A tcp: endpoint was configured by
    someone who knows better than this check does."""
    controller = audio(connectable=False)
    monkeypatch.setenv("PULSE_SERVER", "tcp:192.168.1.5:4713")

    assert controller._isAudioAvailable() is True
    assert controller.connect_attempts == []


# --- the connect attempt itself ----------------------------------------------

def test_an_unexpected_failure_while_probing_is_not_a_crash(bare_controller,
                                                            monkeypatch, logger):
    """The gate runs before anything else on every start; an exception here
    would take the start down instead of answering "no audio yet"."""
    controller = bare_controller()

    def exploding_socket(*args, **kwargs):
        raise ValueError("no socket for you")

    monkeypatch.setattr(sunshine_module.socket, "socket", exploding_socket)

    assert controller._canConnectToAudioSocket("/run/user/1000/pulse/native") is False
    assert logger.raised_with_traceback("Unexpected error checking audio availability")
