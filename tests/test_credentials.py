"""Credentials and pairing.

Sunshine's Web API is Basic-auth'd, and the plugin keeps the header rather than
the password. Two things follow: the header has to round-trip back into a
username and password for the panel to show, and a malformed one must not take
the panel down with it - it comes out of a settings file that survives plugin
updates and can be anything.

Pairing is the other half. Sunshine's /api/pin answers true whenever a pairing
request is pending, whether or not the PIN was right
(LizardByte/Sunshine#3944), so the plugin decides for itself: count the clients
with that name before and after, and call it paired only if there is one more.
"""
import asyncio

import pytest

from sunshine import RequestError, RequestResult


# --- the header ---------------------------------------------------------------

def test_credentials_become_a_basic_auth_header(bare_controller):
    controller = bare_controller(authHeader="")

    header = controller.setCredentials("decky_sunshine", "hunter2")

    assert header == "Basic ZGVja3lfc3Vuc2hpbmU6aHVudGVyMg=="
    assert controller.authHeader == header


def test_an_incomplete_pair_is_refused_rather_than_encoded(bare_controller, logger):
    """A header built from half a login authenticates nothing and would replace
    one that works."""
    controller = bare_controller(authHeader="Basic ZXhpc3Rpbmc=")

    assert controller.setCredentials("user", "") == ""
    assert controller.setCredentials("", "secret") == ""
    assert controller.authHeader == "Basic ZXhpc3Rpbmc=", "the old one is untouched"
    assert "No username or password provided for setting AuthHeader" in logger.infos


def test_the_header_round_trips_back_into_a_login(bare_controller):
    controller = bare_controller(authHeader="")
    controller.setCredentials("decky_sunshine", "hunter2")

    assert controller.getCredentials() == {"username": "decky_sunshine",
                                           "password": "hunter2"}


def test_a_password_containing_a_colon_survives_the_round_trip(bare_controller):
    """Only the first colon separates the two - _initSunshine's generated
    password is url-safe base64, but a user may type anything."""
    controller = bare_controller(authHeader="")
    controller.setCredentials("user", "a:b:c")

    assert controller.getCredentials()["password"] == "a:b:c"


def test_no_header_means_no_credentials(bare_controller, logger):
    controller = bare_controller(authHeader="")

    assert controller.getCredentials() is None
    assert "AuthHeader is not set or invalid" in logger.infos


def test_a_header_of_another_scheme_is_not_decoded(bare_controller, logger):
    """The payload here would decode cleanly to user:pass, so only the scheme
    check can be what refuses it."""
    controller = bare_controller(authHeader="Bearer dXNlcjpwYXNz")

    assert controller.getCredentials() is None
    assert "AuthHeader is not set or invalid" in logger.infos


def test_a_corrupt_header_does_not_take_the_panel_down(bare_controller, logger):
    """It comes from the settings file, which survives plugin updates and can
    hold anything an older version wrote."""
    controller = bare_controller(authHeader="Basic not-base64!!")

    assert controller.getCredentials() is None
    assert logger.raised_with_traceback(
        "An error occurred when decoding credentials from AuthHeader")


def test_a_header_without_a_colon_is_not_a_login(bare_controller):
    controller = bare_controller(authHeader="Basic dXNlcm5hbWU=")   # "username"

    assert controller.getCredentials() is None


# --- are they valid -----------------------------------------------------------

@pytest.fixture
def checker(bare_controller):
    def _make(running=True, result=None):
        controller = bare_controller(requests=[])

        async def is_running():
            return running

        async def request(path, data=None):
            controller.requests.append((path, data))
            return result if result is not None else RequestResult.success({})

        controller.isSunshineRunning_async = is_running
        controller._request_async = request
        return controller

    return _make


async def test_an_answered_request_means_the_credentials_work(checker):
    controller = checker()

    assert await controller.areCredentialsValid_async() is True
    assert controller.requests == [("/api/apps", None)]


