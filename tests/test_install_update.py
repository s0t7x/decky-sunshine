"""Getting Sunshine installed, initialised and updated.

Everything here runs before there is a Sunshine to talk to, which is what makes
it easy to get wrong: a half-finished install looks exactly like a working one
from the panel, and the plugin's own credentials are created exactly once - if
that step is skipped or its failure swallowed, the user is left with a Sunshine
they cannot log into and no way back short of reinstalling.

A) ensureDependencies_async - the bwrap copy and the installation, in that order
B) _initSunshine - the credentials a fresh installation gets
C) updateSunshine_async - stop, update, start, and what each failure costs
"""
import asyncio

import pytest

import sunshine as sunshine_module
from sunshine import SunshineController


@pytest.fixture
def no_sleep(monkeypatch):
    """The retry delay, recorded rather than dropped: how long the web server
    is given is as much the subject as how often it is asked."""
    slept = []

    async def instant(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", instant)
    return slept


# --- A) dependencies ---------------------------------------------------------

@pytest.fixture
def dependencies(bare_controller):
    """A controller with the four steps of ensureDependencies_async scripted."""

    def _make(copied=True, copy_succeeds=True, installed=True,
              install_succeeds=True, init_succeeds=True):
        controller = bare_controller(steps=[])

        def wasCopied():
            controller.steps.append("was-copied")
            return copied

        def copyBwrap():
            controller.steps.append("copy")
            return copy_succeeds

        def isInstalled():
            controller.steps.append("is-installed")
            return installed

        def install():
            controller.steps.append("install")
            return install_succeeds

        async def init():
            controller.steps.append("init")
            return init_succeeds

        controller._wasBwrapCopied = wasCopied
        controller._copyBwrap = copyBwrap
        controller._isSunshineInstalled = isInstalled
        controller._installOrUpdateSunshine = install
        controller._initSunshine = init
        return controller

    return _make


async def test_a_prepared_system_needs_nothing_done(dependencies, logger):
    controller = dependencies()

    assert await controller.ensureDependencies_async() is True
    assert controller.steps == ["was-copied", "is-installed"]
    assert "Decky Sunshine's copy of bwrap was already obtained." in logger.infos


async def test_a_missing_bwrap_copy_is_obtained(dependencies, logger):
    controller = dependencies(copied=False)

    assert await controller.ensureDependencies_async() is True
    assert controller.steps == ["was-copied", "copy", "is-installed"]
    assert "Decky Sunshine's copy of bwrap is missing. Obtaining now..." in logger.infos
    assert "Decky Sunshine's copy of bwrap obtained successfully." in logger.infos
    assert "Sunshine already installed." in logger.infos


async def test_without_the_bwrap_copy_nothing_else_is_attempted(dependencies, logger):
    """Sunshine cannot capture without the setuid copy, so installing it would
    only produce a Sunshine that fails later and less clearly."""
    controller = dependencies(copied=False, copy_succeeds=False)

    assert await controller.ensureDependencies_async() is False
    assert controller.steps == ["was-copied", "copy"]
    assert "Decky Sunshine's copy of bwrap could not be obtained." in logger.errors


async def test_a_missing_sunshine_is_installed_and_initialised(dependencies, logger):
    controller = dependencies(installed=False)

    assert await controller.ensureDependencies_async() is True
    assert controller.steps == ["was-copied", "is-installed", "install", "init"]
    assert "Sunshine not installed. Installing..." in logger.infos
    assert "Sunshine was installed successfully." in logger.infos


async def test_a_failed_installation_is_not_initialised(dependencies, logger):
    controller = dependencies(installed=False, install_succeeds=False)

    assert await controller.ensureDependencies_async() is False
    assert "init" not in controller.steps
    assert "Sunshine could not be installed." in logger.errors


async def test_a_failed_initialisation_fails_the_whole_setup(dependencies):
    """The installation worked but there are no credentials - reporting success
    would leave the panel offering a login nobody can pass."""
    controller = dependencies(installed=False, init_succeeds=False)

    assert await controller.ensureDependencies_async() is False


async def test_an_installed_sunshine_is_not_re_initialised(dependencies):
    """_initSunshine overwrites the credentials, so running it on an existing
    installation would lock the user out of their own Sunshine."""
    controller = dependencies(installed=True)

    await controller.ensureDependencies_async()

    assert "init" not in controller.steps
    assert "install" not in controller.steps


def test_the_installation_check_matches_the_whole_app_id(bare_controller):
    """`flatpak list` is matched line by line: a substring match would let
    another app whose id merely contains ours pass for Sunshine."""
    controller = bare_controller()
    controller._run_and_capture_stdout = lambda args, context=None: (
        "dev.lizardbyte.app.SunshineExtra\ncom.heroicgameslauncher.hgl\n")

    assert controller._isSunshineInstalled() is False


def test_the_installation_check_finds_sunshine(bare_controller):
    controller = bare_controller(queries=[])

    def capture(args, context=None):
        controller.queries.append((list(args), context))
        return f"com.valvesoftware.Steam\n  {SunshineController.SunshineFlatpakAppId}  \n"

    controller._run_and_capture_stdout = capture

    assert controller._isSunshineInstalled() is True
    # --system because the install goes there, --columns=application because
    # the match below is line-by-line and flatpak otherwise prints a table.
    assert controller.queries == [
        (["flatpak", "list", "--system", "--columns=application"],
         "checking whether Sunshine is installed"),
    ]


def test_a_failed_list_call_is_not_an_installation(bare_controller):
    controller = bare_controller()
    controller._run_and_capture_stdout = lambda args, context=None: None

    assert controller._isSunshineInstalled() is False


def test_the_install_is_noninteractive_and_also_updates(bare_controller):
    """It is the update path too, and nothing here can answer a prompt."""
    controller = bare_controller(commands=[], contexts=[])

    def check(args, context=None):
        controller.commands.append(list(args))
        controller.contexts.append(context)
        return True

    controller._run_and_check = check

    assert controller._installOrUpdateSunshine() is True
    assert controller.commands == [[
        "flatpak", "install", "--system", "--noninteractive", "--or-update",
        SunshineController.SunshineFlatpakAppId]]
    assert controller.contexts == ["installing or updating Sunshine via Flatpak"], \
        "an install that fails leaves nothing behind but this line"


# --- B) the credentials a fresh installation gets ----------------------------

@pytest.fixture
def initialise(bare_controller):
    """A controller whose start and password call are scripted.

    A list of answers gives one per call, with the last repeating - that is
    what lets a test drive the retry loop from a single value.
    """

    def _make(started=True, set_user=True):
        answers = list(set_user) if isinstance(set_user, list) else [set_user]
        controller = bare_controller(set_user_calls=[])

        async def start():
            return started

        async def setUser(username, password):
            controller.set_user_calls.append((username, password))
            index = len(controller.set_user_calls) - 1
            return answers[index] if index < len(answers) else answers[-1]

        controller.start_async = start
        controller._setUser_async = setUser
        return controller

    return _make


async def test_a_fresh_installation_gets_its_own_credentials(initialise, logger):
    controller = initialise()

    assert await controller._initSunshine() is True
    username, password = controller.set_user_calls[0]
    assert username == "decky_sunshine"
    assert len(password) == 8, \
        "token_urlsafe(6) - pinned exactly, because \">= 8\" also accepts a shorter " \
        "request that happened to round up, and the number is the entropy"
    # This runs once, unattended, right after the install; if it goes wrong
    # the user has a Sunshine they cannot log into and no other account of it.
    assert "Starting Sunshine after fresh installation" in logger.infos
    assert "Setting initial credentials" in logger.infos


async def test_the_password_is_not_the_same_on_two_machines(initialise):
    """A fixed one would be a published default password on a service that is
    reachable from the LAN."""
    first = initialise()
    second = initialise()

    await first._initSunshine()
    await second._initSunshine()

    assert first.set_user_calls[0][1] != second.set_user_calls[0][1]


async def test_a_sunshine_that_will_not_start_is_not_initialised(initialise, logger):
    controller = initialise(started=False)

    assert await controller._initSunshine() is False
    assert controller.set_user_calls == []
    assert "Sunshine could not be started after installation" in logger.errors


async def test_a_web_server_that_is_not_up_yet_is_waited_out(initialise, no_sleep):
    """None means no answer at all - Sunshine is running but its Web UI has not
    finished coming up. That is the normal case right after an install."""
    controller = initialise(set_user=[None, None, True])

    assert await controller._initSunshine() is True
    assert len(controller.set_user_calls) == 3


async def test_a_refused_password_change_is_not_retried(initialise, logger):
    """False is Sunshine answering "no" - retrying nineteen more times would
    not change its mind and only delays the error the user needs to see."""
    controller = initialise(set_user=False)

    assert await controller._initSunshine() is False
    assert len(controller.set_user_calls) == 1
    assert "Setting initial credentials failed" in logger.errors


async def test_the_wait_for_the_web_server_is_bounded(initialise, no_sleep, logger):
    slept = no_sleep
    controller = initialise(set_user=None)

    assert await controller._initSunshine() is False
    assert len(controller.set_user_calls) == 20
    assert slept == [0.25] * 19, "quarter-second steps, so about five seconds in all"
    assert "Initial credentials could not be set" in logger.errors
    assert "Setting initial credentials failed. Trying again in 0.25 seconds" in logger.infos


async def test_the_credentials_end_up_in_the_log(initialise, logger):
    """Deliberate: it is the only record of a password the user never chose,
    and the only way back into their Sunshine if the panel loses it."""
    controller = initialise()

    await controller._initSunshine()

    assert any("Initial credentials set successfully" in line for line in logger.infos)


# --- C) the update -----------------------------------------------------------

@pytest.fixture
def updater(bare_controller):
    def _make(stopped=True, installed=True, started=True):
        controller = bare_controller(steps=[])

        async def stop():
            controller.steps.append("stop")
            return stopped

        def install():
            controller.steps.append("install")
            return installed

        async def start():
            controller.steps.append("start")
            return started

        controller.stop_async = stop
        controller._installOrUpdateSunshine = install
        controller.start_async = start
        return controller

    return _make


async def test_an_update_stops_installs_and_starts_again(updater, logger):
    controller = updater()

    assert await controller.updateSunshine_async() is True
    assert controller.steps == ["stop", "install", "start"]
    assert "Sunshine started after update" in logger.infos


async def test_a_sunshine_that_will_not_stop_is_not_updated(updater, logger):
    """flatpak cannot replace the files of a running instance, and the panel
    keys its "restart to finish" hint off this return value."""
    controller = updater(stopped=False)

    assert await controller.updateSunshine_async() is False
    assert controller.steps == ["stop"]
    assert "Couldn't stop Sunshine for update" in logger.errors


async def test_a_failed_update_does_not_start_the_old_instance_back_up(updater, logger):
    """It is stopped and half-updated; starting it would hide the failure
    behind a Sunshine that looks fine until it does not."""
    controller = updater(installed=False)

    assert await controller.updateSunshine_async() is False
    assert controller.steps == ["stop", "install"]
    assert "Sunshine stopped for update. Installing update now..." in logger.infos
    assert "Couldn't update Sunshine" in logger.errors


async def test_an_update_that_installed_but_will_not_start_reports_failure(updater, logger):
    controller = updater(started=False)

    assert await controller.updateSunshine_async() is False
    assert "Sunshine updated successfully. Starting Sunshine now..." in logger.infos
    assert "Couldn't start Sunshine after update" in logger.errors
