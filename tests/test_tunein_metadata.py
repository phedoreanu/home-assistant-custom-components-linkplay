"""Regression tests for the TuneIn / live-stream metadata pipeline.

Covers the three-source fallback chain wired in v4.0.24:

    getPlayerStatus -> UPnP AVTransport -> icy-headers

and the UPnP-init bug fix that moved ``_upnp_device`` creation out of
the old-firmware force-wifidirect branch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.linkplay.media_player import LinkPlayDevice


def _make_device(name: str = "device") -> LinkPlayDevice:
    hass = MagicMock()
    hass.data = {"linkplay": MagicMock(entities=[])}

    with patch("custom_components.linkplay.media_player.AiohttpRequester"), patch(
        "custom_components.linkplay.media_player.UpnpFactory"
    ):
        dev = LinkPlayDevice(
            name=name,
            host="1.2.3.4",
            protocol="http",
            sources=None,
            common_sources=None,
            icecast_metadata="StationName",
            multiroom_wifidirect=False,
            led_off=False,
            volume_step=5,
            lastfm_api_key=None,
            uuid="",
            state="idle",
        )
    dev.entity_id = f"media_player.{name}"
    dev.hass = hass
    return dev


# DIDL-Lite metadata the device would return for a TuneIn stream.
_TUNEIN_DIDL = (
    '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    ' xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
    "<item>"
    "<dc:title>Carbon Based Lifeforms - World Of Sleepers</dc:title>"
    "<upnp:artist>Carbon Based Lifeforms</upnp:artist>"
    "<upnp:album>SomaFM</upnp:album>"
    "<upnp:albumArtURI>https://cover.example/img.jpg</upnp:albumArtURI>"
    "</item>"
    "</DIDL-Lite>"
)


def _upnp_with_didl(didl: str | None) -> MagicMock:
    """Build a stand-in ``_upnp_device`` whose AVTransport.GetMediaInfo returns DIDL."""
    service = MagicMock()
    action = MagicMock()
    action.async_call = AsyncMock(
        return_value={
            "CurrentURI": "http://stream.example/tunein.aac",
            "TrackSource": "http://stream.example/tunein.aac",
            "CurrentURIMetaData": didl,
        }
    )
    service.action = MagicMock(return_value=action)

    upnp_device = MagicMock()
    upnp_device.service = MagicMock(return_value=service)
    return upnp_device


class TestTuneInMetadataFlow:
    @pytest.mark.asyncio
    async def test_upnp_didl_populates_title_artist(self) -> None:
        """When playerstatus has no metadata, UPnP DIDL-Lite fills in title + artist."""
        dev = _make_device()
        dev._upnp_device = _upnp_with_didl(_TUNEIN_DIDL)

        await dev.async_update_via_upnp()

        assert dev._media_title == "Carbon Based Lifeforms - World Of Sleepers"
        assert dev._media_artist == "Carbon Based Lifeforms"
        assert dev._media_album == "SomaFM"
        assert dev._media_image_url == "https://cover.example/img.jpg"

    @pytest.mark.asyncio
    async def test_upnp_skipped_when_no_device(self) -> None:
        """Without an initialised _upnp_device the method must be a noop."""
        dev = _make_device()
        dev._upnp_device = None
        dev._media_title = "should not change"

        await dev.async_update_via_upnp()

        assert dev._media_title == "should not change"

    @pytest.mark.asyncio
    async def test_upnp_didl_missing_metadata_is_silent(self) -> None:
        """When DIDL is None the method returns without crashing."""
        dev = _make_device()
        dev._upnp_device = _upnp_with_didl(None)

        await dev.async_update_via_upnp()

        # Nothing populated, no exception.
        assert dev._media_title is None
        assert dev._media_artist is None

    @pytest.mark.asyncio
    async def test_playerstatus_metadata_short_circuits_upnp(self) -> None:
        """If getPlayerStatus already filled Title + Artist, no extra fetch is needed.

        Exercises async_get_playerstatus_metadata directly so we
        confirm the cheap path returns True (the flag callers use to
        skip UPnP / icecast fallbacks).
        """
        dev = _make_device()
        # 'Test Artist' / 'Test Track' hex-encoded
        plr_stat = {
            "Title": "5465737420547261636b",   # "Test Track"
            "Artist": "546573742041727469737421",  # "Test Artist!"
            "Album": "",
            "uri": "",
        }

        got = await dev.async_get_playerstatus_metadata(plr_stat)

        assert got is True
        assert dev._media_title == "Test Track"
        assert dev._media_artist == "Test Artist!"

    @pytest.mark.asyncio
    async def test_playerstatus_metadata_returns_false_on_empty(self) -> None:
        """All-empty fields -> False so the caller falls through to UPnP / icecast."""
        dev = _make_device()
        plr_stat = {"Title": "", "Artist": "", "Album": "", "uri": ""}

        got = await dev.async_get_playerstatus_metadata(plr_stat)

        assert got is False
        assert dev._media_title is None
        assert dev._media_artist is None
