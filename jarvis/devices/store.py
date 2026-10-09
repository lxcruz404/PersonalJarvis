"""The JSON file the owned-device records live in.

``<user data>/devices/devices.json``, rewritten atomically (temp file +
``os.replace``) under one process-wide lock, so a crash mid-write leaves the
previous file intact and two writers never interleave a read-modify-write.
No secrets are ever written here: a MAC address is an identifier, not a
credential.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from pydantic import ValidationError

from jarvis.core.paths import user_data_dir
from jarvis.devices.models import OwnedDevice

log = logging.getLogger(__name__)

_FILE_VERSION = 1
_LOCK = threading.RLock()


def default_path() -> Path:
    """Where the records live; resolved per call so a test sandbox is honoured."""
    return user_data_dir() / "devices" / "devices.json"


class DeviceRegistry:
    """Read and write the owned-device list. Cheap to construct; holds no state."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_path()

    @property
    def path(self) -> Path:
        return self._path

    def all(self) -> list[OwnedDevice]:
        with _LOCK:
            return self._read()

    def get(self, device_id: str) -> OwnedDevice | None:
        wanted = (device_id or "").strip().lower()
        return next((d for d in self.all() if d.id == wanted), None)

    def this_machine(self) -> OwnedDevice | None:
        """The record flagged as the device this install runs on, if any."""
        return next((d for d in self.all() if d.this_machine), None)

    def find(self, query: str) -> OwnedDevice | None:
        """Resolve a spoken or typed reference by id, then by name (case-insensitive)."""
        text = (query or "").strip().lower()
        if not text:
            return None
        rows = self.all()
        for row in rows:
            if row.id == text:
                return row
        for row in rows:
            if row.name.strip().lower() == text:
                return row
        matches = [row for row in rows if text in row.name.lower()]
        return matches[0] if len(matches) == 1 else None

    def upsert(self, device: OwnedDevice) -> OwnedDevice:
        """Add ``device`` or replace the record with the same id.

        Only one record may be ``this_machine``; flagging a new one clears the
        flag on the previous one.
        """
        with _LOCK:
            rows = [row for row in self._read() if row.id != device.id]
            if device.this_machine:
                rows = [
                    row.model_copy(update={"this_machine": False}) if row.this_machine else row
                    for row in rows
                ]
            rows.append(device)
            rows.sort(key=lambda row: row.id)
            self._write(rows)
            return device

    def remove(self, device_id: str) -> bool:
        wanted = (device_id or "").strip().lower()
        with _LOCK:
            rows = self._read()
            kept = [row for row in rows if row.id != wanted]
            if len(kept) == len(rows):
                return False
            self._write(kept)
            return True

    # -- file I/O ----------------------------------------------------------

    def _read(self) -> list[OwnedDevice]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:  # no file yet simply means no devices yet
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Never overwrite a file we cannot read: keep a copy for the user and
            # start from an empty list rather than refusing every request.
            backup = self._path.with_suffix(".corrupt.json")
            log.warning("devices: %s is not JSON; moved aside to %s", self._path, backup)
            os.replace(self._path, backup)
            return []
        rows: list[OwnedDevice] = []
        for item in data.get("devices", []) if isinstance(data, dict) else []:
            try:
                rows.append(OwnedDevice.model_validate(item))
            except ValidationError as exc:
                log.warning("devices: skipping an unreadable record: %s", exc)
        return rows

    def _write(self, rows: list[OwnedDevice]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _FILE_VERSION,
            "devices": [row.model_dump(mode="json") for row in rows],
        }
        fd, tmp = tempfile.mkstemp(prefix=".devices.", suffix=".tmp", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


__all__ = ["DeviceRegistry", "default_path"]
