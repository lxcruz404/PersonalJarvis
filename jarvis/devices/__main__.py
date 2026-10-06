"""Manage the owned-device registry from a terminal.

    python -m jarvis.devices list
    python -m jarvis.devices add --id desktop --name "Desktop PC" --kind desktop \
        --platform windows --endpoint local_agent --this-machine --cap power --cap apps
    python -m jarvis.devices add --id laptop --name "Laptop" --kind laptop \
        --platform windows --mac AA:BB:CC:DD:EE:FF --broadcast 192.168.1.255 --cap wake_on_lan
    python -m jarvis.devices remove laptop
    python -m jarvis.devices wake laptop

Every value comes from the person: nothing is detected or guessed. The file is
``<user data>/devices/devices.json`` (``--file`` overrides it).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import get_args

from pydantic import ValidationError

from jarvis.devices.models import (
    DEVICE_CAPABILITIES,
    DeviceEndpoint,
    DeviceKind,
    DevicePlatform,
    OwnedDevice,
)
from jarvis.devices.store import DeviceRegistry


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m jarvis.devices", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--file", type=Path, default=None, help="registry file (default: user data)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show registered devices")

    add = sub.add_parser("add", help="add or replace a device")
    add.add_argument("--id", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--kind", choices=get_args(DeviceKind), default="other")
    add.add_argument("--platform", choices=get_args(DevicePlatform), default="other")
    add.add_argument("--endpoint", choices=get_args(DeviceEndpoint), default="none")
    add.add_argument("--this-machine", action="store_true")
    add.add_argument("--mac", default=None, help="MAC address, only for Wake-on-LAN")
    add.add_argument("--broadcast", default=None, help="local broadcast address for Wake-on-LAN")
    add.add_argument("--cap", action="append", default=[], choices=DEVICE_CAPABILITIES)
    add.add_argument("--notes", default="")

    remove = sub.add_parser("remove", help="remove a device")
    remove.add_argument("id")

    wake = sub.add_parser("wake", help="send a Wake-on-LAN packet to a device")
    wake.add_argument("device")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    registry = DeviceRegistry(args.file)

    if args.command == "list":
        rows = registry.all()
        if not rows:
            print(f"No devices registered ({registry.path}).")
            return 0
        for row in rows:
            marker = " *this machine*" if row.this_machine else ""
            mac = f" mac={row.mac_address}" if row.mac_address else ""
            caps = ",".join(row.capabilities) or "-"
            where = f"{row.kind}/{row.platform}/{row.endpoint}"
            print(f"{row.id}: {row.name} [{where}]{mac} caps={caps}{marker}")
        return 0

    if args.command == "add":
        try:
            device = OwnedDevice(
                id=args.id,
                name=args.name,
                kind=args.kind,
                platform=args.platform,
                endpoint=args.endpoint,
                this_machine=args.this_machine,
                mac_address=args.mac,
                wol_broadcast=args.broadcast,
                capabilities=args.cap,
                notes=args.notes,
            )
        except ValidationError as exc:
            print(f"Invalid device: {exc}", file=sys.stderr)
            return 2
        registry.upsert(device)
        print(f"Saved {device.id} to {registry.path}")
        return 0

    if args.command == "remove":
        if registry.remove(args.id):
            print(f"Removed {args.id}")
            return 0
        print(f"No device {args.id!r}", file=sys.stderr)
        return 1

    if args.command == "wake":
        from jarvis.devices.wol import LIMITED_BROADCAST, send_magic_packet

        device = registry.find(args.device)
        if device is None:
            print(f"No device matches {args.device!r}", file=sys.stderr)
            return 1
        if not device.can("wake_on_lan") or not device.mac_address:
            print(
                f"{device.name} needs the wake_on_lan capability and a MAC address", file=sys.stderr
            )
            return 1
        result = send_magic_packet(
            device.mac_address, address=device.wol_broadcast or LIMITED_BROADCAST
        )
        print(f"Magic packet sent to {result.mac} via {result.address}:{result.port}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
