"""Wake-on-LAN: build and send the standard magic packet.

The packet is six ``0xFF`` bytes followed by the target's MAC address repeated
sixteen times (102 bytes), sent as one UDP datagram. It only reaches devices on
the same local network: the destination is validated by
:func:`jarvis.devices.models.validate_lan_target`, so this module never sends
anything toward the internet and never opens a listening port.

Whether the device actually powers on depends on its firmware and network
adapter settings (Wake-on-LAN enabled in BIOS/UEFI and in the adapter's power
management). Sending the packet succeeds either way; the caller reports it as
"sent", never as "the device is on".
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

from jarvis.devices.models import normalize_mac, validate_lan_target

#: The conventional Wake-on-LAN ports; 9 ("discard") is the common default.
DEFAULT_WOL_PORT = 9
ALLOWED_WOL_PORTS: frozenset[int] = frozenset({0, 7, 9})
LIMITED_BROADCAST = "255.255.255.255"


def build_magic_packet(mac: str) -> bytes:
    """Return the 102-byte magic packet for ``mac`` (any common MAC spelling)."""
    raw = bytes.fromhex(normalize_mac(mac).replace(":", ""))
    return b"\xff" * 6 + raw * 16


@dataclass(frozen=True)
class WakeResult:
    mac: str
    address: str
    port: int
    bytes_sent: int


def send_magic_packet(
    mac: str,
    *,
    address: str = LIMITED_BROADCAST,
    port: int = DEFAULT_WOL_PORT,
) -> WakeResult:
    """Send one magic packet for ``mac`` to ``address:port`` on the local network.

    Raises :class:`ValueError` for a malformed MAC, a non-local address or an
    unexpected port, and :class:`OSError` when the OS refuses the send.
    """
    normalized = normalize_mac(mac)
    target = validate_lan_target(address)
    if port not in ALLOWED_WOL_PORTS:
        raise ValueError(f"port {port} is not a Wake-on-LAN port")
    packet = build_magic_packet(normalized)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sent = sock.sendto(packet, (target, port))
    return WakeResult(mac=normalized, address=target, port=port, bytes_sent=sent)


__all__ = [
    "ALLOWED_WOL_PORTS",
    "DEFAULT_WOL_PORT",
    "LIMITED_BROADCAST",
    "WakeResult",
    "build_magic_packet",
    "send_magic_packet",
]
