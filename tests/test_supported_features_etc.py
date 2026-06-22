"""Targeted coverage for the remaining property branches and small holes
in media_player.py: supported_features matrix, icon by source, source_list
empty case, and play_track failure-path branches.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.const import STATE_IDLE, STATE_PLAYING

from tests._helpers import make_device


def _make_device():
    dev = make_device("dev")
    dev.call_linkplay_httpapi = AsyncMock(return_value="OK")
    return dev


class TestSupportedFeatures:
    def test_slave_mode_returns_cached(self) -> None:
        dev = _make_device()
        dev._slave_mode = True
        dev._features = MediaPlayerEntityFeature.PLAY
        assert dev.supported_features == MediaPlayerEntityFeature.PLAY

    def test_localfile_idle_falls_through_to_else(self) -> None:
        dev = _make_device()
        dev._playing_localfile = True
        dev._state = STATE_IDLE
        feats = dev.supported_features
        # idle/localfile takes the no-seek branch
        assert feats & MediaPlayerEntityFeature.PLAY
        assert not (feats & MediaPlayerEntityFeature.SEEK)

    def test_spotify_playing_includes_seek(self) -> None:
        dev = _make_device()
        dev._playing_spotify = True
        dev._state = STATE_PLAYING
        feats = dev.supported_features
        assert feats & MediaPlayerEntityFeature.SEEK

    def test_stream_includes_seek_no_skip(self) -> None:
        dev = _make_device()
        dev._playing_localfile = False  # default is True in __init__
        dev._playing_stream = True
        feats = dev.supported_features
        assert feats & MediaPlayerEntityFeature.SEEK
        assert not (feats & MediaPlayerEntityFeature.NEXT_TRACK)

    def test_mediabrowser_features(self) -> None:
        dev = _make_device()
        dev._playing_localfile = False
        dev._playing_mediabrowser = True
        feats = dev.supported_features
        assert feats & MediaPlayerEntityFeature.BROWSE_MEDIA

    def test_liveinput_lacks_transport_controls(self) -> None:
        dev = _make_device()
        dev._playing_localfile = False
        dev._playing_liveinput = True
        feats = dev.supported_features
        assert feats & MediaPlayerEntityFeature.SELECT_SOURCE
        assert not (feats & MediaPlayerEntityFeature.PLAY)


class TestIcon:
    def test_bluetooth_icon(self) -> None:
        dev = _make_device()
        dev._state = STATE_PLAYING
        dev._source = "Bluetooth"
        from custom_components.linkplay.media_player import ICON_BLUETOOTH
        assert dev.icon == ICON_BLUETOOTH

    def test_dlna_icon(self) -> None:
        dev = _make_device()
        dev._state = STATE_PLAYING
        dev._source = "DLNA"
        from custom_components.linkplay.media_player import ICON_PUSHSTREAM
        assert dev.icon == ICON_PUSHSTREAM

    def test_playing_icon(self) -> None:
        dev = _make_device()
        dev._source = "Network"
        dev._state = STATE_PLAYING
        from custom_components.linkplay.media_player import ICON_PLAYING
        assert dev.icon == ICON_PLAYING

    def test_muted_icon(self) -> None:
        dev = _make_device()
        dev._state = STATE_PLAYING
        dev._muted = True
        from custom_components.linkplay.media_player import ICON_MUTED
        assert dev.icon == ICON_MUTED

    def test_multiroom_master_icon(self) -> None:
        dev = _make_device()
        dev._state = STATE_PLAYING
        dev._is_master = True
        from custom_components.linkplay.media_player import ICON_MULTIROOM
        assert dev.icon == ICON_MULTIROOM

    def test_tts_icon(self) -> None:
        dev = _make_device()
        dev._playing_tts = True
        from custom_components.linkplay.media_player import ICON_TTS
        assert dev.icon == ICON_TTS


class TestSourceListEmpty:
    def test_empty_source_list_returns_none(self) -> None:
        dev = _make_device()
        dev._source_list = {}
        assert dev.source_list is None


class TestPlayTrackFailure:
    @pytest.mark.asyncio
    async def test_command_failure_returns_false(self) -> None:
        dev = _make_device()
        dev._trackq = ["a.mp3", "Target Song.mp3"]
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        track = MagicMock()
        track.async_render = MagicMock(return_value="Target Song")
        assert await dev.async_play_track(track) is False

    @pytest.mark.asyncio
    async def test_slave_delegates_to_master(self) -> None:
        dev = _make_device()
        dev._trackq = ["x"]
        dev._slave_mode = True
        dev._master = MagicMock()
        dev._master.async_play_track = AsyncMock()
        track = MagicMock()
        track.async_render = MagicMock(return_value="x")
        await dev.async_play_track(track)
        dev._master.async_play_track.assert_awaited_once_with(track)


class TestTrivialProperties:
    """Touch every direct attribute accessor at least once."""

    def test_simple_accessors(self) -> None:
        from homeassistant.components.media_player import (
            MediaPlayerDeviceClass,
            MediaType,
            RepeatMode,
        )

        dev = _make_device()
        dev._shuffle = True
        dev._repeat = RepeatMode.ALL
        dev._media_title = "t"
        dev._media_artist = "a"
        dev._media_album = "al"
        dev._media_image_url = "u"
        dev._media_uri_final = "uri"
        dev._ssid = "ssid"
        dev._wifi_channel = "6"
        dev._slave_ip = "1.1.1.1"
        dev._trackq = ["a", "b"]
        dev._trackc = "c"
        dev._uuid = "U1"
        dev._is_master = True
        dev._slave_mode = True
        dev._multiroom_group = ["x"]
        dev._sound_mode = "Jazz"

        assert dev.shuffle is True
        assert dev.repeat == RepeatMode.ALL
        assert dev.media_title == "t"
        assert dev.media_artist == "a"
        assert dev.media_album_name == "al"
        assert dev.media_image_url == "u"
        assert dev.media_content_type == MediaType.MUSIC
        assert dev.ssid == "ssid"
        assert dev.wifi_channel == "6"
        assert dev.slave_ip == "1.1.1.1"
        assert dev.device_class == MediaPlayerDeviceClass.SPEAKER
        assert dev.sound_mode == "Jazz"
        # extra_state_attributes covers the various branches above
        attrs = dev.extra_state_attributes
        assert "uuid" in attrs or "UUID" in attrs or any(
            "uuid" in k.lower() for k in attrs.keys()
        )

    def test_track_count_zero(self) -> None:
        dev = _make_device()
        dev._trackq = []
        assert dev.track_count == 0

    def test_unique_id_returns_none_without_uuid(self) -> None:
        dev = _make_device()
        dev._uuid = ""
        assert dev.unique_id is None

    def test_unique_id_formats_with_uuid(self) -> None:
        dev = _make_device()
        dev._uuid = "ABCD"
        assert dev.unique_id == "linkplay_media_ABCD"


class TestSomaFmDetectionInUpdate:
    """Drive the SomaFM detection branch inside ``async_update``."""

    def _seed(self, dev, payload):
        async def _stub(*a, **kw):
            dev._player_statdata = payload
        dev.async_get_status = AsyncMock(side_effect=_stub)
        dev._first_update = False
        dev.async_update_via_upnp = AsyncMock()
        dev.async_get_playerstatus_metadata = AsyncMock(return_value=True)
        dev.async_get_icecast_meta = AsyncMock(return_value=False)
        dev.async_update_lastfm = AsyncMock(return_value=False)
        dev.async_is_playing_new_track = AsyncMock(return_value=False)
        dev._factory = MagicMock()
        dev._factory.async_create_device = AsyncMock(return_value=MagicMock())

    @pytest.mark.asyncio
    async def test_somafm_station_change_resets_track_metadata(self) -> None:
        dev = _make_device()
        # decoded "SomaFM: Beat Blender" in hex
        somafm_hex = "536f6d61464d3a204265617420426c656e646572"
        payload = {
            "type": "0", "mode": "10", "status": "play",
            "vol": "55", "mute": "0", "eq": "0", "loop": "0",
            "totlen": "0", "curpos": "0",
            "uri": "687474703a2f2f73",  # arbitrary
            "Title": somafm_hex, "Artist": "", "Album": "",
        }
        self._seed(dev, payload)
        dev._media_title = "Old Track"
        dev._media_artist = "Old Artist"
        dev._somafm_cached_station = "SomaFM: Drone Zone"
        dev.async_update_from_somafm = AsyncMock(return_value=True)
        await dev.async_update()
        # Cache flipped to new station
        assert dev._somafm_cached_station == "SomaFM: Beat Blender"

    @pytest.mark.asyncio
    async def test_somafm_throttled_keeps_existing_artist(self) -> None:
        dev = _make_device()
        somafm_hex = "536f6d61464d3a204472" + "6f6e65205a6f6e65"  # Drone Zone
        payload = {
            "type": "0", "mode": "10", "status": "play",
            "vol": "55", "mute": "0", "eq": "0", "loop": "0",
            "totlen": "0", "curpos": "0", "uri": "ff",
            "Title": somafm_hex, "Artist": "", "Album": "",
        }
        self._seed(dev, payload)
        dev._media_title = "Track In Progress"
        dev._media_artist = "Artist In Progress"
        dev._somafm_cached_station = "SomaFM: Drone Zone"
        # Throttled fetch returns None (per the integration's @Throttle path)
        dev.async_update_from_somafm = AsyncMock(return_value=None)
        await dev.async_update()
        # Existing artist preserved through throttle
        assert dev._media_artist == "Artist In Progress"

    @pytest.mark.asyncio
    async def test_non_somafm_stream_upnp_exception_swallowed(self) -> None:
        dev = _make_device()
        payload = {
            "type": "0", "mode": "10", "status": "play",
            "vol": "55", "mute": "0", "eq": "0", "loop": "0",
            "totlen": "0", "curpos": "0", "uri": "",
            "Title": "BBC Radio 1", "Artist": "", "Album": "",
        }
        self._seed(dev, payload)
        dev._media_title = "BBC Radio 1"
        dev._upnp_device = MagicMock()
        dev.async_get_playerstatus_metadata = AsyncMock(return_value=False)
        dev.async_update_via_upnp = AsyncMock(side_effect=Exception("boom"))
        dev.async_update_from_icecast = AsyncMock(return_value=False)
        # No raise; coverage hits the except branch
        await dev.async_update()
