"""Owned-device records: validation never invents or loosens a value."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jarvis.devices.models import OwnedDevice, normalize_mac, validate_lan_target
from jarvis.devices.store import DeviceRegistry


@pytest.mark.parametrize(
    "raw",
    ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "aabb.ccdd.eeff", "AABBCCDDEEFF"],
)
def test_mac_spellings_normalize_to_one_form(raw: str) -> None:
    assert normalize_mac(raw) == "AA:BB:CC:DD:EE:FF"


@pytest.mark.parametrize("raw", ["", "aa:bb:cc:dd:ee", "gg:bb:cc:dd:ee:ff", "aa:bb:cc:dd:ee:ff:00"])
def test_malformed_mac_is_refused(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_mac(raw)


@pytest.mark.parametrize(
    "address",
    ["255.255.255.255", "192.168.1.255", "10.0.0.255", "172.16.5.9", "127.0.0.1"],
)
def test_local_network_targets_are_accepted(address: str) -> None:
    assert validate_lan_target(address) == address


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.255", "example.com", "::1", ""])
def test_internet_or_non_ipv4_targets_are_refused(address: str) -> None:
    with pytest.raises(ValueError):
        validate_lan_target(address)


def test_device_validates_id_mac_broadcast_and_capabilities() -> None:
    device = OwnedDevice(
        id="Omen",
        name="HP OMEN",
        kind="laptop",
        platform="windows",
        mac_address="aa-bb-cc-dd-ee-ff",
        wol_broadcast="192.168.1.255",
        capabilities=["power", "wake_on_lan"],
    )
    assert device.id == "omen"
    assert device.mac_address == "AA:BB:CC:DD:EE:FF"
    # Stored in the vocabulary's order, whatever order the user typed.
    assert device.capabilities == ("wake_on_lan", "power")
    assert device.can("wake_on_lan") and not device.can("shell")


def test_device_without_mac_has_none_not_a_placeholder() -> None:
    device = OwnedDevice(id="phone", name="iPhone", mac_address="  ")
    assert device.mac_address is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "has space"),
        ("capabilities", ["teleport"]),
        ("wol_broadcast", "8.8.8.8"),
        ("mac_address", "not-a-mac"),
    ],
)
def test_device_rejects_bad_values(field: str, value: object) -> None:
    data: dict[str, object] = {"id": "pc", "name": "PC"}
    data[field] = value
    with pytest.raises(ValidationError):
        OwnedDevice.model_validate(data)


def test_registry_round_trip_and_single_this_machine(tmp_path: Path) -> None:
    registry = DeviceRegistry(tmp_path / "devices.json")
    assert registry.all() == []

    registry.upsert(OwnedDevice(id="desktop", name="Desktop PC", this_machine=True))
    registry.upsert(OwnedDevice(id="omen", name="HP OMEN", mac_address="AABBCCDDEEFF"))
    registry.upsert(OwnedDevice(id="omen-2", name="Second laptop", this_machine=True))

    assert [d.id for d in registry.all()] == ["desktop", "omen", "omen-2"]
    # Flagging a second machine as "this machine" clears the first.
    assert registry.this_machine() is not None
    assert registry.this_machine().id == "omen-2"
    assert registry.get("desktop").this_machine is False

    payload = json.loads((tmp_path / "devices.json").read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert {row["id"] for row in payload["devices"]} == {"desktop", "omen", "omen-2"}

    assert registry.remove("omen-2") is True
    assert registry.remove("omen-2") is False


def test_registry_find_by_id_name_and_unique_fragment(tmp_path: Path) -> None:
    registry = DeviceRegistry(tmp_path / "devices.json")
    registry.upsert(OwnedDevice(id="desktop", name="Desktop PC"))
    registry.upsert(OwnedDevice(id="omen", name="HP OMEN Laptop"))
    registry.upsert(OwnedDevice(id="echo", name="Echo Dot Max"))

    assert registry.find("OMEN").id == "omen"
    assert registry.find("hp omen laptop").id == "omen"
    assert registry.find("laptop").id == "omen"
    assert registry.find("Echo").id == "echo"
    assert registry.find("tablet") is None
    assert registry.find("") is None


def test_registry_ambiguous_fragment_resolves_to_nothing(tmp_path: Path) -> None:
    registry = DeviceRegistry(tmp_path / "devices.json")
    registry.upsert(OwnedDevice(id="pc1", name="Office PC"))
    registry.upsert(OwnedDevice(id="pc2", name="Gaming PC"))
    assert registry.find("pc") is None


def test_registry_moves_a_corrupt_file_aside(tmp_path: Path) -> None:
    path = tmp_path / "devices.json"
    path.write_text("{ not json", encoding="utf-8")
    registry = DeviceRegistry(path)
    assert registry.all() == []
    assert (tmp_path / "devices.corrupt.json").exists()


def test_registry_skips_an_invalid_record_and_keeps_the_rest(tmp_path: Path) -> None:
    path = tmp_path / "devices.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "devices": [
                    {"id": "ok", "name": "Fine"},
                    {"id": "bad", "name": "Broken", "mac_address": "zz"},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert [d.id for d in DeviceRegistry(path).all()] == ["ok"]