async def test_a_rejected_request_means_they_do_not(checker):
    controller = checker(result=RequestResult.failure(RequestError.UNAUTHORIZED))

    assert await controller.areCredentialsValid_async() is False


async def test_without_a_running_sunshine_there_is_no_answer(checker):
    """Not False: the panel offers a login on False, and there is nothing wrong
    with the credentials of a Sunshine that is simply not running."""
    controller = checker(running=False)

    assert await controller.areCredentialsValid_async() is None
    assert controller.requests == []


async def test_any_other_failure_is_no_answer_either(checker):
    controller = checker(result=RequestResult.failure(RequestError.UNREACHABLE))

    assert await controller.areCredentialsValid_async() is None


# --- changing the password ----------------------------------------------------

@pytest.fixture
def password_setter(bare_controller):
    def _make(result):
        controller = bare_controller(authHeader="", requests=[])

        async def request(path, data=None):
            controller.requests.append((path, data))
            return result

        controller._request_async = request
        return controller

    return _make


async def test_a_new_password_is_sent_and_then_used(password_setter):
    """The header has to be updated in the same step: the old one stops working
    the moment Sunshine accepts the change."""
    controller = password_setter(RequestResult.success({"status": True}))

    assert await controller._setUser_async("decky_sunshine", "hunter2") is True
    path, data = controller.requests[0]
    assert path == "/api/password"
    assert data == {"newUsername": "decky_sunshine", "newPassword": "hunter2",
                    "confirmNewPassword": "hunter2"}
    assert controller.getCredentials() == {"username": "decky_sunshine",
                                           "password": "hunter2"}


async def test_the_current_login_is_sent_along_when_there_is_one(password_setter):
    controller = password_setter(RequestResult.success({"status": True}))

    await controller._setUser_async("new", "newpass", "old", "oldpass")

    _, data = controller.requests[0]
    assert (data["currentUsername"], data["currentPassword"]) == ("old", "oldpass")


async def test_half_a_current_login_is_still_sent(password_setter):
    """Sunshine decides whether it needs the current credentials, and it
    answers a half-filled pair with an error the caller can act on. Dropping
    them here instead would turn that into a silent "password changed"."""
    controller = password_setter(RequestResult.success({"status": True}))

    await controller._setUser_async("new", "newpass", "old", "")

    _, data = controller.requests[0]
    assert data["currentUsername"] == "old"


async def test_a_refused_change_is_told_apart_from_no_answer(password_setter, logger):
    """_initSunshine retries on "no answer" and gives up on "refused" - so the
    two may not collapse into one falsy value."""
    controller = password_setter(RequestResult.success({"status": False}))

    assert await controller._setUser_async("user", "pass") is False
    assert controller.authHeader == "", "nothing was changed, so nothing is remembered"
    assert "User was not changed" in logger.errors


async def test_no_answer_at_all_is_none(password_setter, logger):
    controller = password_setter(RequestResult.failure(RequestError.UNREACHABLE))

    assert await controller._setUser_async("user", "pass") is None
    assert "No response received while setting user" in logger.errors, \
        "and not the same line as a refusal - the caller treats the two differently"


# --- pairing ------------------------------------------------------------------

