"""The device-control tool: per-call risk tiers and honest refusals."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import pytest

from jarvis.core.protocols import ExecutionContext
from jarvis.devices.models import OwnedDevice
from jarvis.devices.store import DeviceRegistry
from jarvis.plugins.tool.device_control import DeviceControlTool


def _ctx() -> ExecutionContext:
    return ExecutionContext(trace_id=uuid4(), user_utterance="", config={}, memory_read=None)


class RecordingRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.returncode = returncode

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(argv))
        return subprocess.CompletedProcess(list(argv), self.returncode, "", "")


@pytest.fixture
def registry(tmp_path: Path) -> DeviceRegistry:
    reg = DeviceRegistry(tmp_path / "devices.json")
    reg.upsert(
        OwnedDevice(
            id="desktop",
            name="Desktop PC",
            kind="desktop",
            platform="windows",
            endpoint="local_agent",
            this_machine=True,
            capabilities=["power", "apps"],
        )
    )
    reg.upsert(
        OwnedDevice(
            id="omen",
            name="HP OMEN",
            kind="laptop",
            platform="windows",
            mac_address="AA:BB:CC:DD:EE:FF",
            wol_broadcast="127.0.0.1",
            capabilities=["wake_on_lan", "power"],
        )
    )
    reg.upsert(OwnedDevice(id="echo", name="Echo Dot", kind="smart_speaker", platform="alexa"))
    return reg


@pytest.mark.parametrize(
    "args,tier",
    [
        ({"action": "list"}, "safe"),
        ({"action": "wake", "device": "omen"}, None),
        ({"action": "power", "op": "shutdown"}, "ask"),
        ({"action": "power", "op": "restart"}, "ask"),
        ({"action": "power", "op": "sleep"}, "ask"),
        ({"action": "power", "op": "lock"}, None),
        ({"action": "power", "op": "cancel"}, "safe"),
    ],
)
def test_risk_tiers(args: dict[str, str], tier: str | None) -> None:
    tool = DeviceControlTool()
    assert tool.risk_tier == "monitor"
    assert tool.risk_tier_for_args(args) == tier


def test_tool_satisfies_the_tool_protocol() -> None:
    from jarvis.core.protocols import Tool

    assert isinstance(DeviceControlTool(), Tool)


async def test_list_shows_devices_and_permissions(registry: DeviceRegistry) -> None:
    result = await DeviceControlTool(registry=registry).execute({"action": "list"}, _ctx())
    assert result.success
    assert "Desktop PC [desktop] (this computer)" in result.output
    assert "HP OMEN [omen]" in result.output
    assert "no permissions granted" in result.output


async def test_list_on_an_empty_registry_explains_how_to_add(tmp_path: Path) -> None:
    tool = DeviceControlTool(registry=DeviceRegistry(tmp_path / "none.json"))
    result = await tool.execute({"action": "list"}, _ctx())
    assert result.success and "python -m jarvis.devices add" in result.output


async def test_wake_sends_a_packet_and_does_not_claim_the_device_is_on(
    registry: DeviceRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jarvis.devices import wol

    sent: list[tuple[str, str]] = []

    def record(mac: str, *, address: str, port: int = 9) -> wol.WakeResult:
        sent.append((mac, address))
        return wol.WakeResult(mac=mac, address=address, port=port, bytes_sent=102)

    monkeypatch.setattr(wol, "send_magic_packet", record)
    result = await DeviceControlTool(registry=registry).execute(
        {"action": "wake", "device": "HP OMEN"}, _ctx()
    )
    assert result.success, result.error
    assert sent == [("AA:BB:CC:DD:EE:FF", "127.0.0.1")]
    assert "does not confirm it is on" in result.output


@pytest.mark.parametrize(
    "device,fragment",
    [
        ("echo", "not allowed to be woken"),
        ("tablet", "No registered device matches"),
        ("", "Which device"),
    ],
)
async def test_wake_refusals(registry: DeviceRegistry, device: str, fragment: str) -> None:
    result = await DeviceControlTool(registry=registry).execute(
        {"action": "wake", "device": device}, _ctx()
    )
    assert not result.success and fragment in result.error


async def test_wake_without_a_mac_is_refused(tmp_path: Path) -> None:
    reg = DeviceRegistry(tmp_path / "devices.json")
    reg.upsert(OwnedDevice(id="nas", name="NAS", capabilities=["wake_on_lan"]))
    result = await DeviceControlTool(registry=reg).execute(
        {"action": "wake", "device": "nas"}, _ctx()
    )
    assert not result.success and "no MAC address" in result.error


async def test_power_runs_the_planned_command_for_this_computer(registry: DeviceRegistry) -> None:
    runner = RecordingRunner()
    tool = DeviceControlTool(registry=registry, runner=runner)
    result = await tool.execute({"action": "power", "op": "lock"}, _ctx())
    assert result.success, result.error
    assert len(runner.calls) == 1


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS shuts down without a grace delay")
async def test_power_shutdown_reports_the_grace_period(registry: DeviceRegistry) -> None:
    runner = RecordingRunner()
    tool = DeviceControlTool(registry=registry, runner=runner)
    result = await tool.execute(
        {"action": "power", "op": "shutdown", "device": "desktop", "delay_s": 60}, _ctx()
    )
    assert result.success, result.error
    assert "op='cancel' stops it" in result.output


async def test_power_for_another_device_is_refused_without_running_anything(
    registry: DeviceRegistry,
) -> None:
    runner = RecordingRunner()
    tool = DeviceControlTool(registry=registry, runner=runner)
    result = await tool.execute({"action": "power", "op": "shutdown", "device": "omen"}, _ctx())
    assert not result.success and "different device" in result.error
    assert runner.calls == []


async def test_power_without_permission_is_refused(tmp_path: Path) -> None:
    reg = DeviceRegistry(tmp_path / "devices.json")
    reg.upsert(OwnedDevice(id="pc", name="PC", this_machine=True))
    runner = RecordingRunner()
    result = await DeviceControlTool(registry=reg, runner=runner).execute(
        {"action": "power", "op": "restart", "device": "pc"}, _ctx()
    )
    assert not result.success and "no power permission" in result.error
    assert runner.calls == []


async def test_power_failure_is_reported(registry: DeviceRegistry) -> None:
    tool = DeviceControlTool(registry=registry, runner=RecordingRunner(returncode=5))
    result = await tool.execute({"action": "power", "op": "lock"}, _ctx())
    assert not result.success and "exit 5" in result.error


async def test_unknown_action_and_op(registry: DeviceRegistry) -> None:
    tool = DeviceControlTool(registry=registry, runner=RecordingRunner())
    assert not (await tool.execute({"action": "fly"}, _ctx())).success
    assert not (await tool.execute({"action": "power", "op": "explode"}, _ctx())).success
