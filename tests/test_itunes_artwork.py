"""Tests for the iTunes Search artwork fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.linkplay.itunes_artwork_mixin import (
    LinkPlayItunesArtworkMixin,
    _upscale_artwork,
)


class _Stub(LinkPlayItunesArtworkMixin):
    def __init__(self):
        self._media_artist = "Carbon Based Lifeforms"
        self._media_title = "Carbon Mind"
        self._media_image_url = "https://api.somafm.com/img/groovesalad600.jpg"
        self._icecast_meta = "StationName"
        self._name = "dev"
        self._host = "1.2.3.4"
        self.hass = MagicMock()


def _ok_response(payload):
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value=payload)
    return response


class TestUpscale:
    def test_replaces_100x100_with_600x600(self) -> None:
        before = "https://is1.mzstatic.com/image/thumb/abc/100x100bb.jpg"
        after = _upscale_artwork(before)
        assert after == "https://is1.mzstatic.com/image/thumb/abc/600x600bb.jpg"

    def test_leaves_url_unchanged_when_no_size_marker(self) -> None:
        u = "https://example.com/cover.png"
        assert _upscale_artwork(u) == u


class TestAsyncGetItunesArtwork:
    @pytest.mark.asyncio
    async def test_happy_path_replaces_image_url(self) -> None:
        stub = _Stub()
        payload = {
            "results": [
                {
                    "artworkUrl100": "https://is1.mzstatic.com/cover/100x100bb.jpg",
                    "trackName": "Carbon Mind",
                }
            ]
        }
        session = MagicMock()
        session.get = AsyncMock(return_value=_ok_response(payload))
        with patch(
            "custom_components.linkplay.itunes_artwork_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await stub.async_get_itunes_artwork.__wrapped__(stub)
        assert ok is True
        assert "600x600bb.jpg" in stub._media_image_url

    @pytest.mark.asyncio
    async def test_empty_results_returns_false_and_caches(self) -> None:
        stub = _Stub()
        session = MagicMock()
        session.get = AsyncMock(return_value=_ok_response({"results": []}))
        with patch(
            "custom_components.linkplay.itunes_artwork_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await stub.async_get_itunes_artwork.__wrapped__(stub)
        assert ok is False
        # Channel-level fallback URL was not replaced
        assert stub._media_image_url.endswith("groovesalad600.jpg")
        # Cache populated so the next call short-circuits
        assert stub._itunes_last_lookup == ("Carbon Based Lifeforms", "Carbon Mind")

    @pytest.mark.asyncio
    async def test_missing_artist_short_circuits(self) -> None:
        stub = _Stub()
        stub._media_artist = None
        ok = await stub.async_get_itunes_artwork.__wrapped__(stub)
        assert ok is False

    @pytest.mark.asyncio
    async def test_repeated_call_for_same_track_skips_network(self) -> None:
        stub = _Stub()
        stub._itunes_last_lookup = ("Carbon Based Lifeforms", "Carbon Mind")
        # If we ever hit the session, this assertion will explode.
        session = MagicMock()
        session.get = AsyncMock(side_effect=AssertionError("should not be called"))
        with patch(
            "custom_components.linkplay.itunes_artwork_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await stub.async_get_itunes_artwork.__wrapped__(stub)
        assert ok is False

    @pytest.mark.asyncio
    async def test_http_error_returns_false(self) -> None:
        stub = _Stub()
        resp = MagicMock()
        resp.status = 503
        session = MagicMock()
        session.get = AsyncMock(return_value=resp)
        with patch(
            "custom_components.linkplay.itunes_artwork_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await stub.async_get_itunes_artwork.__wrapped__(stub)
        assert ok is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self) -> None:
        stub = _Stub()
        session = MagicMock()
        session.get = AsyncMock(side_effect=TimeoutError())
        with patch(
            "custom_components.linkplay.itunes_artwork_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await stub.async_get_itunes_artwork.__wrapped__(stub)
        assert ok is False

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_false(self) -> None:
        stub = _Stub()
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(side_effect=ValueError("bad json"))
        session = MagicMock()
        session.get = AsyncMock(return_value=resp)
        with patch(
            "custom_components.linkplay.itunes_artwork_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await stub.async_get_itunes_artwork.__wrapped__(stub)
        assert ok is False

    @pytest.mark.asyncio
    async def test_client_error_returns_false(self) -> None:
        stub = _Stub()
        session = MagicMock()
        session.get = AsyncMock(side_effect=aiohttp.ClientError("boom"))
        with patch(
            "custom_components.linkplay.itunes_artwork_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await stub.async_get_itunes_artwork.__wrapped__(stub)
        assert ok is False
