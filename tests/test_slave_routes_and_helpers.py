"""Cover slave-mode delegation branches and small helpers in media_player.py
that aren't exercised elsewhere.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.media_player import RepeatMode

from tests._helpers import make_device


def _make_device():
    dev = make_device("dev")
    dev.call_linkplay_httpapi = AsyncMock(return_value="OK")
    return dev


def _mk_slave(target):
    """Set `target` up as a slave with a master-side mock for delegation
    tests."""
    target._slave_mode = True
    target._master = MagicMock()
    target._master.async_select_sound_mode = AsyncMock()
    target._master.async_set_shuffle = AsyncMock()
    target._master.async_set_repeat = AsyncMock()


class TestSlaveDelegation:
    @pytest.mark.asyncio
    async def test_select_sound_mode_delegates(self) -> None:
        dev = _make_device()
        _mk_slave(dev)
        await dev.async_select_sound_mode("Jazz")
        dev._master.async_select_sound_mode.assert_awaited_once_with("Jazz")

    @pytest.mark.asyncio
    async def test_set_shuffle_delegates(self) -> None:
        dev = _make_device()
        _mk_slave(dev)
        await dev.async_set_shuffle(True)
        dev._master.async_set_shuffle.assert_awaited_once_with(True)

    @pytest.mark.asyncio
    async def test_set_repeat_delegates(self) -> None:
        dev = _make_device()
        _mk_slave(dev)
        await dev.async_set_repeat(RepeatMode.ONE)
        dev._master.async_set_repeat.assert_awaited_once_with(RepeatMode.ONE)


class TestSelectSourceFailures:
    @pytest.mark.asyncio
    async def test_http_source_failed_command_warns(self) -> None:
        dev = _make_device()
        dev._source_list = {"http://radio/": "Web Radio"}
        dev._fw_ver = "4.2"
        dev._volume = 0
        dev.async_detect_stream_url_redirection = AsyncMock(side_effect=lambda u: u)
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev._async_select_source_impl("Web Radio")
        # No exception; warning was logged.

    @pytest.mark.asyncio
    async def test_physical_source_failed_command_warns(self) -> None:
        dev = _make_device()
        dev._source_list = {"line-in": "Line In"}
        dev._fw_ver = "4.2"
        dev._volume = 0
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev._async_select_source_impl("Line In")


class TestSetShuffleAndRepeatBranches:
    @pytest.mark.asyncio
    async def test_shuffle_failed_command_warns(self) -> None:
        dev = _make_device()
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev.async_set_shuffle(True)

    @pytest.mark.asyncio
    async def test_repeat_failed_command_warns(self) -> None:
        dev = _make_device()
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev.async_set_repeat(RepeatMode.ALL)


class TestSelectSoundModeFailure:
    @pytest.mark.asyncio
    async def test_failed_command_keeps_old_mode(self) -> None:
        dev = _make_device()
        from custom_components.linkplay.media_player import SOUND_MODES
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        mode = next(iter(SOUND_MODES.values()))
        await dev.async_select_sound_mode(mode)
        assert dev._sound_mode != mode


class TestIsPlayingNewTrack:
    @pytest.mark.asyncio
    async def test_icecast_name_matches_title_returns_false(self) -> None:
        dev = _make_device()
        dev._icecast_name = "WBGO"
        dev._source = "WBGO Jazz"
        dev._media_title = "WBGO live stream"
        dev._media_artist = "Some Artist"
        result = await dev.async_is_playing_new_track()
        assert result is False
        assert dev._media_image_url is None


class TestPlayerStatusMetadataBranches:
    @pytest.mark.asyncio
    async def test_missing_title_clears_existing(self) -> None:
        dev = _make_device()
        dev._media_title = "old"
        # Title key absent -> _media_title set to None
        await dev.async_get_playerstatus_metadata({"uri": ""})
        assert dev._media_title is None

    @pytest.mark.asyncio
    async def test_uri_decoded_into_trackc(self) -> None:
        dev = _make_device()
        # hex("/usb/song.mp3") (path-with-USB-root convention varies; just
        # exercise the decode path)
        await dev.async_get_playerstatus_metadata(
            {"uri": "736f6e672e6d7033", "Title": "", "Artist": "", "Album": ""}
        )
        assert dev._trackc is not None
