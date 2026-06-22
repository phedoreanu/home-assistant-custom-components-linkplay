"""Tests for the optional Last.fm cover-art mixin."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.linkplay.lastfm_mixin import (
    LinkPlayLastFmMixin,
    _RATELIMIT_MARKER,
)


class _FakeDevice(LinkPlayLastFmMixin):
    def __init__(self) -> None:
        self.hass = MagicMock()
        self._name = "fake"
        self._lastfm_api_key = "deadbeef"
        self._media_title = "Track"
        self._media_artist = "Artist"
        self._media_image_url = None


def _unwrap(method):
    return method.__wrapped__


def _patch_session(session):
    return patch(
        "custom_components.linkplay.lastfm_mixin.async_get_clientsession",
        return_value=session,
    )


class TestCallUpdateLastfm:
    @pytest.mark.asyncio
    async def test_returns_json_on_ok(self) -> None:
        dev = _FakeDevice()
        response = MagicMock(status=HTTPStatus.OK)
        response.json = AsyncMock(return_value={"k": "v"})
        session = MagicMock()
        session.get = AsyncMock(return_value=response)
        with _patch_session(session):
            result = await dev.call_update_lastfm("track.getInfo", "x=1")
        assert result == {"k": "v"}

    @pytest.mark.asyncio
    async def test_non_200_returns_false(self) -> None:
        dev = _FakeDevice()
        response = MagicMock(status=HTTPStatus.FORBIDDEN)
        session = MagicMock()
        session.get = AsyncMock(return_value=response)
        with _patch_session(session):
            assert await dev.call_update_lastfm("track.getInfo", "x=1") is False

    @pytest.mark.asyncio
    async def test_client_error_returns_false(self) -> None:
        dev = _FakeDevice()
        session = MagicMock()
        session.get = AsyncMock(side_effect=aiohttp.ClientError())
        with _patch_session(session):
            assert await dev.call_update_lastfm("track.getInfo", "x=1") is False


class TestCoverart:
    @pytest.mark.asyncio
    async def test_no_artist_or_title_clears_image(self) -> None:
        dev = _FakeDevice()
        dev._media_title = None
        dev._media_image_url = "stale"
        await _unwrap(dev.async_get_lastfm_coverart)(dev)
        assert dev._media_image_url is None

    @pytest.mark.asyncio
    async def test_populates_image_from_extralarge(self) -> None:
        dev = _FakeDevice()
        payload = {
            "track": {
                "album": {
                    "image": [
                        {"size": "small", "#text": "small.jpg"},
                        {"size": "medium", "#text": "medium.jpg"},
                        {"size": "large", "#text": "large.jpg"},
                        {"size": "extralarge", "#text": "xl.jpg"},
                    ]
                }
            }
        }
        dev.call_update_lastfm = AsyncMock(return_value=payload)
        await _unwrap(dev.async_get_lastfm_coverart)(dev)
        assert dev._media_image_url == "xl.jpg"

    @pytest.mark.asyncio
    async def test_malformed_payload_clears_image(self) -> None:
        dev = _FakeDevice()
        dev.call_update_lastfm = AsyncMock(return_value={"not": "right"})
        await _unwrap(dev.async_get_lastfm_coverart)(dev)
        assert dev._media_image_url is None

    @pytest.mark.asyncio
    async def test_ratelimit_marker_skips_assignment(self) -> None:
        dev = _FakeDevice()
        marker_url = f"https://lastfm/{ _RATELIMIT_MARKER }.jpg"
        payload = {
            "track": {"album": {"image": [{}, {}, {}, {"#text": marker_url}]}}
        }
        dev.call_update_lastfm = AsyncMock(return_value=payload)
        await _unwrap(dev.async_get_lastfm_coverart)(dev)
        assert dev._media_image_url is None
