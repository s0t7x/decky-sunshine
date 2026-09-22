"""Talking to the outside: subprocesses and Sunshine's Web API.

Three narrow layers that everything else in the controller goes through, so a
mistake in any of them shows up as a wrong answer somewhere far away. The two
callers that parse what comes back are at the end of the file.

A) _run and its two wrappers - every flatpak/su/cp call in this plugin. The
   contract is "None means it did not work", and the reason has to reach the
   log, because the caller only sees the None.
B) _request - Sunshine's Web API. Telling its failures apart is what the panel
   is built on: 401 means wrong credentials (ask for new ones), a refused
   connection means Sunshine is not up yet (wait), and anything else is an
   error worth showing.
C) _createRequest - what is actually sent.
"""
import json
import socket as socket_module
import ssl
import subprocess

import pytest

from http.client import UNAUTHORIZED
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler

import sunshine as sunshine_module
from sunshine import NoRedirect, RequestError


# --- A) subprocesses ----------------------------------------------------------

@pytest.fixture
def runner(bare_controller, monkeypatch):
    """A controller whose subprocess.run is scripted."""

    def _make(returncode=0, stdout="", stderr="", raises=None):
        controller = bare_controller(environment_variables={"PATH": "/usr/bin"},
                                     calls=[])

        def fake_run(args, env=None, capture_output=None, text=None):
            controller.calls.append({"args": list(args), "env": env,
                                     "capture_output": capture_output, "text": text})
            if raises is not None:
                raise raises
            # Honours text the way subprocess does, so an assertion about it is
            # about behaviour rather than bookkeeping
            out, err = (stdout, stderr) if text else (stdout.encode(), stderr.encode())
            return subprocess.CompletedProcess(args, returncode, out, err)

        monkeypatch.setattr(sunshine_module.subprocess, "run", fake_run)
        return controller

    return _make


def test_a_successful_command_comes_back_whole(runner):
    controller = runner(stdout="output\n")

    proc = controller._run(["flatpak", "ps"])

    assert proc.stdout == "output\n"


def test_the_command_runs_in_the_controllers_environment(runner):
    """Not os.environ: the sanitised copy is what keeps the loader's bundled
    libraries out of the subprocess, and it carries PULSE_SERVER."""
    controller = runner()

    controller._run(["flatpak", "ps"])

    assert controller.calls[0]["env"] == controller.environment_variables
    assert controller.calls[0]["capture_output"] is True
    assert controller.calls[0]["text"] is True, "without it every parser gets bytes"


def test_a_non_zero_exit_is_a_failure_with_its_stderr_in_the_log(runner, logger):
    """The caller gets None and nothing else, so the log is the only place the
    reason can be."""
    controller = runner(returncode=1, stderr="  error: not found  \n")

    assert controller._run(["flatpak", "ps"], context="listing apps") is None
    assert any("listing apps" in line and "error: not found" in line
               for line in logger.errors)


def test_a_command_that_cannot_be_run_at_all_is_not_fatal(runner, logger):
    controller = runner(raises=FileNotFoundError("no flatpak"))

    assert controller._run(["flatpak", "ps"], context="listing apps") is None
    assert logger.raised_with_traceback("An exception occurred when listing apps"), \
        "the context is what says which of the plugin's many flatpak calls broke"


def test_without_a_context_the_command_names_itself(runner, logger):
    """A name that needs quoting, so the quoting is visible in the result -
    with a plain "flatpak" the quoted and unquoted forms are the same."""
    controller = runner(returncode=1)

    controller._run(["my flatpak", "ps"])

    assert any("'my flatpak'" in line for line in logger.errors)


def test_the_check_wrapper_reduces_the_result_to_a_yes_or_no(runner):
    assert runner()._run_and_check(["true"]) is True
    assert runner(returncode=2)._run_and_check(["false"]) is False


def test_both_wrappers_pass_the_context_on(runner):
    """They are the only two ways anything in this plugin runs a command, so a
    context dropped here silently unlabels every error message below them."""
    for call in ("_run_and_check", "_run_and_capture_stdout"):
        controller = runner(returncode=1)

        getattr(controller, call)(["my flatpak", "ps"], context="listing apps")

        assert any("listing apps" in line for line in controller.logger.errors), call


def test_the_capture_wrapper_hands_back_stdout_or_nothing(runner):
    assert runner(stdout="lines\n")._run_and_capture_stdout(["echo"]) == "lines\n"
    assert runner(returncode=1, stdout="lines\n")._run_and_capture_stdout(["echo"]) is None


