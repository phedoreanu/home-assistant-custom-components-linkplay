"""Tests for async_browse_media on LinkPlayDevice.

The integration surfaces HA media sources plus an optional USB-disk
listing built from ``self._trackq``. These tests stub out HA's
``media_source.async_browse_media`` so we can assert the wrapping
without spinning up an HA instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from custom_components.linkplay.media_player import LinkPlayDevice


def _make_device(name: str = "device") -> "LinkPlayDevice":
    """Construct a minimal LinkPlayDevice without doing any I/O."""
    from custom_components.linkplay.media_player import LinkPlayDevice

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
            icecast_metadata="Off",
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


def _ha_source_stub(children=None):
    """Build a stand-in BrowseMedia for HA media sources."""
    from custom_components.linkplay.media_player import BrowseMedia, MediaClass

    return BrowseMedia(
        title="Media Sources",
        media_class=MediaClass.DIRECTORY,
        media_content_id="media-source://",
        media_content_type="directory",
        can_play=False,
        can_expand=True,
        children=children or [],
    )


class TestBrowseMedia:
    @pytest.mark.asyncio
    async def test_root_with_udisk_appends_usb_folder(self) -> None:
        dev = _make_device()
        dev._source_list = {"udisk": "USB stick", "line-in": "Line-in"}
        dev._trackq = ["Track 1.mp3", "Track 2.mp3", "Track 3.mp3"]

        with patch(
            "custom_components.linkplay.media_player.media_source.async_browse_media",
            new=AsyncMock(return_value=_ha_source_stub()),
        ):
            result = await dev.async_browse_media()

        assert len(result.children) == 1
        usb_folder = result.children[0]
        assert usb_folder.media_content_id == "linkplay_udisk"
        assert usb_folder.title == "USB stick"
        assert usb_folder.can_expand is True

    @pytest.mark.asyncio
    async def test_root_without_udisk_returns_ha_sources_only(self) -> None:
        dev = _make_device()
        dev._source_list = {"line-in": "Line-in"}
        dev._trackq = []

        with patch(
            "custom_components.linkplay.media_player.media_source.async_browse_media",
            new=AsyncMock(return_value=_ha_source_stub()),
        ):
            result = await dev.async_browse_media()

        assert result.children == []

    @pytest.mark.asyncio
    async def test_root_with_udisk_but_no_tracks_returns_ha_only(self) -> None:
        dev = _make_device()
        dev._source_list = {"udisk": "USB stick"}
        dev._trackq = []

        with patch(
            "custom_components.linkplay.media_player.media_source.async_browse_media",
            new=AsyncMock(return_value=_ha_source_stub()),
        ):
            result = await dev.async_browse_media()

        assert result.children == []

    @pytest.mark.asyncio
    async def test_expanding_udisk_folder_returns_tracks(self) -> None:
        dev = _make_device()
        dev._source_list = {"udisk": "USB stick"}
        dev._trackq = ["Track 1.mp3", "Track 2.mp3"]

        result = await dev.async_browse_media(media_content_id="linkplay_udisk")

        assert result.media_content_id == "linkplay_udisk"
        assert len(result.children) == 2
        first, second = result.children
        assert first.title == "Track 1.mp3"
        assert first.media_content_id == "1"
        assert first.can_play is True
        assert second.media_content_id == "2"

    @pytest.mark.asyncio
    async def test_inner_ha_media_source_path_pass_through(self) -> None:
        """Non-root media_content_ids delegate straight to HA's media_source.

        Verifies we don't accidentally append the USB folder on every
        recursion into HA's media-source tree.
        """
        dev = _make_device()
        dev._source_list = {"udisk": "USB stick"}
        dev._trackq = ["Track.mp3"]

        ha_payload = _ha_source_stub()
        with patch(
            "custom_components.linkplay.media_player.media_source.async_browse_media",
            new=AsyncMock(return_value=ha_payload),
        ):
            result = await dev.async_browse_media(
                media_content_id="media-source://some/path"
            )

        assert result is ha_payload
        assert result.children == []
