"""Wake-on-LAN magic packet: exact bytes, LAN-only targets, a real send."""

from __future__ import annotations

import socket

import pytest

from jarvis.devices.wol import build_magic_packet, send_magic_packet


def test_magic_packet_layout() -> None:
    packet = build_magic_packet("01-23-45-67-89-ab")
    mac = bytes.fromhex("0123456789ab")
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == mac * 16


def test_send_reaches_a_local_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    from jarvis.devices import wol

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.settimeout(2.0)
        # Aim the real send path at an ephemeral loopback listener by allowing
        # that one port for this test; the packet and socket code are unchanged.
        port = listener.getsockname()[1]
        monkeypatch.setattr(wol, "ALLOWED_WOL_PORTS", frozenset({*wol.ALLOWED_WOL_PORTS, port}))
        result = send_magic_packet("AA:BB:CC:DD:EE:FF", address="127.0.0.1", port=port)
        data, _ = listener.recvfrom(1024)

    assert result.bytes_sent == 102
    assert result.mac == "AA:BB:CC:DD:EE:FF"
    assert data == build_magic_packet("AA:BB:CC:DD:EE:FF")


def test_send_refuses_an_internet_address() -> None:
    with pytest.raises(ValueError):
        send_magic_packet("AA:BB:CC:DD:EE:FF", address="8.8.8.8")


def test_send_refuses_a_non_wol_port() -> None:
    with pytest.raises(ValueError):
        send_magic_packet("AA:BB:CC:DD:EE:FF", address="127.0.0.1", port=22)


def test_send_refuses_a_malformed_mac() -> None:
    with pytest.raises(ValueError):
        send_magic_packet("nope", address="127.0.0.1")
