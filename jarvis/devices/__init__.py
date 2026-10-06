"""The person's own devices: a registry of what each one is and may do.

See :mod:`jarvis.devices.models` for the record, :mod:`jarvis.devices.store`
for the file it lives in, :mod:`jarvis.devices.wol` for Wake-on-LAN and
:mod:`jarvis.devices.power` for OS power actions on this machine. Kept import
light: nothing here touches the network or spawns a process at import time.
"""

from __future__ import annotations

from jarvis.devices.models import DEVICE_CAPABILITIES, OwnedDevice

__all__ = ["DEVICE_CAPABILITIES", "OwnedDevice"]
