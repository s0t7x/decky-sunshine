"""The async wrappers around the blocking calls.

Everything the controller does that blocks - a subprocess, a socket, a file -
has an `_async` twin that runs it in the default executor, because the plugin
lives in the Decky loader's event loop and a blocked loop freezes the panel
along with every other plugin in it.

The wrappers are one-liners, and that is exactly why they are worth a test:
they all look alike, and a wrapper that forwards to the wrong twin, drops an
argument or returns the coroutine instead of awaiting it still reads correctly.
"""
import asyncio

import pytest

from sunshine import SunshineController


WRAPPERS = [
    # async method, the blocking method it has to reach, arguments
    ("isSunshineRunning_async", "isSunshineRunning", ()),
    # logEnvironment only writes to the log, so its wrapper has nothing to hand
    # back - it is in the list for the delegation, not for a return value
    ("logEnvironment_async", "logEnvironment", ()),
    ("isCsrfOriginAllowed_async", "isCsrfOriginAllowed", ("https://192.168.1.38:47990",)),
    ("ensureCsrfAllowedOrigin_async", "ensureCsrfAllowedOrigin", ("https://10.0.0.1:47990",)),
    ("setCompositionForce_async", "setCompositionForce", (True,)),
    ("getSunshineVersionInfo_async", "getSunshineVersionInfo", ()),
]

# _request_async reaches its twin through run_in_executor rather than
# _to_thread, because it has arguments to pass. What it forwards has its own
# two tests at the bottom; the loop check below applies to it just the same,
# and it is the wrapper behind every call the open panel polls.
OFF_THE_LOOP = WRAPPERS + [("_request_async", "_request", ("/api/apps",))]


@pytest.mark.parametrize("async_name, sync_name, args",
                         WRAPPERS, ids=[name for name, _, _ in WRAPPERS])
async def test_the_wrapper_reaches_its_blocking_twin(bare_controller, async_name,
                                                     sync_name, args):
    controller = bare_controller(calls=[])
    marker = object()

    def record(*received):
        controller.calls.append(received)
        return marker

    setattr(controller, sync_name, record)

    result = await getattr(controller, async_name)(*args)

    assert controller.calls == [args]
    if sync_name != "logEnvironment":
        assert result is marker


@pytest.mark.parametrize("async_name, sync_name, args",
                         OFF_THE_LOOP, ids=[name for name, _, _ in OFF_THE_LOOP])
async def test_the_wrapper_does_not_block_the_loop(bare_controller, async_name,
                                                   sync_name, args):
    """The blocking call runs off the event loop thread, so anything else the
    loop has to do keeps happening while it is in flight."""
    controller = bare_controller()
    started = asyncio.Event()
    loop = asyncio.get_running_loop()
    release = asyncio.Event()

    def blocking(*_args):
        loop.call_soon_threadsafe(started.set)
        # Waits on the loop, so the loop has to be running for this to return
        asyncio.run_coroutine_threadsafe(release.wait(), loop).result(timeout=5)
        return None

    setattr(controller, sync_name, blocking)
    call = asyncio.ensure_future(getattr(controller, async_name)(*args))

    await asyncio.wait_for(started.wait(), timeout=5)
    release.set()

    await asyncio.wait_for(call, timeout=5)


async def test_the_request_wrapper_forwards_path_and_data(bare_controller):
    """_request_async goes through run_in_executor directly rather than through
    _to_thread, because it has arguments to pass."""
    controller = bare_controller(calls=[])
    marker = object()

    def record(path, data=None):
        controller.calls.append((path, data))
        return marker

    controller._request = record

    assert await controller._request_async("/api/pin", {"pin": "1234"}) is marker
    assert controller.calls == [("/api/pin", {"pin": "1234"})]


async def test_the_request_wrapper_defaults_to_no_data(bare_controller):
    controller = bare_controller(calls=[])
    controller._request = lambda path, data=None: controller.calls.append((path, data))

    await controller._request_async("/api/apps")

    assert controller.calls == [("/api/apps", None)]
