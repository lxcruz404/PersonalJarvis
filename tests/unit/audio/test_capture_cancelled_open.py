"""A capture cancelled while its stream is opening must still close that stream.

Live crash on Windows/MME (two dumps, 0xc0000005 on the PortAudio thread): the
barge-in monitor opens a second capture while a reply plays. With no voice
configured the reply ended at once, the monitor was cancelled mid-open, and the
worker thread still returned a STARTED stream that nobody kept. sounddevice has
no finalizer that stops a stream, so dropping it freed the callback PortAudio
kept calling and the process died with no traceback. The same drop happens when
a loop teardown cancels the open's own task, so the close may not depend on the
asyncio side receiving the result.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from jarvis.audio import capture


def _open_guard_held() -> bool:
    """Whether some thread holds the PortAudio open guard right now."""
    held: list[bool] = []

    def _probe() -> None:
        guard = capture.topology.stream_open_guard()
        acquired = guard.acquire(blocking=False)
        if acquired:
            guard.release()
        held.append(not acquired)

    probe = threading.Thread(target=_probe)
    probe.start()
    probe.join()
    return held[0]


class _SlowStream:
    """An ``InputStream`` whose ``start`` blocks until the test releases it."""

    instances: list[_SlowStream] = []
    created = threading.Event()

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.opening = threading.Event()
        self.release = threading.Event()
        self.started = False
        self.aborted = False
        self.closed = threading.Event()
        self.closed_under_guard = False
        _SlowStream.instances.append(self)
        _SlowStream.created.set()

    def start(self) -> None:
        self.opening.set()
        assert self.release.wait(5.0), "test never released the open"
        self.started = True

    def abort(self) -> None:
        self.aborted = True

    def close(self) -> None:
        self.closed_under_guard = _open_guard_held()
        self.closed.set()


@pytest.fixture
def slow_stream(monkeypatch: pytest.MonkeyPatch) -> type[_SlowStream]:
    _SlowStream.instances = []
    _SlowStream.created = threading.Event()
    monkeypatch.setattr(capture, "_fallback_input_devices", lambda _device: [])
    # A stand-in module, so the test also runs where PortAudio is absent.
    monkeypatch.setattr(capture, "sd", SimpleNamespace(InputStream=_SlowStream))
    return _SlowStream


async def _wait_until(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 5.0)


@pytest.mark.asyncio
async def test_cancel_during_open_closes_the_started_stream(
    slow_stream: type[_SlowStream],
) -> None:
    mic = capture.MicrophoneCapture(device=3, access_gate=lambda: True)
    opener = asyncio.create_task(mic.__aenter__())
    await _wait_until(slow_stream.created)
    stream = slow_stream.instances[0]
    await _wait_until(stream.opening)

    opener.cancel()
    await asyncio.sleep(0)
    stream.release.set()
    with pytest.raises(asyncio.CancelledError):
        await opener

    await _wait_until(stream.closed)
    assert stream.started
    assert stream.aborted
    # Closed before the guard was released: a hot-swap re-init waiting on the
    # guard can never terminate PortAudio while this stream is alive.
    assert stream.closed_under_guard
    assert mic._stream is None


@pytest.mark.asyncio
async def test_cancel_as_the_open_finishes_still_closes_the_stream(
    slow_stream: type[_SlowStream],
) -> None:
    mic = capture.MicrophoneCapture(device=3, access_gate=lambda: True)
    opener = asyncio.create_task(mic.__aenter__())
    await _wait_until(slow_stream.created)
    stream = slow_stream.instances[0]
    await _wait_until(stream.opening)

    stream.release.set()
    opener.cancel()
    with pytest.raises(asyncio.CancelledError):
        await opener

    await _wait_until(stream.closed)
    assert stream.aborted
    assert mic._stream is None


def test_a_loop_teardown_mid_open_closes_the_started_stream(
    slow_stream: type[_SlowStream],
) -> None:
    """``asyncio.run`` cancels the open's own task too and drops its result."""
    pending: list[asyncio.Task[capture.MicrophoneCapture]] = []

    async def _main() -> None:
        mic = capture.MicrophoneCapture(device=3, access_gate=lambda: True)
        pending.append(asyncio.create_task(mic.__aenter__()))
        await _wait_until(slow_stream.created)
        await _wait_until(slow_stream.instances[0].opening)
        # Returning now makes asyncio.run cancel every task still pending,
        # then wait for the executor; the open finishes during that wait.
        threading.Timer(0.2, slow_stream.instances[0].release.set).start()

    asyncio.run(_main())

    stream = slow_stream.instances[0]
    assert stream.closed.wait(5.0)
    assert stream.started
    assert stream.aborted
    assert pending[0].cancelled()


@pytest.mark.asyncio
async def test_an_uncancelled_open_keeps_its_stream(
    slow_stream: type[_SlowStream],
) -> None:
    mic = capture.MicrophoneCapture(device=3, access_gate=lambda: True)
    mic._loop = asyncio.get_running_loop()
    opener = asyncio.create_task(mic._try_open_stream())
    await _wait_until(slow_stream.created)
    stream = slow_stream.instances[0]
    stream.release.set()
    await opener

    assert mic._stream is stream
    assert not stream.aborted
    assert not stream.closed.is_set()
