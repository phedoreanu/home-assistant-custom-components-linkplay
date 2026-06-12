"""Raw-command dispatcher for LinkPlayDevice.

Wraps the LinkPlay HTTP / TCP UART command surface so users can invoke
device-specific commands via the ``linkplay.command`` service.

The mixin reads ``self.call_linkplay_httpapi`` / ``self.call_linkplay_tcpuart``
from the entity and writes only ``self._name``, ``self._unav_throttle``,
``self._first_update``. Persistent notifications are posted on the HA
bus via ``self.hass``.
"""

from __future__ import annotations

import logging
import time
from random import choice
from string import ascii_letters
from urllib.parse import quote

from homeassistant.components import persistent_notification

_LOGGER = logging.getLogger(__name__)


def _random_wifi_key(length: int = 16) -> str:
    return "".join(choice(ascii_letters) for _ in range(length))


class LinkPlayCommandsMixin:
    """LinkPlay ``linkplay.command`` service implementation."""

    async def async_execute_command(self, command: str, notif: bool) -> None:
        """Execute a raw device command and optionally surface the result.

        Commands handled here cover the device-management surface that
        users typically reach for: device naming, prompt sounds, random
        Wi-Fi keys, multiroom protocol toggle, reboots, factory reset,
        and a couple of refresh hooks. Unknown commands log a warning
        and surface ``"No such command implemented."`` to the user.
        """
        value: str | bool | None
        if command.startswith("MCU"):
            value = await self.call_linkplay_tcpuart(command)
        elif command == "PromptEnable":
            value = await self.call_linkplay_httpapi("PromptEnable", None)
        elif command == "PromptDisable":
            value = await self.call_linkplay_httpapi("PromptDisable", None)
        elif command == "RouterMultiroomEnable":
            value = await self.call_linkplay_httpapi("setMultiroomLogic:1", None)
        elif command == "SetRandomWifiKey":
            newkey = _random_wifi_key()
            value = await self.call_linkplay_httpapi(f"setNetwork:1:{newkey}", None)
            value = f"{value}, key: {newkey}" if value == "OK" else f"key: {newkey}"
        elif command.startswith("SetApSSIDName:"):
            ssidnam = command.removeprefix("SetApSSIDName:").strip()
            if ssidnam:
                value = await self.call_linkplay_httpapi(f"setSSID:{quote(ssidnam)}", None)
                if value == "OK":
                    value = f"{value}, SoftAP SSID set to: {ssidnam}"
            else:
                value = "SSID not specified correctly. You need 'SetApSSIDName: NewWifiName'"
        elif command.startswith("WriteDeviceNameToUnit:"):
            devnam = command.removeprefix("WriteDeviceNameToUnit:").strip()
            if devnam:
                value = await self.call_linkplay_httpapi(f"setDeviceName:{quote(devnam)}", None)
                if value == "OK":
                    self._name = devnam
                    value = f"{value}, name set to: {self._name}"
            else:
                value = "Device name not specified correctly. You need 'WriteDeviceNameToUnit: My Device Name'"
        elif command == "TimeSync":
            tme = time.strftime("%Y%m%d%H%M%S")
            value = await self.call_linkplay_httpapi(f"timeSync:{tme}", None)
            if value == "OK":
                value = f"{value}, time: {tme}"
        elif command == "Rescan":
            self._unav_throttle = False
            self._first_update = True
            value = "Scheduled to Rescan"
        elif command == "Update":
            value = "Scheduled to Update state"
        elif command == "reboot":
            value = await self.call_linkplay_httpapi("reboot;", None)
        elif command == "restoreToDefault":
            value = await self.call_linkplay_httpapi("restoreToDefault", None)
        else:
            value = "No such command implemented."
            _LOGGER.warning("Player %s command: %s, result: %s", self.entity_id, command, value)

        _LOGGER.debug("Player %s executed command: %s, result: %s", self.entity_id, command, value)

        if notif:
            persistent_notification.async_create(
                self.hass,
                f"<b>Executed command:</b><br>{command}<br><b>Result:</b><br>{value}",
                title=self.entity_id,
            )
