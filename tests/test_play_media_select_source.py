"""Tests for the play_media and select_source impl bodies on LinkPlayDevice."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.media_player import MediaType
from homeassistant.const import STATE_IDLE, STATE_PLAYING


def _make_device():
    from custom_components.linkplay.media_player import LinkPlayDevice

    hass = MagicMock()
    hass.data = {"linkplay": MagicMock(entities=[])}

    with patch("custom_components.linkplay.media_player.AiohttpRequester"), patch(
        "custom_components.linkplay.media_player.UpnpFactory"
    ):
        dev = LinkPlayDevice(
            name="dev", host="1.2.3.4", protocol="http",
            sources={"line-in": "Line In", "http://radio/": "Web Radio"},
            common_sources=None,
            icecast_metadata="StationName", multiroom_wifidirect=False,
            led_off=False, volume_step=5, lastfm_api_key=None,
            uuid="", state=STATE_IDLE,
        )
    dev.entity_id = "media_player.dev"
    dev.hass = hass
    dev.call_linkplay_httpapi = AsyncMock(return_value="OK")
    dev.async_detect_stream_url_redirection = AsyncMock(side_effect=lambda u: u)
    dev.async_media_stop = AsyncMock()
    dev.async_parse_m3u_url = AsyncMock(side_effect=lambda u: u)
    dev.async_parse_pls_url = AsyncMock(side_effect=lambda u: u)
    dev.async_tracklist_via_upnp = AsyncMock()
    dev._fw_ver = "4.2"
    dev._volume = 0
    return dev


class TestPlayMedia:
    @pytest.mark.asyncio
    async def test_invalid_media_type_calls_stop_and_returns_false(self) -> None:
        dev = _make_device()
        ok = await dev._async_play_media_impl("video", "http://x")
        assert ok is False
        dev.async_media_stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_url_media_plays_and_sets_state(self) -> None:
        dev = _make_device()
        ok = await dev._async_play_media_impl(MediaType.URL, "http://stream/mp3")
        assert ok is True
        assert dev._state == STATE_PLAYING
        assert dev._media_uri == "http://stream/mp3"
        assert dev._playing_tts is False
        cmd = dev.call_linkplay_httpapi.await_args.args[0]
        assert cmd == "setPlayerCmd:play:http://stream/mp3"

    @pytest.mark.asyncio
    async def test_url_media_failed_call_returns_false(self) -> None:
        dev = _make_device()
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        ok = await dev._async_play_media_impl(MediaType.URL, "http://stream/mp3")
        assert ok is False

    @pytest.mark.asyncio
    async def test_music_type_plays_local_list(self) -> None:
        dev = _make_device()
        ok = await dev._async_play_media_impl(MediaType.MUSIC, "5")
        assert ok is True
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:playLocalList:5"
        assert dev._media_uri is None
        assert dev._media_uri_final is None
        assert dev._wait_for_mcu == 0.4

    @pytest.mark.asyncio
    async def test_url_with_http_in_id_normalized_to_url_type(self) -> None:
        dev = _make_device()
        # Even when called with MUSIC type, an http:// id is treated as URL
        # because the impl reroutes on the http prefix check.
        ok = await dev._async_play_media_impl(MediaType.URL, "http://stream/aac")
        assert ok is True
        cmd = dev.call_linkplay_httpapi.await_args.args[0]
        assert "setPlayerCmd:play:http://stream/aac" == cmd

    @pytest.mark.asyncio
    async def test_m3u_url_passed_through_parser(self) -> None:
        dev = _make_device()
        dev.async_parse_m3u_url = AsyncMock(return_value="http://resolved/aac")
        await dev._async_play_media_impl(MediaType.URL, "http://stream/list.m3u")
        dev.async_parse_m3u_url.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pls_url_passed_through_parser(self) -> None:
        dev = _make_device()
        dev.async_parse_pls_url = AsyncMock(return_value="http://resolved/mp3")
        await dev._async_play_media_impl(MediaType.URL, "http://stream/list.pls")
        dev.async_parse_pls_url.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tts_proxy_url_sets_tts_flag(self) -> None:
        dev = _make_device()
        await dev._async_play_media_impl(
            MediaType.URL, "http://localhost:8123/api/tts_proxy/abc.mp3"
        )
        assert dev._playing_tts is True
        assert dev._playing_stream is False

    @pytest.mark.asyncio
    async def test_slave_routes_to_master(self) -> None:
        dev = _make_device()
        dev._slave_mode = True
        dev._master = MagicMock()
        dev._master.async_play_media = AsyncMock()
        await dev._async_play_media_impl(MediaType.URL, "http://stream/x")
        dev._master.async_play_media.assert_awaited_once()


class TestSelectSource:
    @pytest.mark.asyncio
    async def test_unknown_source_short_circuits(self) -> None:
        dev = _make_device()
        await dev._async_select_source_impl("Not A Source")
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_http_source_plays_resolved_url(self) -> None:
        dev = _make_device()
        await dev._async_select_source_impl("Web Radio")
        cmd = dev.call_linkplay_httpapi.await_args.args[0]
        assert cmd == "setPlayerCmd:play:http://radio/"
        assert dev._source == "Web Radio"
        assert dev._state == STATE_PLAYING

    @pytest.mark.asyncio
    async def test_physical_source_uses_switchmode(self) -> None:
        dev = _make_device()
        await dev._async_select_source_impl("Line In")
        cmd = dev.call_linkplay_httpapi.await_args.args[0]
        assert cmd == "setPlayerCmd:switchmode:line-in"
        assert dev._source == "Line In"

    @pytest.mark.asyncio
    async def test_slave_routes_to_master(self) -> None:
        dev = _make_device()
        dev._slave_mode = True
        dev._master = MagicMock()
        dev._master.async_select_source = AsyncMock()
        await dev._async_select_source_impl("Line In")
        dev._master.async_select_source.assert_awaited_once_with("Line In")
        dev.call_linkplay_httpapi.assert_not_awaited()
