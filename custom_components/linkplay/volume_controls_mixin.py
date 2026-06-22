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

        Uses ``vol:N`` for the device's own hardware volume, or the
        Wi-Fi-direct ``multiroom:SlaveVolume:<ip>:<N>`` form when the
        device is a slave on a Wi-Fi-direct group (the slave can't be
        reached directly, so the master proxies the command).

        ``setPlayerCmd:slave_vol:N`` is deliberately NOT used here. It
        broadcasts to slaves only and leaves the master's own hardware
        volume untouched, so calling it on a master left the master at
        its old level while every slave moved. Group-wide volume changes
        happen through ``async_set_group_volume``, which iterates each
        member and calls this helper per device, so the per-device
        ``vol:N`` is sufficient.

        Logs a warning on a non-OK response.
        """
        volume_s = str(volume)
        _LOGGER.debug(
            "_set_volume_on_device: %s action=%s target=%s slave_mode=%s "
            "wifidirect=%s is_master=%s snapshot_active=%s slave_ip=%s master=%s",
            self.entity_id, action, volume_s, self._slave_mode,
            self._multiroom_wifidirect, self._is_master,
            self._snapshot_active, self._slave_ip,
            self._master.entity_id if self._master else None,
        )
        if not (self._slave_mode and self._multiroom_wifidirect):
            cmd = f"setPlayerCmd:vol:{volume_s}"
            _LOGGER.debug(
                "_set_volume_on_device: %s sending DIRECT %s", self.entity_id, cmd,
            )
            value = await self.call_linkplay_httpapi(cmd, None)
        else:
            if self._snapshot_active:
                _LOGGER.debug(
                    "_set_volume_on_device: %s SKIPPED action=%s target=%s "
                    "(snapshot active on wifidirect slave; command dropped)",
                    self.entity_id, action, volume_s,
                )
                return
            cmd = f"multiroom:SlaveVolume:{self._slave_ip}:{volume_s}"
            _LOGGER.debug(
                "_set_volume_on_device: %s sending PROXY via master %s: %s",
                self.entity_id,
                self._master.entity_id if self._master else None,
                cmd,
            )
            value = await self._master.call_linkplay_httpapi(cmd, None)

        _LOGGER.debug(
            "_set_volume_on_device: %s response=%s (target=%s)",
            self.entity_id, value, volume_s,
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
        _LOGGER.debug(
            "async_set_volume_level: %s level=%.4f -> target=%s",
            self.entity_id, volume, target,
        )
        # During a snapshot restore the device fades in audio when the
        # input switches, so an immediate vol command is ignored. Give
        # it a second to settle.
        if (
            not (self._slave_mode and self._multiroom_wifidirect)
            and not self._is_master
            and self._snapshot_active
        ):
            _LOGGER.debug(
                "async_set_volume_level: %s sleeping 1s (snapshot settle)",
                self.entity_id,
            )
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
