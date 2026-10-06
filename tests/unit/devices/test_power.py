"""OS power commands: one fixed argv per OS, honest about what each can do."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

import pytest

from jarvis.devices.power import (
    PowerActionUnsupported,
    os_family,
    plan_power_command,
    run_power_action,
    scheduled_delay_s,
)


@pytest.mark.parametrize(
    "platform,family",
    [("win32", "windows"), ("darwin", "macos"), ("linux", "linux"), ("freebsd14", "other")],
)
def test_os_family(platform: str, family: str) -> None:
    assert os_family(platform) == family


def test_windows_commands_schedule_with_grace() -> None:
    assert plan_power_command("shutdown", platform="win32", delay_s=60) == (
        "shutdown.exe",
        "/s",
        "/t",
        "60",
    )
    assert plan_power_command("restart", platform="win32", delay_s=0) == (
        "shutdown.exe",
        "/r",
        "/t",
        "0",
    )
    assert plan_power_command("cancel", platform="win32") == ("shutdown.exe", "/a")
    assert plan_power_command("lock", platform="win32") == (
        "rundll32.exe",
        "user32.dll,LockWorkStation",
    )
    sleep = plan_power_command("sleep", platform="win32")
    assert sleep[0] == "powershell.exe" and "SetSuspendState" in sleep[-1]


def test_grace_is_clamped() -> None:
    assert plan_power_command("shutdown", platform="win32", delay_s=-5)[-1] == "0"
    assert plan_power_command("shutdown", platform="win32", delay_s=99999)[-1] == "3600"


def test_linux_rounds_grace_up_to_whole_minutes() -> None:
    assert plan_power_command("shutdown", platform="linux", delay_s=30) == ("shutdown", "-h", "+1")
    assert plan_power_command("restart", platform="linux", delay_s=121) == ("shutdown", "-r", "+3")
    assert plan_power_command("shutdown", platform="linux", delay_s=0) == ("shutdown", "-h", "now")
    assert scheduled_delay_s("shutdown", platform="linux", delay_s=30) == 60


def test_macos_acts_immediately_and_cannot_cancel() -> None:
    assert plan_power_command("sleep", platform="darwin") == ("pmset", "sleepnow")
    assert scheduled_delay_s("shutdown", platform="darwin", delay_s=60) == 0
    with pytest.raises(PowerActionUnsupported):
        plan_power_command("cancel", platform="darwin")


def test_unknown_action_and_platform() -> None:
    with pytest.raises(ValueError):
        plan_power_command("explode", platform="win32")
    with pytest.raises(PowerActionUnsupported):
        plan_power_command("shutdown", platform="freebsd14")


def test_no_command_cuts_power_or_runs_through_a_shell() -> None:
    for platform in ("win32", "linux", "darwin"):
        for action in ("shutdown", "restart", "sleep", "lock", "cancel"):
            try:
                argv = plan_power_command(action, platform=platform)
            except PowerActionUnsupported:
                continue
            joined = " ".join(argv).lower()
            assert "/p" not in argv  # Windows "power off now, no warning"
            assert argv[0] not in ("sh", "bash", "cmd", "cmd.exe")
            assert "-f" not in argv and "/f" not in argv  # never force-close apps
            assert joined


class RecordingRunner:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.calls: list[tuple[str, ...]] = []
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(argv))
        return subprocess.CompletedProcess(list(argv), self.returncode, "", self.stderr)


def test_run_power_action_runs_exactly_the_planned_argv() -> None:
    runner = RecordingRunner()
    result = run_power_action("restart", platform="win32", delay_s=45, runner=runner)
    assert runner.calls == [("shutdown.exe", "/r", "/t", "45")]
    assert result.returncode == 0 and result.delay_s == 45


def test_run_power_action_reports_failure_output() -> None:
    runner = RecordingRunner(
        returncode=1190, stderr="A system shutdown has already been scheduled."
    )
    result = run_power_action("shutdown", platform="win32", runner=runner)
    assert result.returncode == 1190
    assert "already been scheduled" in result.output
