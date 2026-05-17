"""Volume + mute controls for LinkPlayDevice.

Three commands the firmware exposes:

* ``setPlayerCmd:vol:N`` / ``setPlayerCmd:slave_vol:N`` for direct
  changes on the player or via the master.
* ``multiroom:SlaveVolume:<ip>:<N>`` from the master to a slave when
  the group is in Wi-Fi-direct mode.
* ``setPlayerCmd:mute`` / ``setPlayerCmd:slave_mute`` for muting.

Wraps them so the entity exposes ``async_volume_up`` /
``async_volume_down`` / ``async_set_volume_level`` / ``async_mute_volume``.
"""

from __future__ import annotations

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

_MAX_VOL = 100


class LinkPlayVolumeControlsMixin:
    """Volume up/down/set/mute service handlers."""

    async def _set_volume_on_device(self, volume: int, *, action: str) -> None:
        """Send a volume command to whichever device should receive it.

        Picks between ``slave_vol`` / ``vol`` / Wi-Fi-direct
        ``SlaveVolume`` based on the master/slave/Wi-Fi-direct state.
        Logs a warning on a non-OK response.
        """
        volume_s = str(volume)
        if not (self._slave_mode and self._multiroom_wifidirect):
            if self._is_master:
                cmd = f"setPlayerCmd:slave_vol:{volume_s}"
            else:
                cmd = f"setPlayerCmd:vol:{volume_s}"
            value = await self.call_linkplay_httpapi(cmd, None)
        else:
            if self._snapshot_active:
                return
            value = await self._master.call_linkplay_httpapi(
                f"multiroom:SlaveVolume:{self._slave_ip}:{volume_s}", None,
            )

        if value == "OK":
            self._volume = volume
        else:
            _LOGGER.warning(
                "Failed to %s. Device: %s, Got response: %s",
                action, self.entity_id, value,
            )

    async def async_volume_up(self) -> None:
        """Increase volume one step."""
        if int(self._volume) == 100 and not self._muted:
            return
        volume = min(_MAX_VOL, int(self._volume) + int(self._volume_step))
        await self._set_volume_on_device(volume, action="volume_up")

    async def async_volume_down(self) -> None:
        """Decrease volume one step."""
        if int(self._volume) == 0:
            return
        volume = max(0, int(self._volume) - int(self._volume_step))
        await self._set_volume_on_device(volume, action="volume_down")

    async def async_set_volume_level(self, volume) -> None:
        """Set volume from a 0.0-1.0 HA scale to the device's 0-100 scale."""
        target = round(int(volume * _MAX_VOL))
        # During a snapshot restore the device fades in audio when the
        # input switches, so an immediate vol command is ignored. Give
        # it a second to settle.
        if (
            not (self._slave_mode and self._multiroom_wifidirect)
            and not self._is_master
            and self._snapshot_active
        ):
            await asyncio.sleep(1)
        await self._set_volume_on_device(target, action="set volume")

    async def async_mute_volume(self, mute) -> None:
        """Mute (true) or unmute (false) the media player."""
        flag = str(int(mute))
        if not (self._slave_mode and self._multiroom_wifidirect):
            cmd = (
                f"setPlayerCmd:slave_mute:{flag}"
                if self._is_master
                else f"setPlayerCmd:mute:{flag}"
            )
            value = await self.call_linkplay_httpapi(cmd, None)
        else:
            value = await self._master.call_linkplay_httpapi(
                f"multiroom:SlaveVolume:{self._slave_ip}:{flag}", None,
            )

        if value == "OK":
            self._muted = bool(int(mute))
        else:
            _LOGGER.warning(
                "Failed mute/unmute volume. Device: %s, Got response: %s",
                self.entity_id, value,
            )
