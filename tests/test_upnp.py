"""Tests for the UPnP metadata + queue + preset-snap mixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.linkplay.upnp_mixin import LinkPlayUPnPMixin


_DIDL_OK = """<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
                xmlns:dc="http://purl.org/dc/elements/1.1/"
                xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
  <item>
    <dc:title>Carbon Mind</dc:title>
    <upnp:artist>Carbon Based Lifeforms</upnp:artist>
    <upnp:album>World Of Sleepers</upnp:album>
    <upnp:albumArtURI>https://example.com/art.jpg</upnp:albumArtURI>
  </item>
</DIDL-Lite>"""

_DIDL_BAD_URL = """<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
                xmlns:dc="http://purl.org/dc/elements/1.1/"
                xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
  <item>
    <dc:title>Track</dc:title>
    <upnp:albumArtURI>not-a-url</upnp:albumArtURI>
  </item>
</DIDL-Lite>"""

_DIDL_MALFORMED = "<DIDL-Lite> bad & unescaped"

_QUEUE_XML = """<root>
  <Playlist>
    <Tracks>
      <URL>/media/sda1/track1.mp3</URL>
      <URL>/media/sda1/track2.mp3</URL>
      <URL>http://elsewhere/skip.mp3</URL>
    </Tracks>
  </Playlist>