@pytest.fixture
def no_sleep(monkeypatch):
    """The pause before the client list is re-read, recorded rather than
    dropped - it is the whole reason the second read sees anything."""
    slept = []

    async def instant(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", instant)
    return slept


@pytest.fixture
def pairer(bare_controller):
    """A controller whose client list and /api/pin call are scripted.

    clients is the named_certs list before the pairing, then after it.
    """

    def _make(clients, pin_result=None, list_fails=False, list_fails_after=False):
        states = list(clients)
        controller = bare_controller(requests=[])

        async def request(path, data=None):
            controller.requests.append((path, data))
            if path == "/api/clients/list":
                already_paired = any(p == "/api/pin" for p, _ in controller.requests)
                if list_fails or (list_fails_after and already_paired):
                    return RequestResult.failure(RequestError.UNREACHABLE)
                names = states.pop(0) if len(states) > 1 else states[0]
                return RequestResult.success({
                    "status": True,
                    "named_certs": [{"name": name} for name in names],
                })
            if path == "/api/pin":
                return pin_result if pin_result is not None else \
                    RequestResult.success({"status": True})
            raise AssertionError(f"unexpected path {path}")

        controller._request_async = request
        return controller

    return _make


async def test_a_client_that_appeared_counts_as_paired(pairer, no_sleep):
    controller = pairer([[], ["Living Room TV"]])

    assert await controller.pair_async("1234", "Living Room TV") is True
    assert no_sleep == [1], \
        "the list is re-read after a pause, or it still shows the state before the pairing"


async def test_a_client_list_that_did_not_change_is_not_a_pairing(pairer, no_sleep):
    """The bug this works around: /api/pin answers true for a pending request
    whatever PIN it was given."""
    controller = pairer([["Other"]])

    assert await controller.pair_async("9999", "Living Room TV") is False


async def test_a_second_device_with_the_same_name_is_recognised(pairer, no_sleep):
    """Client names are not unique - one more with that name is the signal,
    not the name being present."""
    controller = pairer([["TV"], ["TV", "TV"]])

    assert await controller.pair_async("1234", "TV") is True


async def test_a_pin_without_a_name_never_reaches_sunshine(pairer, logger):
    controller = pairer([[]])

    assert await controller.pair_async("1234", "") is False
    assert await controller.pair_async("", "TV") is False
    assert controller.requests == []
    assert "No pin or client name provided for pairing" in logger.infos


async def test_a_rejected_pin_is_reported_rather_than_verified(pairer, no_sleep, logger):
    controller = pairer([[], ["TV"]],
                        pin_result=RequestResult.success({"status": False}))

    assert await controller.pair_async("1234", "TV") is False
    assert "Failed to send PIN and client name to Sunshine" in logger.errors


async def test_a_client_list_that_cannot_be_read_stops_the_pairing(pairer, logger):
    """Without a count before, "one more afterwards" cannot be decided - and
    guessing would report a pairing that did not happen."""
    controller = pairer([[]], list_fails=True)

    assert await controller.pair_async("1234", "TV") is False
    assert controller.requests == [("/api/clients/list", None)]
    assert "Could not get client count before pairing" in logger.errors


async def test_the_pin_and_name_are_what_sunshine_gets(pairer, no_sleep):
    controller = pairer([[], ["TV"]])

    await controller.pair_async("1234", "TV")

    assert ("/api/pin", {"pin": "1234", "name": "TV"}) in controller.requests


async def test_a_client_list_without_a_status_is_no_answer(bare_controller):
    """Sunshine answers 200 with status false when it is not happy; treating
    that as an empty list would make every pairing look successful."""
    controller = bare_controller()

    async def request(path, data=None):
        return RequestResult.success({"status": False})

    controller._request_async = request

    assert await controller._getCountOfClientName_async("TV") is None


async def test_clients_with_other_names_are_not_counted(bare_controller):
    controller = bare_controller()

    async def request(path, data=None):
        return RequestResult.success({
            "status": True,
            "named_certs": [{"name": "TV"}, {"name": "Laptop"}, {"name": "TV"}],
        })

    controller._request_async = request

    assert await controller._getCountOfClientName_async("TV") == 2


async def test_a_client_list_that_dies_after_the_pin_is_not_a_pairing(pairer, no_sleep,
                                                                     logger):
    """Sunshine may well have taken the PIN, but we cannot see it - and the
    panel telling the user they are paired when they are not is worse than
    telling them to try again."""
    controller = pairer([[]], list_fails_after=True)

    assert await controller.pair_async("1234", "TV") is False
    assert "Could not get client count after pairing" in logger.errors