# --- the one caller that parses a list ---------------------------------------

def test_a_running_sunshine_is_recognised(bare_controller):
    controller = bare_controller()
    controller._run_and_capture_stdout = lambda args, context=None: (
        "com.valvesoftware.Steam\ndev.lizardbyte.app.Sunshine\n")

    assert controller.isSunshineRunning() is True


def test_the_question_asked_of_flatpak_is_exactly_this(bare_controller):
    """--columns=application is what makes the answer one app id per line,
    which is what the comparison below relies on; without it flatpak prints a
    table and every id arrives with padding and neighbours. The context is
    what a failure says in the log, and this call is made every five seconds,
    so an unlabelled one is unfindable.
    """
    controller = bare_controller(asked=[])
    controller._run_and_capture_stdout = lambda args, context=None: (
        controller.asked.append((list(args), context)) or "")

    controller.isSunshineRunning()

    assert controller.asked == [
        (["flatpak", "ps", "--columns=application"],
         "checking whether Sunshine is running"),
    ]


def test_another_app_whose_id_contains_ours_is_not_sunshine(bare_controller):
    controller = bare_controller()
    controller._run_and_capture_stdout = lambda args, context=None: (
        "dev.lizardbyte.app.SunshineExtra\n")

    assert controller.isSunshineRunning() is False


def test_a_failed_ps_call_means_not_running(bare_controller):
    controller = bare_controller()
    controller._run_and_capture_stdout = lambda args, context=None: None

    assert controller.isSunshineRunning() is False


# --- the LAN IP ---------------------------------------------------------------

def test_the_lan_ip_is_looked_up_over_an_unconnected_udp_socket(bare_controller,
                                                                monkeypatch):
    """UDP is what makes this free: connecting a datagram socket only makes
    the kernel pick a source address, no packet leaves the machine and nothing
    on the other side has to exist. A stream socket would try to connect to
    TEST-NET-1 and block until it timed out."""
    opened = []

    class FakeSocket:
        def __init__(self, family, kind):
            opened.append((family, kind))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def connect(self, address):
            pass

        def getsockname(self):
            return ("192.168.1.50", 0)

    monkeypatch.setattr(sunshine_module.socket, "socket", FakeSocket)

    assert bare_controller().getLanIp() == "192.168.1.50"
    assert opened == [(sunshine_module.socket.AF_INET, sunshine_module.socket.SOCK_DGRAM)]


def test_the_lan_ip_is_the_source_address_of_the_default_route(bare_controller,
                                                               monkeypatch):
    """No packet is sent: connecting a UDP socket only makes the kernel pick a
    source address, and the target is TEST-NET-1, which is never routable."""
    connected = []

    class FakeSocket:
        def __init__(self, family, kind):
            self.family = family

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def connect(self, address):
            connected.append(address)

        def getsockname(self):
            return ("192.168.1.38", 51234)

    monkeypatch.setattr(sunshine_module.socket, "socket", FakeSocket)

    assert bare_controller().getLanIp() == "192.168.1.38"
    assert connected == [("192.0.2.1", 80)]


def test_without_a_route_there_is_no_lan_ip(bare_controller, monkeypatch, logger):
    def no_route(family, kind):
        raise OSError("Network is unreachable")

    monkeypatch.setattr(sunshine_module.socket, "socket", no_route)

    assert bare_controller().getLanIp() is None
    assert "Could not determine the LAN IP: Network is unreachable" in logger.warnings


# --- B) the Web API -----------------------------------------------------------

class FakeResponse:
    def __init__(self, code=200, body=b'{"status": true}', charset="utf-8"):
        self.code = code
        self.body = body
        self.charset = charset
        self.headers = self

    def get_content_charset(self):
        return self.charset

    def getcode(self):
        return self.code

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def api(bare_controller):
    """A controller whose opener answers with a response or raises."""

    def _make(response=None, raises=None):
        controller = bare_controller(authHeader="Basic dGVzdA==", opened=[])

        class FakeOpener:
            def open(self, request, timeout=None):
                controller.opened.append((request, timeout))
                if raises is not None:
                    raise raises
                return response if response is not None else FakeResponse()

        controller.opener = FakeOpener()
        return controller

    return _make