</root>"""


class _FakeDevice(LinkPlayUPnPMixin):
    def __init__(self) -> None:
        self.entity_id = "media_player.fake"
        self._service = None
        self._upnp_device = None
        self._media_title = None
        self._media_artist = None
        self._media_album = None
        self._media_image_url = None
        self._media_uri_final = None
        self._trackc = None
        self._trackq: list[str] = []
        self._playing_spotify = False


def _service_with_action(name: str, return_value):
    """Build a UPnP service double whose service.action(name).async_call returns the value."""
    action = MagicMock()
    action.async_call = AsyncMock(return_value=return_value)
    service = MagicMock()
    service.action = MagicMock(return_value=action)
    return service


class TestUpdateViaUpnp:
    @pytest.mark.asyncio
    async def test_no_upnp_device_short_circuits(self) -> None:
        dev = _FakeDevice()
        await dev.async_update_via_upnp()
        # nothing to assert; just no exception

    @pytest.mark.asyncio
    async def test_populates_metadata_from_didl(self) -> None:
        dev = _FakeDevice()
        service = _service_with_action(
            "GetMediaInfo",
            {
                "CurrentURI": "http://stream/x",
                "TrackSource": "http://stream/x-final",
                "CurrentURIMetaData": _DIDL_OK,
            },
        )
        dev._upnp_device = MagicMock()
        dev._upnp_device.service = MagicMock(return_value=service)
        await dev.async_update_via_upnp()
        assert dev._media_title == "Carbon Mind"
        assert dev._media_artist == "Carbon Based Lifeforms"
        assert dev._media_album == "World Of Sleepers"
        assert dev._media_image_url == "https://example.com/art.jpg"
        assert dev._media_uri_final == "http://stream/x-final"

    @pytest.mark.asyncio
    async def test_invalid_url_image_dropped(self) -> None:
        dev = _FakeDevice()
        service = _service_with_action(
            "GetMediaInfo",
            {"CurrentURI": "x", "TrackSource": "x", "CurrentURIMetaData": _DIDL_BAD_URL},
        )
        dev._upnp_device = MagicMock()
        dev._upnp_device.service = MagicMock(return_value=service)
        await dev.async_update_via_upnp()
        assert dev._media_title == "Track"
        assert dev._media_image_url is None

    @pytest.mark.asyncio
    async def test_malformed_xml_bails_without_clearing_state(self) -> None:
        """ParseError path must not raise and must not crash the poll."""
        dev = _FakeDevice()
        dev._media_title = "previous"
        service = _service_with_action(
            "GetMediaInfo",
            {"CurrentURI": "x", "TrackSource": "x", "CurrentURIMetaData": _DIDL_MALFORMED},
        )
        dev._upnp_device = MagicMock()
        dev._upnp_device.service = MagicMock(return_value=service)
        await dev.async_update_via_upnp()
        # The function returns early; existing _media_title stays put.
        assert dev._media_title == "previous"

    @pytest.mark.asyncio
    async def test_action_exception_is_swallowed(self) -> None:
        dev = _FakeDevice()
        action = MagicMock()
        action.async_call = AsyncMock(side_effect=RuntimeError("upnp down"))
        service = MagicMock()
        service.action = MagicMock(return_value=action)
        dev._upnp_device = MagicMock()
        dev._upnp_device.service = MagicMock(return_value=service)
        await dev.async_update_via_upnp()
        assert dev._media_title is None  # untouched


class TestTracklistViaUpnp:
    @pytest.mark.asyncio
    async def test_no_upnp_device_short_circuits(self) -> None:
        dev = _FakeDevice()
        await dev.async_tracklist_via_upnp("USB")

    @pytest.mark.asyncio
    async def test_non_usb_clears_queue(self) -> None:
        dev = _FakeDevice()
        dev._upnp_device = MagicMock()
        dev._trackq = ["stale"]
        await dev.async_tracklist_via_upnp("TFcard")
        assert dev._trackq == []

    @pytest.mark.asyncio
    async def test_usb_queue_paths_stripped_of_rootdir(self) -> None:
        dev = _FakeDevice()
        service = _service_with_action(
            "BrowseQueue", {"QueueContext": _QUEUE_XML},
        )
        dev._upnp_device = MagicMock()
        dev._upnp_device.service = MagicMock(return_value=service)
        await dev.async_tracklist_via_upnp("USB")
        assert dev._trackq == ["track1.mp3", "track2.mp3"]

    @pytest.mark.asyncio
    async def test_browse_queue_failure_keeps_existing_queue(self) -> None:
        dev = _FakeDevice()
        dev._trackq = ["existing"]
        action = MagicMock()
        action.async_call = AsyncMock(side_effect=RuntimeError("no usb"))
        service = MagicMock()
        service.action = MagicMock(return_value=action)
        dev._upnp_device = MagicMock()
        dev._upnp_device.service = MagicMock(return_value=service)
        await dev.async_tracklist_via_upnp("USB")
        assert dev._trackq == ["existing"]


class TestPresetSnapViaUpnp:
    @pytest.mark.asyncio
    async def test_no_upnp_or_not_spotify_short_circuits(self) -> None:
        dev = _FakeDevice()
        await dev.async_preset_snap_via_upnp("1")
        dev._upnp_device = MagicMock()  # but spotify still False
        await dev.async_preset_snap_via_upnp("1")

    def _spotify_device(self) -> _FakeDevice:
        dev = _FakeDevice()
        dev._playing_spotify = True
        dev._upnp_device = MagicMock()
        dev.hass = MagicMock()
        return dev

    @pytest.mark.asyncio
    async def test_set_spotify_preset_then_get_key_mapping_writes_back(self) -> None:
        dev = self._spotify_device()

        set_preset = MagicMock()
        set_preset.async_call = AsyncMock(return_value={"Result": "1"})
        get_keymap = MagicMock()
        get_keymap.async_call = AsyncMock(
            return_value={
                "QueueContext": (
                    "<root><Key1><Name>old</Name></Key1></root>"
                ),
            }
        )
        set_keymap = MagicMock()
        set_keymap.async_call = AsyncMock(return_value=None)

        service = MagicMock()
        service.action = MagicMock(
            side_effect=lambda name: {
                "SetSpotifyPreset": set_preset,
                "GetKeyMapping": get_keymap,
                "SetKeyMapping": set_keymap,
            }[name]
        )
        dev._upnp_device.service = MagicMock(return_value=service)

        await dev.async_preset_snap_via_upnp("1")

        # SetKeyMapping invoked with the freshly-built preset XML.
        set_keymap.async_call.assert_awaited_once()
        body = set_keymap.async_call.await_args.kwargs["QueueContext"]
        assert "<Source>SPOTIFY</Source>" in body
        assert "<PicUrl>https://brands.home-assistant.io" in body

    @pytest.mark.asyncio
    async def test_set_spotify_preset_action_error_returns(self) -> None:
        dev = self._spotify_device()
        set_preset = MagicMock()
        set_preset.async_call = AsyncMock(side_effect=RuntimeError("boom"))
        service = MagicMock()
        service.action = MagicMock(return_value=set_preset)
        dev._upnp_device.service = MagicMock(return_value=service)
        await dev.async_preset_snap_via_upnp("1")  # no exception, just return

    @pytest.mark.asyncio
    async def test_missing_preset_key_posts_notification(self) -> None:
        dev = self._spotify_device()
        dev.hass.components.persistent_notification.async_create = MagicMock()

        set_preset = MagicMock()
        set_preset.async_call = AsyncMock(return_value={"Result": "1"})
        get_keymap = MagicMock()
        # XML has no Key1 entry -> triggers the missing-preset notification.
        get_keymap.async_call = AsyncMock(
            return_value={"QueueContext": "<root></root>"}
        )

        service = MagicMock()
        service.action = MagicMock(
            side_effect=lambda name: {
                "SetSpotifyPreset": set_preset,
                "GetKeyMapping": get_keymap,
            }[name]
        )
        dev._upnp_device.service = MagicMock(return_value=service)

        await dev.async_preset_snap_via_upnp("1")
        dev.hass.components.persistent_notification.async_create.assert_called_once()
