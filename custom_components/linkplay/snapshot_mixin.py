"""Snapshot / restore for LinkPlayDevice.

Captures and restores enough player state so a TTS announcement
(handled internally by the media_player base since HA 2022.6) or a
manual ``linkplay.snapshot``/``linkplay.restore`` call leaves the user
back where they were: same source, same volume, same playhead.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.media_player.const import MediaType
from homeassistant.const import (
    STATE_IDLE,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)

_LOGGER = logging.getLogger(__name__)

# Firmware version after which the firmware is slow to switch streams
# and we need an extra pause before snapshot. Kept here to avoid
# coupling the mixin to media_player module-level constants.
_FW_SLOW_STREAMS = "4.6"


class LinkPlaySnapshotMixin:
    """``linkplay.snapshot`` / ``linkplay.restore`` service handlers."""

    async def async_snapshot(self, switchinput: bool) -> None:
        """Capture the current source, volume and playhead position.

        When ``switchinput`` is True the player is switched to the
        Wi-Fi (network) input, which is required before playing TTS.
        When False, current playback continues — useful for snapshotting
        without interrupting Spotify, etc.
        """
        if self._state == STATE_UNAVAILABLE:
            return
        if self._slave_mode:
            return

        self._snapshot_active = True
        self._snap_source = self._source
        self._snap_state = self._state
        self._snap_nometa = self._nometa
        self._snap_playing_mediabrowser = self._playing_mediabrowser
        self._snap_media_source_uri = self._media_source_uri
        self._snap_playhead_position = self._playhead_position

        if self._playing_localfile or self._playing_spotify or self._playing_webplaylist:
            if self._state in (STATE_PLAYING, STATE_PAUSED):
                self._snap_seek = True
        elif self._playing_stream or self._playing_mediabrowser:
            if self._state in (STATE_PLAYING, STATE_PAUSED) and self._playing_mediabrowser:
                self._snap_seek = True

        _LOGGER.debug(
            "Player %s snapshot source: %s, volume: %s, uri: %s, seek: %s, pos: %s",
            self.name, self._source, self._snap_volume, self._media_uri_final,
            self._snap_seek, self._playhead_position,
        )

        if self._source == "Network":
            self._snap_uri = self._media_uri_final

        if self._playing_spotify:
            if not switchinput:
                await self.async_preset_snap_via_upnp(str(self._preset_key))
                await self.call_linkplay_httpapi("setPlayerCmd:stop", None)
            else:
                self._snap_spotify_volumeonly = True
            self._snap_spotify = True
            self._snap_volume = int(self._volume)
            return

        if self._state == STATE_IDLE:
            self._snap_volume = int(self._volume)
            return

        if switchinput and not self._playing_stream:
            value = await self.call_linkplay_httpapi("setPlayerCmd:switchmode:wifi", None)
            await asyncio.sleep(0.2)
            await self.call_linkplay_httpapi("setPlayerCmd:stop", None)
            if value != "OK":
                self._snap_volume = 0
                return
            # Physical-source switch fades audio in; wait so the
            # reported volume is accurate.
            await asyncio.sleep(2)
            await self.async_get_status()
            if self._player_statdata is None:
                self._snap_volume = 0
                return
            try:
                self._snap_volume = int(self._player_statdata["vol"])
            except ValueError:
                _LOGGER.warning(
                    "Erroneous JSON during snapshot volume reading: %s, %s",
                    self.entity_id, self._name,
                )
                self._snap_volume = 0
            return

        self._snap_volume = int(self._volume)
        if self._fwvercheck(self._fw_ver) >= self._fwvercheck(_FW_SLOW_STREAMS):
            await self.call_linkplay_httpapi("setPlayerCmd:pause", None)
        await self.call_linkplay_httpapi("setPlayerCmd:stop", None)

    async def async_restore(self) -> None:
        """Restore the source, volume and playhead position captured by async_snapshot."""
        if self._state == STATE_UNAVAILABLE:
            return
        if self._slave_mode:
            return

        _LOGGER.debug(
            "Player %s current source: %s, restoring volume: %s, source: %s "
            "uri: %s, seek: %s, pos: %s",
            self.name, self._source, self._snap_volume, self._snap_source,
            self._snap_uri, self._snap_seek, self._snap_playhead_position,
        )

        if self._snap_state != STATE_UNKNOWN:
            self._state = self._snap_state

        if self._snap_volume != 0:
            await self.call_linkplay_httpapi(f"setPlayerCmd:vol:{self._snap_volume}", None)
            self._snap_volume = 0

        self._playing_tts = False
        self._playhead_position = self._snap_playhead_position

        if self._snap_spotify:
            self._snap_spotify = False
            if not self._snap_spotify_volumeonly:
                await self.call_linkplay_httpapi(
                    f"MCUKeyShortClick:{self._preset_key}", None
                )
            self._snapshot_active = False
            self._snap_spotify_volumeonly = False

        elif self._snap_source != "Network":
            self._snapshot_active = False
            await self.async_select_source(self._snap_source)
            self._snap_source = None

        elif self._snap_uri is not None:
            self._playing_mediabrowser = self._snap_playing_mediabrowser
            self._media_source_uri = self._snap_media_source_uri
            self._media_uri = self._snap_uri
            self._nometa = self._snap_nometa
            if self._snap_state in (STATE_PLAYING, STATE_PAUSED):
                await self.async_play_media(MediaType.URL, self._media_uri)
            self._snapshot_active = False
            self._snap_uri = None

        if self._snap_state in (STATE_PLAYING, STATE_PAUSED):
            await asyncio.sleep(0.5)
            if self._snap_seek and self._snap_playhead_position > 0:
                _LOGGER.debug("Seeking after restore")
                await self.call_linkplay_httpapi(
                    f"setPlayerCmd:seek:{self._snap_playhead_position}", None
                )
                if self._snap_state == STATE_PAUSED:
                    await self.async_media_pause()

        self._snap_state = STATE_UNKNOWN
        self._snap_seek = False
        self._snap_playhead_position = 0