def test_a_successful_request_carries_the_parsed_body(api):
    controller = api(FakeResponse(body=b'{"status": true, "apps": []}'))

    result = controller._request("/api/apps")

    assert result.ok is True
    assert result.data == {"status": True, "apps": []}


def test_the_request_that_reaches_the_opener_carries_path_and_body(api):
    """The only test that follows data all the way out: everything else calls
    a body-less endpoint, and the callers that do send one are tested against
    a stubbed _request_async."""
    controller = api()

    controller._request("/api/pin", {"pin": "1234"})

    request, _ = controller.opened[0]
    assert request.full_url.endswith("/api/pin")
    assert json.loads(request.data.decode("utf-8")) == {"pin": "1234"}


def test_the_request_does_not_wait_forever(api):
    """The panel polls this; an unbounded wait would park the executor thread
    for as long as Sunshine is wedged."""
    controller = api()

    controller._request("/api/apps")

    assert controller.opened[0][1] == 5


# A client name with an umlaut in it, because that is the only kind of body
# that can tell the two codecs apart - pure ASCII encodes identically in both.
def test_the_response_charset_is_honoured(api):
    controller = api(FakeResponse(body='{"name": "Küche"}'.encode("latin-1"),
                                  charset="latin-1"))

    assert controller._request("/api/clients/list").data["name"] == "Küche"


def test_a_response_without_a_charset_is_read_as_utf8(api):
    controller = api(FakeResponse(body='{"name": "Küche"}'.encode("utf-8"),
                                  charset=None))

    assert controller._request("/api/clients/list").data["name"] == "Küche"


def test_a_non_ok_status_is_a_plain_failure(api, logger):
    controller = api(FakeResponse(code=503))

    result = controller._request("/api/apps")

    assert (result.ok, result.error) == (False, RequestError.OTHER)
    assert ("Request to path '/api/apps' with data 'None' failed with code: 503"
            in logger.errors)


def test_an_unauthorized_answer_is_told_apart(api):
    """The panel offers a login on this and only this - anything else would
    make it ask for credentials that are perfectly fine."""
    controller = api(raises=HTTPError("https://127.0.0.1:47990/api/apps", UNAUTHORIZED,
                                      "Unauthorized", {}, None))

    result = controller._request("/api/apps")

    assert result.is_unauthorized() is True
    assert result.ok is False


def test_another_http_error_is_not_an_authentication_problem(api, logger):
    controller = api(raises=HTTPError("https://127.0.0.1:47990/api/apps", 500,
                                      "Server Error", {}, None))

    result = controller._request("/api/apps")

    assert result.is_unauthorized() is False
    assert result.error == RequestError.OTHER
    assert ("HTTP error in request to path '/api/apps' with data 'None', "
            "code: 500, reason: Server Error") in logger.errors


def test_a_refused_connection_means_sunshine_is_not_up_yet(api, logger):
    """_initSunshine waits on exactly this while the Web UI is still coming
    up after a fresh install."""
    # No errno, so only the ConnectionRefusedError branch can catch it;
    # test_a_refusal_reported_as_a_plain_oserror_counts_too covers the other.
    controller = api(raises=URLError(ConnectionRefusedError("Connection refused")))

    assert controller._request("/api/apps").is_unreachable() is True
    assert ("Server not reachable when requesting path '/api/apps' with data "
            "'None': Connection refused") in logger.errors


def test_a_refusal_reported_as_a_plain_oserror_counts_too(api):
    """Some stacks hand up an OSError with errno 111 rather than the subclass.

    Built by hand rather than as OSError(111, ...): that constructor returns a
    ConnectionRefusedError, so it would be caught by the isinstance check above
    and this test would pass with the errno branch removed entirely.
    """
    error = OSError("Connection refused")
    error.errno = 111
    assert type(error) is OSError, "precondition: not the subclass"
    controller = api(raises=URLError(error))

    assert controller._request("/api/apps").is_unreachable() is True


def test_a_value_containing_a_separator_survives_the_config_parser(bare_controller,
                                                                   tmp_path):
    """csrf_allowed_origins holds URLs, and a port is one colon away from an
    equals sign in somebody else\'s config. Splitting on the last separator
    instead of the first would cut the value in half."""
    config = tmp_path / "sunshine.conf"
    config.write_text("csrf_allowed_origins = https://a=b:47990,https://c\n")
    controller = bare_controller(SunshineConfigPath=str(config))

    _, _, origins = controller._readCsrfAllowedOrigins()

    assert origins == ["https://a=b:47990", "https://c"]


