"""``device_control`` — the person's own devices: list, wake, and power.

Three actions over the owned-device registry (:mod:`jarvis.devices`):

* ``list``  — the registered devices and what each may do. Read-only, ``safe``.
* ``wake``  — send a Wake-on-LAN magic packet to a registered device on the
  local network. Needs the device's ``wake_on_lan`` capability and a MAC
  address the person entered. ``monitor``: it cannot harm anything, and the
  result says "packet sent", never "the device is on".
* ``power`` — shut down, restart, sleep or lock THIS machine through the OS
  (never by cutting power), or cancel a pending shutdown. Shutdown, restart
  and sleep are ``ask``: the person confirms first through the normal
  two-turn confirmation. ``lock`` is ``monitor``; ``cancel`` is ``safe``.

Power for ANOTHER device is refused honestly: that needs the assistant running
on that device, and the reply says so instead of pretending.

Direct gated action, never a spawn — never in a worker tool set (AP-5/AP-14).
See ADR-0011 amendment "device-control tool".
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Any

from jarvis.core.protocols import ExecutionContext, ToolResult

log = logging.getLogger(__name__)

_ACTIONS = ("list", "wake", "power")
_POWER_OPS = ("shutdown", "restart", "sleep", "lock", "cancel")
_CONFIRMED_POWER_OPS = frozenset({"shutdown", "restart", "sleep"})


class DeviceControlTool:
    name: str = "device_control"
    read_only: bool = False
    risk_tier: str = "monitor"
    description: str = (
        "The user's own registered devices (desktop, laptop, phone, smart "
        "speaker, home hub). action='list' shows them and what each may do; "
        "action='wake' turns on a registered device over the local network "
        "(Wake-on-LAN); action='power' with op='shutdown'|'restart'|'sleep'|"
        "'lock'|'cancel' acts on THIS computer through the operating system. "
        "Shutdown and restart are scheduled with a short grace period so "
        "op='cancel' can still stop them."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS)},
            "device": {
                "type": "string",
                "description": (
                    "Device id or name for action='wake'. For action='power' "
                    "leave empty (this computer)."
                ),
                "default": "",
            },
            "op": {"type": "string", "enum": list(_POWER_OPS)},
            "delay_s": {
                "type": "integer",
                "description": "Grace period before shutdown/restart, seconds (0-3600).",
                "default": 60,
            },
        },
        "required": ["action"],
    }

    def __init__(self, *, registry: Any | None = None, runner: Any | None = None) -> None:
        # Both are seams for tests; production resolves the registry per call
        # so a changed data directory is honoured, and runs real OS commands.
        self._registry = registry
        self._runner = runner

    def risk_tier_for_args(self, args: dict[str, Any]) -> str | None:
        """``list`` reads; confirmed power ops ask; everything else keeps ``monitor``."""
        action = str(args.get("action") or "").strip().lower()
        if action == "list":
            return "safe"
        if action == "power":
            op = str(args.get("op") or "").strip().lower()
            if op in _CONFIRMED_POWER_OPS:
                return "ask"
            if op == "cancel":
                return "safe"
        return None

    def _registry_or_default(self) -> Any:
        if self._registry is not None:
            return self._registry
        from jarvis.devices.store import DeviceRegistry

        return DeviceRegistry()

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        del ctx
        action = str(args.get("action") or "").strip().lower()
        if action == "list":
            return self._list()
        if action == "wake":
            return await self._wake(str(args.get("device") or ""))
        if action == "power":
            return await self._power(args)
        return ToolResult(
            success=False, output=None, error=f"action must be one of {', '.join(_ACTIONS)}"
        )

    # -- actions -------------------------------------------------------------

    def _list(self) -> ToolResult:
        devices = self._registry_or_default().all()
        if not devices:
            return ToolResult(
                success=True,
                output=(
                    "No devices are registered yet. The user adds them with "
                    "`python -m jarvis.devices add`."
                ),
                error=None,
            )
        lines = []
        for device in devices:
            marker = " (this computer)" if device.this_machine else ""
            caps = ", ".join(device.capabilities) or "no permissions granted"
            lines.append(
                f"- {device.name} [{device.id}]{marker}: {device.kind}, {device.platform}; {caps}"
            )
        return ToolResult(success=True, output="\n".join(lines), error=None)

    async def _wake(self, query: str) -> ToolResult:
        from jarvis.devices.wol import LIMITED_BROADCAST, send_magic_packet

        if not query.strip():
            return ToolResult(success=False, output=None, error="Which device should be woken?")
        device = self._registry_or_default().find(query)
        if device is None:
            return ToolResult(
                success=False, output=None, error=f"No registered device matches {query!r}."
            )
        if not device.can("wake_on_lan"):
            return ToolResult(
                success=False,
                output=None,
                error=f"{device.name} is not allowed to be woken (no wake_on_lan permission).",
            )
        if not device.mac_address:
            return ToolResult(
                success=False,
                output=None,
                error=f"{device.name} has no MAC address registered, so it cannot be woken.",
            )
        address = device.wol_broadcast or LIMITED_BROADCAST
        try:
            result = await asyncio.to_thread(send_magic_packet, device.mac_address, address=address)
        except (OSError, ValueError) as exc:
            log.warning("device_control: wake packet for %s failed: %s", device.id, exc)
            return ToolResult(success=False, output=None, error=f"Wake packet not sent: {exc}")
        return ToolResult(
            success=True,
            output=(
                f"Wake-on-LAN packet sent to {device.name} ({result.mac}) via "
                f"{result.address}. It starts only if Wake-on-LAN is enabled in its "
                "firmware and network adapter; this does not confirm it is on."
            ),
            error=None,
        )

    async def _power(self, args: dict[str, Any]) -> ToolResult:
        from jarvis.devices.power import (
            DEFAULT_GRACE_S,
            PowerActionUnsupported,
            run_power_action,
        )

        op = str(args.get("op") or "").strip().lower()
        if op not in _POWER_OPS:
            return ToolResult(
                success=False, output=None, error=f"op must be one of {', '.join(_POWER_OPS)}"
            )
        query = str(args.get("device") or "").strip()
        if query:
            registry = self._registry_or_default()
            device = registry.find(query)
            if device is None:
                return ToolResult(
                    success=False, output=None, error=f"No registered device matches {query!r}."
                )
            if not device.this_machine:
                return ToolResult(
                    success=False,
                    output=None,
                    error=(
                        f"{device.name} is a different device. Power actions only "
                        "run on this computer until the assistant runs on that device too."
                    ),
                )
            if not device.can("power"):
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"{device.name} has no power permission in the device registry.",
                )
        try:
            delay_s = int(args.get("delay_s", DEFAULT_GRACE_S))
        except (TypeError, ValueError):  # a garbled delay falls back to the default grace
            delay_s = DEFAULT_GRACE_S
        try:
            result = await asyncio.to_thread(
                run_power_action, op, delay_s=delay_s, runner=self._runner
            )
        except PowerActionUnsupported as exc:  # surfaced to the user as the result
            return ToolResult(success=False, output=None, error=str(exc))
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("device_control: power %s failed to start: %s", op, exc)
            return ToolResult(success=False, output=None, error=f"{op} could not start: {exc}")
        if result.returncode != 0:
            detail = f": {result.output}" if result.output else ""
            return ToolResult(
                success=False,
                output=None,
                error=f"{op} failed (exit {result.returncode}){detail}",
            )
        if result.delay_s > 0:
            summary = f"{op} scheduled in about {result.delay_s} seconds; op='cancel' stops it."
        else:
            summary = f"{op} requested from the operating system."
        return ToolResult(success=True, output=summary, error=None)


__all__ = ["DeviceControlTool"]
