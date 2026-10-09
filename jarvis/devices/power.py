"""Power actions for THIS machine through the operating system's own commands.

Shut down, restart, sleep, lock, and cancel a pending shutdown — always by
asking the OS, never by cutting power. Each action maps to one fixed argv per
OS (no shell, no user text interpolated), so the command that runs is exactly
the one listed in :func:`plan_power_command`.

Shutdown and restart on Windows and Linux are scheduled with a grace delay so
the person can still say "cancel"; macOS has no unprivileged delayed shutdown,
so there the action happens right away and ``cancel`` is reported as
unsupported rather than pretending to work.

Every spawn passes ``NO_WINDOW_CREATIONFLAGS`` (AP-1) and decodes output as
UTF-8 (Windows defaults to cp1252).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS

PowerAction = Literal["shutdown", "restart", "sleep", "lock", "cancel"]
POWER_ACTIONS: tuple[str, ...] = ("shutdown", "restart", "sleep", "lock", "cancel")

#: Seconds between the request and a scheduled shutdown/restart.
DEFAULT_GRACE_S = 60
MAX_GRACE_S = 3600
_RUN_TIMEOUT_S = 15.0

#: Windows: suspend (not hibernate) through the .NET forms API, which honours
#: the request even when hibernation is enabled, unlike rundll32 powrprof.
_WINDOWS_SLEEP = (
    "powershell.exe",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    "Add-Type -AssemblyName System.Windows.Forms; "
    "[void][System.Windows.Forms.Application]::SetSuspendState("
    "[System.Windows.Forms.PowerState]::Suspend, $false, $false)",
)


class PowerActionUnsupported(RuntimeError):
    """The action has no OS command on this platform."""


def os_family(platform: str | None = None) -> str:
    """``windows`` | ``macos`` | ``linux`` | ``other`` for ``sys.platform``-style input."""
    name = (platform or sys.platform).lower()
    if name.startswith("win"):
        return "windows"
    if name == "darwin":
        return "macos"
    if name.startswith("linux"):
        return "linux"
    return "other"


def _grace(delay_s: int) -> int:
    return max(0, min(MAX_GRACE_S, int(delay_s)))


def plan_power_command(
    action: str,
    *,
    platform: str | None = None,
    delay_s: int = DEFAULT_GRACE_S,
) -> tuple[str, ...]:
    """Return the argv that performs ``action`` on ``platform``.

    Raises :class:`ValueError` for an unknown action and
    :class:`PowerActionUnsupported` when the OS has no command for it.
    """
    if action not in POWER_ACTIONS:
        raise ValueError(f"unknown power action: {action!r}")
    family = os_family(platform)
    grace = _grace(delay_s)

    if family == "windows":
        return {
            "shutdown": ("shutdown.exe", "/s", "/t", str(grace)),
            "restart": ("shutdown.exe", "/r", "/t", str(grace)),
            "sleep": _WINDOWS_SLEEP,
            "lock": ("rundll32.exe", "user32.dll,LockWorkStation"),
            "cancel": ("shutdown.exe", "/a"),
        }[action]

    if family == "linux":
        # ``shutdown`` takes whole minutes; round a grace delay up so a request
        # for "in 30 seconds" never fires sooner than asked.
        minutes = 0 if grace == 0 else max(1, -(-grace // 60))
        when = "now" if minutes == 0 else f"+{minutes}"
        return {
            "shutdown": ("shutdown", "-h", when),
            "restart": ("shutdown", "-r", when),
            "sleep": ("systemctl", "suspend"),
            "lock": ("loginctl", "lock-session"),
            "cancel": ("shutdown", "-c"),
        }[action]

    if family == "macos":
        if action == "cancel":
            raise PowerActionUnsupported("macOS has no pending shutdown to cancel")
        return {
            "shutdown": ("osascript", "-e", 'tell application "System Events" to shut down'),
            "restart": ("osascript", "-e", 'tell application "System Events" to restart'),
            "sleep": ("pmset", "sleepnow"),
            "lock": ("pmset", "displaysleepnow"),
        }[action]

    raise PowerActionUnsupported(f"no power commands for platform {platform or sys.platform!r}")


def scheduled_delay_s(
    action: str, *, platform: str | None = None, delay_s: int = DEFAULT_GRACE_S
) -> int:
    """Seconds until ``action`` takes effect as planned; 0 means immediately."""
    if action not in ("shutdown", "restart"):
        return 0
    family = os_family(platform)
    grace = _grace(delay_s)
    if family == "windows":
        return grace
    if family == "linux":
        return 0 if grace == 0 else max(1, -(-grace // 60)) * 60
    return 0


@dataclass(frozen=True)
class PowerResult:
    action: str
    argv: tuple[str, ...]
    returncode: int
    output: str
    #: Seconds until the action takes effect; 0 means it was immediate.
    delay_s: int = 0


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed argv from plan_power_command, no shell
        list(argv),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_RUN_TIMEOUT_S,
        check=False,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )


def run_power_action(
    action: str,
    *,
    platform: str | None = None,
    delay_s: int = DEFAULT_GRACE_S,
    runner: Runner | None = None,
) -> PowerResult:
    """Plan and run ``action``; the caller is responsible for confirmation.

    Raises the same errors as :func:`plan_power_command`, plus
    :class:`OSError` / :class:`subprocess.TimeoutExpired` from the spawn.
    """
    argv = plan_power_command(action, platform=platform, delay_s=delay_s)
    completed = (runner or _default_runner)(argv)
    output = "\n".join(
        part.strip() for part in (completed.stdout or "", completed.stderr or "") if part.strip()
    )
    return PowerResult(
        action=action,
        argv=argv,
        returncode=int(completed.returncode),
        output=output[:2000],
        delay_s=scheduled_delay_s(action, platform=platform, delay_s=delay_s),
    )


__all__ = [
    "DEFAULT_GRACE_S",
    "MAX_GRACE_S",
    "POWER_ACTIONS",
    "PowerAction",
    "PowerActionUnsupported",
    "PowerResult",
    "os_family",
    "plan_power_command",
    "run_power_action",
    "scheduled_delay_s",
]
