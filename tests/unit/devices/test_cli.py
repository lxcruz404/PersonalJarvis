"""``python -m jarvis.devices``: add, list, remove against a sandboxed file."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.devices.__main__ import main
from jarvis.devices.store import DeviceRegistry


def test_add_list_remove(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file = tmp_path / "devices.json"
    code = main(
        [
            "--file",
            str(file),
            "add",
            "--id",
            "laptop",
            "--name",
            "Laptop",
            "--kind",
            "laptop",
            "--platform",
            "windows",
            "--mac",
            "aa-bb-cc-dd-ee-ff",
            "--broadcast",
            "192.168.1.255",
            "--cap",
            "wake_on_lan",
        ]
    )
    assert code == 0
    device = DeviceRegistry(file).get("laptop")
    assert device is not None and device.mac_address == "AA:BB:CC:DD:EE:FF"

    assert main(["--file", str(file), "list"]) == 0
    assert "laptop: Laptop [laptop/windows/none] mac=AA:BB:CC:DD:EE:FF" in capsys.readouterr().out

    assert main(["--file", str(file), "remove", "laptop"]) == 0
    assert main(["--file", str(file), "remove", "laptop"]) == 1


def test_add_rejects_an_internet_broadcast(tmp_path: Path) -> None:
    file = tmp_path / "devices.json"
    code = main(["--file", str(file), "add", "--id", "x", "--name", "X", "--broadcast", "8.8.8.8"])
    assert code == 2
    assert not file.exists()
