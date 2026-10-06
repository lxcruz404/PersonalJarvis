"""Records for the user's own devices and what each one can do.

One :class:`OwnedDevice` per device the person owns and wants the assistant to
know about: this desktop, a laptop, a phone, a smart speaker, a home hub. It is
plain, user-declared data. Nothing here probes a network or guesses a value: a
MAC address or broadcast address only exists when the person typed it, and a
capability only exists when the person granted it.

Distinct from :mod:`jarvis.computers`, which holds machines Jarvis logs into
over SSH. A device here may never accept a login at all (a smart speaker), and
the registry is what a later per-device agent announces itself against.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: What kind of device it is, for display and defaults.
DeviceKind = Literal["desktop", "laptop", "phone", "smart_speaker", "home_hub", "other"]

#: The operating system or platform the device runs.
DevicePlatform = Literal["windows", "macos", "linux", "ios", "android", "alexa", "other"]

#: How the assistant reaches the device. ``local_agent`` is a Personal Jarvis
#: install running on that device; ``none`` is a device the assistant can only
#: act on from outside (for example, waking it over the network).
DeviceEndpoint = Literal["local_agent", "alexa", "iphone", "home_assistant", "none"]

#: Closed capability vocabulary. A capability is a permission the person gave,
#: not a claim that the device supports it; actions check both.
DEVICE_CAPABILITIES: tuple[str, ...] = (
    "wake_on_lan",  # may be woken with a magic packet (needs mac_address)
    "power",  # may be shut down / restarted / put to sleep / locked by the OS
    "apps",  # may open and control applications
    "files",  # may read and write files and folders
    "shell",  # may run shell commands
    "dev_tools",  # editors, build tools, git
    "coding_agents",  # may run coding-agent CLIs
    "voice",  # has a microphone/speaker the assistant uses
    "smart_home",  # controls smart-home devices
    "notifications",  # may receive notifications from the assistant
)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_MAC_HEX_RE = re.compile(r"^[0-9a-f]{12}$")


def normalize_mac(value: str) -> str:
    """Return ``value`` as ``AA:BB:CC:DD:EE:FF`` or raise :class:`ValueError`.

    Accepts the common spellings (``aa:bb:..``, ``AA-BB-..``, ``aabb.ccdd.eeff``,
    bare hex). Rejects anything that is not exactly six bytes.
    """
    compact = re.sub(r"[:\-.\s]", "", str(value or "")).lower()
    if not _MAC_HEX_RE.match(compact):
        raise ValueError(f"not a MAC address: {value!r}")
    return ":".join(compact[i : i + 2] for i in range(0, 12, 2)).upper()


def validate_lan_target(value: str) -> str:
    """Return ``value`` if it is an IPv4 address that stays on the local network.

    Allowed: private ranges (including their directed broadcast, e.g.
    ``192.168.1.255``), the limited broadcast ``255.255.255.255``, and loopback.
    A publicly routable address is refused so a wake packet is never aimed at
    the internet.
    """
    text = str(value or "").strip()
    try:
        addr = ipaddress.IPv4Address(text)
    except ValueError as exc:
        raise ValueError(f"not an IPv4 address: {value!r}") from exc
    if addr == ipaddress.IPv4Address("255.255.255.255"):
        return text
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return text
    raise ValueError(f"{value!r} is not a local-network address")


class OwnedDevice(BaseModel):
    """One device the person owns."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str = Field(min_length=1, max_length=80)
    kind: DeviceKind = "other"
    platform: DevicePlatform = "other"
    endpoint: DeviceEndpoint = "none"
    #: True for the device this Personal Jarvis install runs on.
    this_machine: bool = False
    mac_address: str | None = None
    #: Where the wake packet goes. Defaults to the limited broadcast.
    wol_broadcast: str | None = None
    capabilities: tuple[str, ...] = ()
    notes: str = Field(default="", max_length=500)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        text = str(value or "").strip().lower()
        if not _ID_RE.match(text):
            raise ValueError("id must be 1-48 chars of a-z, 0-9, '-' or '_'")
        return text

    @field_validator("mac_address")
    @classmethod
    def _check_mac(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        return normalize_mac(value)

    @field_validator("wol_broadcast")
    @classmethod
    def _check_broadcast(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        return validate_lan_target(value)

    @field_validator("capabilities", mode="before")
    @classmethod
    def _check_capabilities(cls, value: object) -> tuple[str, ...]:
        items = [str(item).strip().lower() for item in (value or ())]
        unknown = sorted({item for item in items if item not in DEVICE_CAPABILITIES})
        if unknown:
            raise ValueError(f"unknown capabilities: {', '.join(unknown)}")
        # Keep the vocabulary's order so the stored file is stable.
        return tuple(cap for cap in DEVICE_CAPABILITIES if cap in items)

    def can(self, capability: str) -> bool:
        """True when the person granted ``capability`` to this device."""
        return capability in self.capabilities


__all__ = [
    "DEVICE_CAPABILITIES",
    "DeviceEndpoint",
    "DeviceKind",
    "DevicePlatform",
    "OwnedDevice",
    "normalize_mac",
    "validate_lan_target",
]
