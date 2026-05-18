"""Tests for the icecast HTTP fetch + parsing mixin."""

from __future__ import annotations

import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.linkplay.icecast_fetcher_mixin import (
    LinkPlayIcecastFetcherMixin,
    _fetch_icecast_headers_and_chunks,
)


class _FakeDevice(LinkPlayIcecastFetcherMixin):
    def __init__(self, mode: str = "StationNameSongTitle") -> None:
        self.hass = MagicMock()
        self.hass.async_add_executor_job = AsyncMock()
        self._name = "fake"
        self._icecast_meta = mode
        self._media_uri_final = "http://stream/aac"
        self._media_title = None
        self._media_artist = None
        self._media_image_url = None
        self._icecast_name = None


def _unwrap(method):
    """Strip the @Throttle wrapper so we can drive the underlying coro
    directly and not race the rate-limit clock."""
    return method.__wrapped__


class TestUpdateFromIcecast:
    @pytest.mark.asyncio
    async def test_off_short_circuits(self) -> None:
        dev = _FakeDevice(mode="Off")
        assert await _unwrap(dev.async_update_from_icecast)(dev) is True
        dev.hass.async_add_executor_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetch_failure_clears_metadata(self) -> None:
        dev = _FakeDevice()
        dev._media_title = "stale"
        dev._media_artist = "stale"
        dev.hass.async_add_executor_job = AsyncMock(side_effect=RuntimeError("net"))
        await _unwrap(dev.async_update_from_icecast)(dev)
        assert dev._media_title is None
        assert dev._media_artist is None
        assert dev._icecast_name is None

    @pytest.mark.asyncio
    async def test_station_name_mode_only_sets_title(self) -> None:
        dev = _FakeDevice(mode="StationName")
        dev.hass.async_add_executor_job = AsyncMock(
            return_value=("My Radio", "16000", [])
        )
        await _unwrap(dev.async_update_from_icecast)(dev)
        assert dev._media_title == "My Radio"
        assert dev._media_artist is None
        assert dev._icecast_name == "My Radio"

    @pytest.mark.asyncio
    async def test_missing_metaint_falls_back_to_station(self) -> None:
        """No icy-metaint header -> can't parse StreamTitle chunks, so
        fall back to station-name display even in StationNameSongTitle."""
        dev = _FakeDevice(mode="StationNameSongTitle")
        dev.hass.async_add_executor_job = AsyncMock(
            return_value=("My Radio", None, [])
        )
        await _unwrap(dev.async_update_from_icecast)(dev)
        assert dev._media_title == "My Radio"
        assert dev._media_artist is None

    @pytest.mark.asyncio
    async def test_chunk_without_streamtitle_falls_back_then_recovers(self) -> None:
        """Empty leading chunk falls back to station name; a later chunk
        with a real StreamTitle overrides it."""
        dev = _FakeDevice(mode="StationNameSongTitle")
        empty_chunk = b""
        good_chunk = b"StreamTitle='Carbon - Mind';"
        dev.hass.async_add_executor_job = AsyncMock(
            return_value=("My Radio", "16000", [empty_chunk, good_chunk])
        )
        await _unwrap(dev.async_update_from_icecast)(dev)
        assert dev._media_artist == "Carbon"
        assert dev._media_title == "Mind"

    @pytest.mark.asyncio
    async def test_chunk_with_streamtitle_populates_artist_title(self) -> None:
        dev = _FakeDevice(mode="StationNameSongTitle")
        chunk = b"StreamTitle='Artist Name - Track Name';"
        dev.hass.async_add_executor_job = AsyncMock(
            return_value=("My Radio", "16000", [chunk])
        )
        await _unwrap(dev.async_update_from_icecast)(dev)
        assert dev._media_artist == "Artist Name"
        assert dev._media_title == "Track Name"


class TestFetchExecutor:
    """Test the blocking _fetch_icecast_headers_and_chunks helper directly
    so the network path (currently mocked away) actually executes."""

    def _build_resp(self, *, icy_name: str | None, metaint: int | None, payload: bytes) -> MagicMock:
        resp = MagicMock()
        resp.headers = {}
        if icy_name is not None:
            resp.headers["icy-name"] = icy_name
        if metaint is not None:
            resp.headers["icy-metaint"] = str(metaint)
        # Simulate the read sequence:
        #   read(metaint) -> audio bytes (discarded)
        #   read(1)       -> metadata length byte
        #   read(N*16)    -> metadata block
        resp.read = MagicMock(side_effect=payload)
        resp.close = MagicMock()
        return resp

    def test_returns_headers_and_no_chunks_when_metaint_missing(self) -> None:
        resp = self._build_resp(icy_name="MyRadio", metaint=None, payload=[])
        with patch(
            "custom_components.linkplay.icecast_fetcher_mixin.urllib.request.urlopen",
            return_value=resp,
        ):
            name, metaint, chunks = _fetch_icecast_headers_and_chunks("http://x/")
        assert name == "MyRadio"
        assert metaint is None
        assert chunks == []
        resp.close.assert_called_once()

    def test_reads_one_metadata_chunk_then_terminates(self) -> None:
        meta = b"StreamTitle='A - B';"
        length_byte = struct.pack("B", (len(meta) + 15) // 16)
        # First iteration: audio block (ignored), length byte, metadata
        # Second iteration: empty length byte -> loop break
        sequence = [
            b"\x00" * 16,        # iter1: audio block (discarded)
            length_byte,         # iter1: length byte
            meta.ljust(((len(meta) + 15) // 16) * 16, b"\0"),  # iter1: metadata
            b"\x00" * 16,        # iter2: audio block
            b"",                 # iter2: empty length -> break
        ]
        resp = self._build_resp(icy_name="R", metaint=16, payload=sequence)
        with patch(
            "custom_components.linkplay.icecast_fetcher_mixin.urllib.request.urlopen",
            return_value=resp,
        ):
            name, metaint, chunks = _fetch_icecast_headers_and_chunks("http://x/")
        assert name == "R"
        assert metaint == "16"
        assert chunks[0].startswith(b"StreamTitle=")