def test_another_errno_on_a_plain_oserror_is_not_a_refusal(api):
    """111 is ECONNREFUSED specifically; 113 (no route) means something else
    is wrong and the caller must not sit there waiting for a web server."""
    error = OSError("No route to host")
    error.errno = 113
    controller = api(raises=URLError(error))

    assert controller._request("/api/apps").is_unreachable() is False


def test_another_url_error_is_not_a_refusal(api, logger):
    controller = api(raises=URLError(OSError(113, "No route to host")))

    result = controller._request("/api/apps")

    assert result.is_unreachable() is False
    assert result.error == RequestError.OTHER
    assert ("URL error in request to path '/api/apps' with data 'None', "
            "reason: [Errno 113] No route to host") in logger.errors


def test_a_body_that_is_not_json_is_an_error_not_a_crash(api, logger):
    controller = api(FakeResponse(body=b"<html>nope</html>"))

    result = controller._request("/api/apps")

    assert (result.ok, result.error) == (False, RequestError.OTHER)
    assert logger.raised_with_traceback(
        "An error occurred when performing a request to path '/api/apps' with data 'None'")


# --- C) what gets sent --------------------------------------------------------

def test_the_request_goes_to_sunshines_local_web_ui(bare_controller):
    controller = bare_controller(authHeader="Basic dGVzdA==")

    request = controller._createRequest("/api/apps")

    assert request.full_url == "https://127.0.0.1:47990/api/apps"


def test_the_auth_header_is_attached(bare_controller):
    controller = bare_controller(authHeader="Basic dGVzdA==")

    request = controller._createRequest("/api/apps")

    assert request.get_header("Authorization") == "Basic dGVzdA=="


def test_the_request_looks_like_the_web_ui_own_requests(bare_controller):
    """Sunshine's API is the Web UI's own, and these are the headers a browser
    sends it. Accept in particular is what decides whether an error comes back
    as JSON or as the HTML login page - which the caller then fails to parse
    and reports as "not reachable"."""
    controller = bare_controller(authHeader="Basic dGVzdA==")

    request = controller._createRequest("/api/apps")

    assert request.get_header("User-agent") == "decky-sunshine"
    assert request.get_header("Connection") == "keep-alive"
    assert request.get_header("Accept") == "application/json, */*; q=0.01"


def test_a_request_without_data_carries_no_body(bare_controller):
    """It would turn a GET into a POST, which Sunshine answers differently."""
    controller = bare_controller(authHeader="")

    request = controller._createRequest("/api/apps")

    assert request.data is None
    assert request.get_header("Content-type") is None


def test_data_is_sent_as_json(bare_controller):
    controller = bare_controller(authHeader="")

    request = controller._createRequest("/api/pin", {"pin": "1234", "name": "TV"})

    assert json.loads(request.data.decode("utf-8")) == {"pin": "1234", "name": "TV"}
    assert request.get_header("Content-type") == "application/json"
    assert request.data == b'{"pin": "1234", "name": "TV"}', \
        "UTF-8 on the wire, and no re-ordering or re-spacing by anything in between"


def test_redirects_are_not_followed():
    """Sunshine redirects an unauthenticated request to its login page, and a
    followed redirect would turn a 401 into a 200 with an HTML body."""
    assert NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://elsewhere") is None


def test_the_opener_the_requests_go_through_refuses_redirects(logger, monkeypatch):
    """Not NoRedirect on its own: it has to be in the opener _request uses.
    Every test above replaces that opener, so this is the only place the real
    one is looked at."""
    monkeypatch.setenv("DECKY_PLUGIN_RUNTIME_DIR", "/tmp")

    controller = sunshine_module.SunshineController(logger)

    assert any(isinstance(handler, NoRedirect) for handler in controller.opener.handlers)


def test_sunshines_self_signed_certificate_is_accepted(logger, monkeypatch):
    """Deliberate, and pinned so that turning verification on is a decision
    rather than an accident: Sunshine serves a self-signed certificate on
    127.0.0.1, and the connection never leaves the machine."""
    monkeypatch.setenv("DECKY_PLUGIN_RUNTIME_DIR", "/tmp")

    controller = sunshine_module.SunshineController(logger)

    context = next(h for h in controller.opener.handlers
                   if isinstance(h, HTTPSHandler))._context
    assert context.verify_mode is ssl.CERT_NONE
    assert context.check_hostname is False
