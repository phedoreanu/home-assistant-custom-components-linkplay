"""Async-method tests for LinkPlayDevice methods that aren't covered by
the per-mixin tests (preset_button, play_track, set_shuffle/repeat,
select_sound_mode, get_*_metadata helpers, async_is_playing_new_track).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.media_player import RepeatMode
from homeassistant.const import STATE_IDLE


def _make_device():
    from custom_components.linkplay.media_player import LinkPlayDevice

    hass = MagicMock()
    hass.data = {"linkplay": MagicMock(entities=[])}

    with patch("custom_components.linkplay.media_player.AiohttpRequester"), patch(
        "custom_components.linkplay.media_player.UpnpFactory"
    ):
        dev = LinkPlayDevice(
            name="dev", host="1.2.3.4", protocol="http",
            sources=None, common_sources=None,
            icecast_metadata="StationName", multiroom_wifidirect=False,
            led_off=False, volume_step=5, lastfm_api_key=None,
            uuid="", state=STATE_IDLE,
        )
    dev.entity_id = "media_player.dev"
    dev.hass = hass
    dev.call_linkplay_httpapi = AsyncMock(return_value="OK")
    return dev


class TestPresetButton:
    @pytest.mark.asyncio
    async def test_valid_preset_sends_mcu_short_click(self) -> None:
        dev = _make_device()
        dev._preset_key = 4
        await dev.async_preset_button(2)
        # Wrapped by crossfade; volume==0 means it short-circuits and
        # just runs the impl directly.
        cmds = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert "MCUKeyShortClick:2" in cmds

    @pytest.mark.asyncio
    async def test_preset_out_of_range_warns_no_call(self) -> None:
        dev = _make_device()
        dev._preset_key = 4
        await dev.async_preset_button(99)
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preset_none_or_unsupported_is_noop(self) -> None:
        dev = _make_device()
        dev._preset_key = None
        await dev.async_preset_button(1)
        dev.call_linkplay_httpapi.assert_not_awaited()


class TestPlayTrack:
    @pytest.mark.asyncio
    async def test_empty_queue_returns_false(self) -> None:
        dev = _make_device()
        assert await dev.async_play_track(MagicMock()) is False

    @pytest.mark.asyncio
    async def test_match_plays_local_list_and_sets_state(self) -> None:
        dev = _make_device()
        dev._trackq = ["intro.mp3", "track1.mp3", "track2.mp3"]
        track = MagicMock()
        track.async_render = MagicMock(return_value="track1")
        ok = await dev.async_play_track(track)
        assert ok is True
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:playLocalList:1"
        assert dev._state == "playing"

    @pytest.mark.asyncio
    async def test_unmatched_track_returns_false(self) -> None:
        dev = _make_device()
        dev._trackq = ["intro.mp3"]
        track = MagicMock()
        track.async_render = MagicMock(return_value="nothing")
        assert await dev.async_play_track(track) is False

    @pytest.mark.asyncio
    async def test_zero_index_match_returns_false(self) -> None:
        dev = _make_device()
        dev._trackq = ["intro.mp3", "intro_more.mp3"]
        track = MagicMock()
        track.async_render = MagicMock(return_value="intro.mp3")
        # index 0 is treated as "no track" so the device doesn't replay
        # the same opener.
        assert await dev.async_play_track(track) is False


class TestShuffleRepeat:
    @pytest.mark.asyncio
    async def test_shuffle_on_sends_mode_2(self) -> None:
        dev = _make_device()
        await dev.async_set_shuffle(True)
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:loopmode:2"
        assert dev._shuffle is True

    @pytest.mark.asyncio
    async def test_shuffle_off_with_repeat_all_sends_mode_3(self) -> None:
        dev = _make_device()
        dev._repeat = RepeatMode.ALL
        await dev.async_set_shuffle(False)
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:loopmode:3"

    @pytest.mark.asyncio
    async def test_shuffle_off_with_repeat_one_sends_mode_1(self) -> None:
        dev = _make_device()
        dev._repeat = RepeatMode.ONE
        await dev.async_set_shuffle(False)
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:loopmode:1"

    @pytest.mark.asyncio
    async def test_repeat_all_with_shuffle_uses_mode_2(self) -> None:
        dev = _make_device()
        dev._shuffle = True
        await dev.async_set_repeat(RepeatMode.ALL)
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:loopmode:2"

    @pytest.mark.asyncio
    async def test_repeat_one_sends_mode_1(self) -> None:
        dev = _make_device()
        await dev.async_set_repeat(RepeatMode.ONE)
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:loopmode:1"

    @pytest.mark.asyncio
    async def test_repeat_off_sends_mode_0(self) -> None:
        dev = _make_device()
        await dev.async_set_repeat(RepeatMode.OFF)
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:loopmode:0"


class TestSoundMode:
    @pytest.mark.asyncio
    async def test_select_known_sound_mode(self) -> None:
        dev = _make_device()
        from custom_components.linkplay.media_player import SOUND_MODES
        mode_label = next(iter(SOUND_MODES.values()))
        await dev.async_select_sound_mode(mode_label)
        cmd = dev.call_linkplay_httpapi.await_args.args[0]
        assert cmd.startswith("setPlayerCmd:equalizer:")
        assert dev._sound_mode == mode_label


class TestMetadataHelpers:
    @pytest.mark.asyncio
    async def test_local_mediasource_parses_artist_title(self) -> None:
        dev = _make_device()
        dev._media_source_uri = "media-source://media_source/local/Artist_Name/Song_Name.mp3"
        ok = await dev.async_get_local_mediasource_metadata_from_path()
        assert ok is True
        assert dev._media_artist == "Artist Name"
        assert "Song Name" in dev._media_title

    @pytest.mark.asyncio
    async def test_local_mediasource_with_no_uri_returns_false(self) -> None:
        dev = _make_device()
        dev._media_source_uri = None
        assert await dev.async_get_local_mediasource_metadata_from_path() is False

    @pytest.mark.asyncio
    async def test_playerstatus_metadata_clears_when_field_present_but_empty(self) -> None:
        dev = _make_device()
        # Title/Artist/Album keys present and empty -> leave existing values alone
        dev._media_title = "old"
        dev._media_artist = "old"
        await dev.async_get_playerstatus_metadata(
            {"Title": "", "Artist": "", "Album": "", "uri": ""}
        )
        assert dev._media_title == "old"
        assert dev._media_artist == "old"

    @pytest.mark.asyncio
    async def test_playerstatus_metadata_decoded_hex_populates(self) -> None:
        dev = _make_device()
        # "Hello" in hex
        await dev.async_get_playerstatus_metadata(
            {"Title": "48656c6c6f", "Artist": "576f726c64", "Album": "", "uri": ""}
        )
        assert dev._media_title == "Hello"
        assert dev._media_artist == "World"


class TestIsPlayingNewTrack:
    @pytest.mark.asyncio
    async def test_mediabrowser_files_never_trigger_new_track(self) -> None:
        dev = _make_device()
        dev._playing_mediabrowser = True
        dev._media_source_uri = "x"
        assert await dev.async_is_playing_new_track() is False

    @pytest.mark.asyncio
    async def test_artist_or_title_change_triggers_new_track(self) -> None:
        dev = _make_device()
        dev._media_artist = "A"
        dev._media_title = "T"
        dev._media_prev_artist = "A"
        dev._media_prev_title = "Old"
        assert await dev.async_is_playing_new_track() is True

    @pytest.mark.asyncio
    async def test_same_metadata_returns_false(self) -> None:
        dev = _make_device()
        dev._media_artist = "A"
        dev._media_title = "T"
        dev._media_prev_artist = "A"
        dev._media_prev_title = "T"
        assert await dev.async_is_playing_new_track() is False


class TestFwVerCheck:
    def test_pads_components_for_lexicographic_sort(self) -> None:
        from custom_components.linkplay.media_player import LinkPlayDevice
        assert LinkPlayDevice._fwvercheck("4.6.1") < LinkPlayDevice._fwvercheck("4.6.10")
        assert LinkPlayDevice._fwvercheck("4.2.8020") < LinkPlayDevice._fwvercheck("4.6.0")
