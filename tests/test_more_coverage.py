"""Targeted regressions for remaining media_player.py / multiroom_mixin /
somafm holes - kept in one file so we don't sprawl across many test
modules just to bump coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
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
    dev.async_write_ha_state = MagicMock()
    dev.call_linkplay_httpapi = AsyncMock(return_value="OK")
    return dev


class TestDebugAttr:
    def test_debug_attr_branch(self, monkeypatch) -> None:
        """Flip ``DEBUGSTR_ATTR`` so the ``atrdbg`` accumulator runs."""
        monkeypatch.setattr(
            "custom_components.linkplay.media_player.DEBUGSTR_ATTR", True
        )
        dev = _make_device()
        dev._playing_localfile = True
        dev._playing_spotify = True
        dev._playing_webplaylist = True
        dev._playing_stream = True
        dev._playing_liveinput = True
        dev._playing_tts = True
        dev._playing_mediabrowser = True
        attrs = dev.extra_state_attributes
        # debug string should mention every flag we set
        from custom_components.linkplay.media_player import ATTR_DEBUG
        assert "_playing_localfile" in attrs[ATTR_DEBUG]
        assert "_playing_spotify" in attrs[ATTR_DEBUG]
        assert "_playing_stream" in attrs[ATTR_DEBUG]


class TestMediaSourceResolution:
    @pytest.mark.asyncio
    async def test_local_media_source_url_resolved(self) -> None:
        dev = _make_device()
        dev._fw_ver = "4.2"
        dev._volume = 0  # crossfade short-circuits
        dev.async_detect_stream_url_redirection = AsyncMock(side_effect=lambda u: u)

        # Fake play item from media_source.async_resolve_media
        play_item = MagicMock()
        play_item.url = "/media/local/Song.mp3"
        play_item.mime_type = "audio/mpeg"

        with patch(
            "custom_components.linkplay.media_player.media_source.is_media_source_id",
            return_value=True,
        ), patch(
            "custom_components.linkplay.media_player.media_source.async_resolve_media",
            new=AsyncMock(return_value=play_item),
        ), patch(
            "custom_components.linkplay.media_player.async_process_play_media_url",
            return_value="http://ha-server/media/Song.mp3",
        ):
            ok = await dev._async_play_media_impl(
                "music",
                "media-source://media_source/local/Song.mp3",
            )
        assert ok is True
        assert dev._media_source_uri == "media-source://media_source/local/Song.mp3"

    @pytest.mark.asyncio
    async def test_radio_browser_does_not_set_mediabrowser_flag(self) -> None:
        dev = _make_device()
        dev._fw_ver = "4.2"
        dev._volume = 0
        dev.async_detect_stream_url_redirection = AsyncMock(side_effect=lambda u: u)

        play_item = MagicMock()
        play_item.url = "http://radio.cdn/stream.mp3"
        play_item.mime_type = "audio/mpeg"

        with patch(
            "custom_components.linkplay.media_player.media_source.is_media_source_id",
            return_value=True,
        ), patch(
            "custom_components.linkplay.media_player.media_source.async_resolve_media",
            new=AsyncMock(return_value=play_item),
        ), patch(
            "custom_components.linkplay.media_player.async_process_play_media_url",
            return_value="http://radio.cdn/stream.mp3",
        ):
            ok = await dev._async_play_media_impl(
                "music",
                "media-source://radio_browser/some-station",
            )
        assert ok is True
        assert dev._playing_mediabrowser is False

    @pytest.mark.asyncio
    async def test_unsupported_mime_type_returns_false(self) -> None:
        dev = _make_device()
        dev._fw_ver = "4.2"
        dev._volume = 0

        play_item = MagicMock()
        play_item.url = "http://x/video.mp4"
        play_item.mime_type = "video/mp4"

        with patch(
            "custom_components.linkplay.media_player.media_source.is_media_source_id",
            return_value=True,
        ), patch(
            "custom_components.linkplay.media_player.media_source.async_resolve_media",
            new=AsyncMock(return_value=play_item),
        ):
            ok = await dev._async_play_media_impl(
                "music",
                "media-source://media_source/foo.mp4",
            )
        assert ok is False
        assert dev._playing_mediabrowser is False


class TestMultiroomJoinUnjoin:
    @pytest.mark.asyncio
    async def test_join_unavailable_master_short_circuits(self) -> None:
        from homeassistant.const import STATE_UNAVAILABLE

        dev = _make_device()
        dev._state = STATE_UNAVAILABLE
        slaves = [_make_device()]
        await dev.async_join(slaves)
        # No HTTP traffic because the master is unavailable
        dev.call_linkplay_httpapi.assert_not_called()

    @pytest.mark.asyncio
    async def test_join_wifi_direct_command_shape(self) -> None:
        dev = _make_device()
        dev._multiroom_wifidirect = True
        dev._ssid = "deadbeef"
        dev._wifi_channel = "6"
        slave = _make_device()
        slave.entity_id = "media_player.slave"
        slave._is_master = False
        slave._slave_mode = False
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")
        await dev.async_join([slave])
        sent = slave.call_linkplay_httpapi.await_args.args[0]
        assert sent.startswith("ConnectMasterAp:ssid=deadbeef")

    @pytest.mark.asyncio
    async def test_join_slave_already_in_slave_mode_unjoins_first(self) -> None:
        dev = _make_device()
        dev._multiroom_wifidirect = False
        dev._host = "1.2.3.4"
        slave = _make_device()
        slave.entity_id = "media_player.slave"
        slave._is_master = False
        slave._slave_mode = True
        slave.async_unjoin_me = AsyncMock()
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")
        await dev.async_join([slave])
        slave.async_unjoin_me.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_join_slave_with_master_flag_unjoins_first(self) -> None:
        dev = _make_device()
        slave = _make_device()
        slave.entity_id = "media_player.slave"
        slave._is_master = True
        slave.async_unjoin_all = AsyncMock()
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")
        await dev.async_join([slave])
        slave.async_unjoin_all.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unjoin_player_master_calls_unjoin_all(self) -> None:
        dev = _make_device()
        dev._is_master = True
        dev._slave_mode = False
        dev.async_unjoin_all = AsyncMock()
        await dev.async_unjoin_player()
        dev.async_unjoin_all.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unjoin_player_slave_calls_unjoin_me(self) -> None:
        dev = _make_device()
        dev._is_master = False
        dev._slave_mode = True
        dev.async_unjoin_me = AsyncMock()
        await dev.async_unjoin_player()
        dev.async_unjoin_me.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unjoin_me_router_mode_success(self) -> None:
        dev = _make_device()
        dev._slave_mode = True
        dev._multiroom_wifidirect = False
        master = _make_device()
        master.async_remove_from_group = AsyncMock()
        master.async_write_ha_state = MagicMock()
        dev._master = master
        dev.call_linkplay_httpapi = AsyncMock(return_value="OK")
        await dev.async_unjoin_me()
        master.async_remove_from_group.assert_awaited_once()
        assert dev._slave_mode is False

    @pytest.mark.asyncio
    async def test_unjoin_me_failure_logs_and_keeps_state(self) -> None:
        dev = _make_device()
        dev._slave_mode = True
        dev._multiroom_wifidirect = False
        dev._master = _make_device()
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev.async_unjoin_me()
        assert dev._slave_mode is True

    @pytest.mark.asyncio
    async def test_unjoin_me_wifidirect_uses_kickout(self) -> None:
        dev = _make_device()
        dev._slave_mode = True
        dev._multiroom_wifidirect = True
        dev._slave_ip = "10.0.0.50"
        master = _make_device()
        master._is_master = True
        master.entity_id = "media_player.master"
        master.call_linkplay_httpapi = AsyncMock(return_value="OK")
        master.async_remove_from_group = AsyncMock()
        master.async_write_ha_state = MagicMock()
        dev.hass.data["linkplay"].entities = [master]
        dev._master = master
        await dev.async_unjoin_me()
        cmd = master.call_linkplay_httpapi.await_args.args[0]
        assert cmd == "multiroom:SlaveKickout:10.0.0.50"


class TestSomaFmEdgeCases:
    @pytest.fixture(autouse=True)
    def _reset_channel_cache(self):
        import custom_components.linkplay.somafm_fetcher_mixin as mod
        mod._channel_map_cache = None
        yield
        mod._channel_map_cache = None

    def _dev(self):
        dev = _make_device()
        dev._somafm_cached_station = "SomaFM: Drone Zone"
        return dev

    @pytest.mark.asyncio
    async def test_channel_map_http_error_caches_empty(self) -> None:
        import custom_components.linkplay.somafm_fetcher_mixin as mod
        dev = self._dev()
        dev._media_title = "SomaFM: Drone Zone"
        # channels.json returns 503 -> empty cache; songs.json returns 200 OK
        channels_resp = MagicMock()
        channels_resp.status = 503
        songs_resp = MagicMock()
        songs_resp.status = 200
        songs_resp.json = AsyncMock(
            return_value={"songs": [{"title": "T", "artist": "A"}]}
        )
        session = MagicMock()
        session.get = AsyncMock(side_effect=[channels_resp, songs_resp])
        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            await dev.async_update_from_somafm.__wrapped__(dev)
        assert mod._channel_map_cache == {}

    @pytest.mark.asyncio
    async def test_channel_map_fetch_exception_cached_empty(self) -> None:
        import custom_components.linkplay.somafm_fetcher_mixin as mod
        dev = self._dev()
        dev._media_title = "SomaFM: Drone Zone"
        # channels.json raises; songs request still succeeds via alphanumonly fallback
        songs_resp = MagicMock()
        songs_resp.status = 200
        songs_resp.json = AsyncMock(
            return_value={"songs": [{"title": "T", "artist": "A"}]}
        )

        async def _get(url, *a, **kw):
            if "channels.json" in url:
                raise aiohttp.ClientError("boom")
            return songs_resp

        session = MagicMock()
        session.get = AsyncMock(side_effect=_get)
        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            await dev.async_update_from_somafm.__wrapped__(dev)
        assert mod._channel_map_cache == {}

    @pytest.mark.asyncio
    async def test_song_fetch_timeout_returns_false(self) -> None:
        dev = self._dev()
        dev._media_title = "SomaFM: Drone Zone"
        session = MagicMock()
        session.get = AsyncMock(side_effect=TimeoutError())
        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm.__wrapped__(dev)
        assert ok is False

    @pytest.mark.asyncio
    async def test_song_json_parse_error_returns_false(self) -> None:
        dev = self._dev()
        dev._media_title = "SomaFM: Drone Zone"
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(side_effect=ValueError("bad json"))
        session = MagicMock()
        session.get = AsyncMock(return_value=resp)
        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm.__wrapped__(dev)
        assert ok is False

    @pytest.mark.asyncio
    async def test_songs_missing_artist_returns_false(self) -> None:
        dev = self._dev()
        dev._media_title = "SomaFM: Drone Zone"
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"songs": [{"title": "x"}]})
        session = MagicMock()
        session.get = AsyncMock(return_value=resp)
        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm.__wrapped__(dev)
        assert ok is False


def _build_tcp_stub(hass_executor):
    """Build a LinkPlayAPIClientMixin host class for TCP UART tests."""
    from custom_components.linkplay.api_client_mixin import LinkPlayAPIClientMixin

    class _Stub(LinkPlayAPIClientMixin):
        def __init__(self):
            self._host = "1.2.3.4"
            self._name = "dev"
            self.hass = MagicMock()
            self.hass.async_add_executor_job = hass_executor

    return _Stub()


class _SocketStub:
    """Minimal context-manager socket fake. ``raise_on_connect`` toggles
    whether ``.connect(...)`` raises OSError."""

    def __init__(self, raise_on_connect: bool):
        self._raise = raise_on_connect

    def __call__(self, *_a, **_kw):
        # Allow ``socket.socket(AF_INET, SOCK_STREAM)`` to return us.
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def settimeout(self, *_a, **_kw):
        return None

    def connect(self, *_a, **_kw):
        if self._raise:
            raise OSError("Connection refused")

    def send(self, *_a, **_kw):
        return None

    def recv(self, *_a, **_kw):
        return b"AXXok-response\x00\x00"


class TestApiClientTcpUart:
    @pytest.mark.asyncio
    async def test_tcpuart_socket_error_returns_none(self) -> None:
        """Exercise the OSError branch inside ``_send_recv``."""
        import socket as socket_mod

        async def _run(fn, *args):
            return fn(*args)

        with patch.object(socket_mod, "socket", _SocketStub(raise_on_connect=True)):
            stub = _build_tcp_stub(_run)
            result = await stub.call_linkplay_tcpuart("MCU+PAS+RAKOIT:LED:0&")
        assert result is None

    @pytest.mark.asyncio
    async def test_tcpuart_success_returns_decoded_response(self) -> None:
        """Cover the marker-decode tail of ``call_linkplay_tcpuart``."""
        import socket as socket_mod

        async def _run(fn, *args):
            return fn(*args)

        with patch.object(socket_mod, "socket", _SocketStub(raise_on_connect=False)):
            stub = _build_tcp_stub(_run)
            result = await stub.call_linkplay_tcpuart("MCU+PAS+RAKOIT:LED:0&")
        assert result is not None
