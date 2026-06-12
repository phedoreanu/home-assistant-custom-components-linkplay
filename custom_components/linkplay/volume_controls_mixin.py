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
from datetime import timedelta

from homeassistant.util.dt import utcnow

_LOGGER = logging.getLogger(__name__)

_MAX_VOL = 100

# How long a locally commanded volume outranks values reported by the
# device. A getPlayerStatus (or multiroom:getSlaveList) response that
# was already in flight when the user changed the volume carries the
# pre-change value; without this window the poll handler writes that
# stale value back into ``_volume``, and a preset switch that snapshots
# ``_volume`` right then re-applies the OLD volume to the whole group.
VOLUME_CMD_GRACE = timedelta(seconds=3)


class LinkPlayVolumeControlsMixin:
    """Volume up/down/set/mute service handlers."""

    def _within_volume_grace(self) -> bool:
        """True while a recently commanded volume outranks polled values."""
        volume_cmd_at = getattr(self, "_volume_cmd_at", None)
        return (
            volume_cmd_at is not None
            and utcnow() < volume_cmd_at + VOLUME_CMD_GRACE
        )

    def _within_mute_grace(self) -> bool:
        """True while a recently commanded mute outranks polled values."""
        mute_cmd_at = getattr(self, "_mute_cmd_at", None)
        return (
            mute_cmd_at is not None
            and utcnow() < mute_cmd_at + VOLUME_CMD_GRACE
        )

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
        if not (self._slave_mode and self._multiroom_wifidirect):
            cmd = f"setPlayerCmd:vol:{volume_s}"
            value = await self.call_linkplay_httpapi(cmd, None)
        else:
            if self._snapshot_active or self._master is None:
                return
            value = await self._master.call_linkplay_httpapi(
                f"multiroom:SlaveVolume:{self._slave_ip}:{volume_s}", None,
            )

        if value == "OK":
            self._volume = volume
            self._volume_cmd_at = utcnow()
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
            if self._master is None:
                return
            value = await self._master.call_linkplay_httpapi(
                f"multiroom:SlaveMute:{self._slave_ip}:{flag}", None,
            )

        if value == "OK":
            self._muted = bool(int(mute))
            self._mute_cmd_at = utcnow()
        else:
            _LOGGER.warning(
                "Failed mute/unmute volume. Device: %s, Got response: %s",
                self.entity_id, value,
            )
