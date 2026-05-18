"""Tests for the stream URL resolver and playlist parser mixin."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.linkplay.stream_resolver_mixin import LinkPlayStreamResolverMixin


class _FakeDevice(LinkPlayStreamResolverMixin):
    def __init__(self) -> None:
        self.hass = MagicMock()
        self._name = "fake"
        self._host = "1.2.3.4"
        self._nometa = False


def _patch_session(session):
    return patch(
        "custom_components.linkplay.stream_resolver_mixin.async_get_clientsession",
        return_value=session,
    )


class TestRedirect:
    @pytest.mark.asyncio
    async def test_tts_proxy_passthrough(self) -> None:
        dev = _FakeDevice()
        url = "http://localhost:8123/api/tts_proxy/abc.mp3"
        assert await dev.async_detect_stream_url_redirection(url) == url

    @pytest.mark.asyncio
    async def test_follows_chain_to_terminal(self) -> None:
        dev = _FakeDevice()
        hops = [
            MagicMock(status=302, headers={"Location": "http://b/"}),
            MagicMock(status=301, headers={"Location": "http://c/"}),
            MagicMock(status=200, headers={}),
        ]
        session = MagicMock()
        session.head = AsyncMock(side_effect=hops)
        with _patch_session(session):
            final = await dev.async_detect_stream_url_redirection("http://a/")
        assert final == "http://c/"

    @pytest.mark.asyncio
    async def test_redirect_loop_caps_at_10(self) -> None:
        dev = _FakeDevice()
        # 12 hops in a row, all 302 -> would loop forever without cap.
        hops = [
            MagicMock(status=302, headers={"Location": f"http://loop{i}/"})
            for i in range(20)
        ]
        session = MagicMock()
        session.head = AsyncMock(side_effect=hops)
        with _patch_session(session):
            final = await dev.async_detect_stream_url_redirection("http://start/")
        assert session.head.await_count == 10
        assert final == "http://loop9/"

    @pytest.mark.asyncio
    async def test_network_error_returns_last_known_uri(self) -> None:
        dev = _FakeDevice()
        session = MagicMock()
        session.head = AsyncMock(side_effect=aiohttp.ClientError("boom"))
        with _patch_session(session):
            final = await dev.async_detect_stream_url_redirection("http://orig/")
        assert final == "http://orig/"


class TestParseM3uPls:
    @pytest.mark.asyncio
    async def test_m3u_returns_first_url(self) -> None:
        dev = _FakeDevice()
        body = "#EXTM3U\n#EXTINF:0,Station\nhttp://stream/aac\n"
        response = MagicMock(status=HTTPStatus.OK)
        response.text = AsyncMock(return_value=body)
        session = MagicMock()
        session.get = AsyncMock(return_value=response)
        with _patch_session(session):
            url = await dev.async_parse_m3u_url("http://server/list.m3u")
        assert url == "http://stream/aac"

    @pytest.mark.asyncio
    async def test_m3u_fetch_error_returns_playlist(self) -> None:
        dev = _FakeDevice()
        session = MagicMock()
        session.get = AsyncMock(side_effect=aiohttp.ClientError("down"))
        with _patch_session(session):
            url = await dev.async_parse_m3u_url("http://server/list.m3u")
        assert url == "http://server/list.m3u"

    @pytest.mark.asyncio
    async def test_m3u_non_200_returns_playlist(self) -> None:
        dev = _FakeDevice()
        response = MagicMock(status=HTTPStatus.NOT_FOUND)
        session = MagicMock()
        session.get = AsyncMock(return_value=response)
        with _patch_session(session):
            url = await dev.async_parse_m3u_url("http://server/list.m3u")
        assert url == "http://server/list.m3u"

    @pytest.mark.asyncio
    async def test_m3u_no_url_sets_nometa(self) -> None:
        dev = _FakeDevice()
        response = MagicMock(status=HTTPStatus.OK)
        response.text = AsyncMock(return_value="garbage only")
        session = MagicMock()
        session.get = AsyncMock(return_value=response)
        with _patch_session(session):
            url = await dev.async_parse_m3u_url("http://server/list.m3u")
        assert url == "http://server/list.m3u"
        assert dev._nometa is True

    @pytest.mark.asyncio
    async def test_pls_returns_first_file(self) -> None:
        dev = _FakeDevice()
        body = "[playlist]\nNumberOfEntries=1\nFile1=http://stream/mp3\n"
        response = MagicMock(status=HTTPStatus.OK)
        response.text = AsyncMock(return_value=body)
        session = MagicMock()
        session.get = AsyncMock(return_value=response)
        with _patch_session(session):
            url = await dev.async_parse_pls_url("http://server/list.pls")
        assert url == "http://stream/mp3"

    @pytest.mark.asyncio
    async def test_pls_no_file_sets_nometa(self) -> None:
        dev = _FakeDevice()
        body = "[playlist]\nNumberOfEntries=0\n"
        response = MagicMock(status=HTTPStatus.OK)
        response.text = AsyncMock(return_value=body)
        session = MagicMock()
        session.get = AsyncMock(return_value=response)
        with _patch_session(session):
            url = await dev.async_parse_pls_url("http://server/list.pls")
        assert url == "http://server/list.pls"
        assert dev._nometa is True
