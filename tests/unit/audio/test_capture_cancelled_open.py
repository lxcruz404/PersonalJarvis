"""A capture cancelled while its stream is opening must still close that stream.

Live crash on Windows/MME (two dumps, 0xc0000005 on the PortAudio thread): the
barge-in monitor opens a second capture while a reply plays. With no voice
configured the reply ended at once, the monitor was cancelled mid-open, and the
worker thread still returned a STARTED stream that nobody kept. sounddevice has
no finalizer that stops a stream, so dropping it freed the callback PortAudio
kept calling and the process died with no traceback.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from jarvis.audio import capture


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
        _SlowStream.instances.append(self)
        _SlowStream.created.set()

    def start(self) -> None:
        self.opening.set()
        assert self.release.wait(5.0), "test never released the open"
        self.started = True

    def abort(self) -> None:
        self.aborted = True

    def close(self) -> None:
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
    assert mic._stream is None


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
