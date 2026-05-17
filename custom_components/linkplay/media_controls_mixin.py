"""Transport controls (play / pause / stop / seek / next / prev) for LinkPlayDevice."""

from __future__ import annotations

import logging

from homeassistant.const import STATE_IDLE, STATE_PAUSED, STATE_PLAYING
from homeassistant.util.dt import utcnow

_LOGGER = logging.getLogger(__name__)

# Firmware after which streams take noticeably longer to switch; the
# transport methods need an extra pause before stop so the previous
# stream actually shuts down.
_FW_SLOW_STREAMS = "4.6"


class LinkPlayMediaControlsMixin:
    """media_player.* transport-control entry points."""

    async def _propagate_state_to_slaves(self) -> None:
        if self._slave_list is None:
            return
        for slave in self._slave_list:
            await slave.async_set_state(self._state)
            await slave.async_set_position_updated_at(self.media_position_updated_at)

    async def _skip_track(self, cmd: str, action: str) -> None:
        if self._slave_mode:
            if action == "next":
                await self._master.async_media_next_track()
            else:
                await self._master.async_media_previous_track()
            return
        value = await self.call_linkplay_httpapi(cmd, None)
        self._playhead_position = 0
        self._duration = 0
        self._position_updated_at = utcnow()
        self._trackc = None
        self._wait_for_mcu = 2
        if value != "OK":
            _LOGGER.warning(
                "Failed to skip %s. Device: %s, Got response: %s",
                action, self.entity_id, value,
            )

    async def async_media_next_track(self) -> None:
        """Send next-track command."""
        await self._skip_track("setPlayerCmd:next", "next")

    async def async_media_previous_track(self) -> None:
        """Send previous-track command."""
        await self._skip_track("setPlayerCmd:prev", "previous")

    async def async_media_play(self) -> None:
        """Send play / resume command."""
        if self._slave_mode:
            await self._master.async_media_play()
            return

        value: str | bool | None = None
        if self._state == STATE_PAUSED:
            value = await self.call_linkplay_httpapi("setPlayerCmd:resume", None)
        elif self._prev_source is not None:
            temp_source = next(
                (k for k in self._source_list if self._source_list[k] == self._prev_source),
                None,
            )
            if temp_source is None:
                return
            if temp_source.startswith("http") or temp_source in ("udisk", "TFcard"):
                self.select_source(self._prev_source)
                if self._source is not None:
                    self._source = None
                    value = "OK"
            else:
                value = await self.call_linkplay_httpapi("setPlayerCmd:play", None)
        else:
            value = await self.call_linkplay_httpapi("setPlayerCmd:play", None)

        if value != "OK":
            _LOGGER.warning(
                "Failed to start or resume playback. Device: %s, Got response: %s",
                self.entity_id, value,
            )
            return

        self._state = STATE_PLAYING
        self._unav_throttle = False
        self._position_updated_at = utcnow()
        self._idletime_updated_at = self._position_updated_at
        await self._propagate_state_to_slaves()

    async def async_media_pause(self) -> None:
        """Send pause command."""
        if self._slave_mode:
            await self._master.async_media_pause()
            return

        if self._playing_stream and not self._playing_mediabrowser:
            # Pausing a live stream causes a hardware buffer overrun.
            # Stop is the correct procedure; the saved source lets
            # play restart it cleanly.
            await self.async_media_stop()
            return

        value = await self.call_linkplay_httpapi("setPlayerCmd:pause", None)
        if value != "OK":
            _LOGGER.warning(
                "Failed to pause playback. Device: %s, Got response: %s",
                self.entity_id, value,
            )
            return

        self._position_updated_at = utcnow()
        self._idletime_updated_at = self._position_updated_at
        if self._playing_spotify:
            self._spotify_paused_at = utcnow()
        self._state = STATE_PAUSED
        await self._propagate_state_to_slaves()

    async def async_media_stop(self) -> None:
        """Send stop command, with firmware-version-aware pre-pauses."""
        if self._slave_mode:
            await self._master.async_media_stop()
            return

        slow_streams = self._fwvercheck(self._fw_ver) >= self._fwvercheck(_FW_SLOW_STREAMS)

        if self._playing_spotify or self._playing_liveinput:
            if slow_streams:
                await self.call_linkplay_httpapi("setPlayerCmd:pause", None)
            await self.call_linkplay_httpapi("setPlayerCmd:switchmode:wifi", None)

        if self._playing_stream and slow_streams:
            await self.call_linkplay_httpapi("setPlayerCmd:pause", None)
            await self.call_linkplay_httpapi("setPlayerCmd:switchmode:wifi", None)

        value = await self.call_linkplay_httpapi("setPlayerCmd:stop", None)
        if value != "OK":
            _LOGGER.warning(
                "Failed to stop playback. Device: %s, Got response: %s",
                self.entity_id, value,
            )
            return

        self._state = STATE_IDLE
        self._playhead_position = 0
        self._duration = 0
        self._media_title = None
        self._prev_source = self._source
        self._source = None
        self._nometa = False
        self._media_artist = None
        self._media_album = None
        self._icecast_name = None
        self._media_uri = None
        self._media_uri_final = None
        self._media_source_uri = None
        self._playing_mediabrowser = False
        self._playing_stream = False
        self._trackc = None
        self._media_image_url = None
        self._position_updated_at = utcnow()
        self._idletime_updated_at = self._position_updated_at
        self._spotify_paused_at = None
        await self._propagate_state_to_slaves()

    async def async_media_seek(self, position) -> None:
        """Send seek command if the position is inside the current track."""
        if self._slave_mode:
            await self._master.async_media_seek(position)
            return

        _LOGGER.debug("Seek. Device: %s, DUR: %s POS: %s", self.name, self._duration, position)
        if not (self._duration > 0 and 0 <= position <= self._duration):
            return

        value = await self.call_linkplay_httpapi(f"setPlayerCmd:seek:{position}", None)
        self._position_updated_at = utcnow()
        self._idletime_updated_at = self._position_updated_at
        self._wait_for_mcu = 0.2
        if value != "OK":
            _LOGGER.warning(
                "Failed to seek. Device: %s, Got response: %s",
                self.entity_id, value,
            )

    async def async_clear_playlist(self) -> None:
        """Clear the player's playlist (no-op; LinkPlay has no concept of a host-side queue to clear)."""
