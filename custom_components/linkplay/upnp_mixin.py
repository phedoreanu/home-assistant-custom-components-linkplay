"""UPnP-driven metadata + queue interactions for LinkPlayDevice.

Calls the three async_upnp_client services the firmware exposes:

* ``AVTransport:1`` for the currently-playing track metadata
  (Spotify-friendly path).
* ``PlayQueue:1`` for the USB / local-disk track list.
* ``PlayQueue:1`` for persisting a Spotify preset slot.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET

import validators

_LOGGER = logging.getLogger(__name__)

_ROOTDIR_USB = "/media/sda1/"

_AV_TRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
_PLAY_QUEUE = "urn:schemas-wiimu-com:service:PlayQueue:1"

_DIDL_ITEM_NS = "{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}item/"
_DC_NS = "{http://purl.org/dc/elements/1.1/}"
_UPNP_NS = "{urn:schemas-upnp-org:metadata-1-0/upnp/}"


def _didl_text(xml_tree: ET.Element, suffix: str) -> str | None:
    node = xml_tree.find(_DIDL_ITEM_NS + suffix)
    return node.text if node is not None else None


class LinkPlayUPnPMixin:
    """UPnP metadata fetch + queue + Spotify-preset helpers."""

    async def async_update_via_upnp(self) -> None:
        """Refresh media metadata from the AVTransport service."""
        if self._upnp_device is None:
            return

        self._service = self._upnp_device.service(_AV_TRANSPORT)

        media_metadata = None
        try:
            media_info = await self._service.action("GetMediaInfo").async_call(InstanceID=0)
            self._trackc = media_info.get("CurrentURI")
            self._media_uri_final = media_info.get("TrackSource")
            media_metadata = media_info.get("CurrentURIMetaData")
        except Exception:
            _LOGGER.warning("GetMediaInfo/CurrentURIMetaData UPNP error: %s", self.entity_id)

        if media_metadata is None:
            return

        try:
            xml_tree = ET.fromstring(media_metadata)
        except ET.ParseError as error:
            # LinkPlay DIDL-Lite payloads occasionally contain
            # unescaped ampersands or non-Latin chars that the stdlib
            # XML parser rejects. Bail rather than killing the whole
            # poll cycle so the caller can fall through to other
            # metadata sources. Only log the first occurrence of each
            # unique error per entity to avoid filling the log.
            error_key = (self.entity_id, str(error))
            if error_key != getattr(self, "_last_didl_parse_error", None):
                _LOGGER.debug(
                    "Invalid DIDL-Lite XML from %s: %s",
                    self.entity_id, error,
                )
                self._last_didl_parse_error = error_key
            return

        self._media_title = None
        self._media_album = None
        self._media_artist = None
        self._media_image_url = None

        # Most media exposes title/artist/album via DIDL-Lite + UPnP namespaces.
        self._media_title = _didl_text(xml_tree, f"{_DC_NS}title")
        self._media_artist = _didl_text(xml_tree, f"{_UPNP_NS}artist")
        self._media_album = _didl_text(xml_tree, f"{_UPNP_NS}album")
        image_url = _didl_text(xml_tree, f"{_UPNP_NS}albumArtURI")

        if image_url and validators.url(image_url):
            self._media_image_url = image_url
        else:
            self._media_image_url = None

    async def async_tracklist_via_upnp(self, media: str) -> None:
        """Populate ``self._trackq`` with URLs from the local-storage queue."""
        if self._upnp_device is None:
            return

        if media != "USB":
            _LOGGER.debug(
                "Tracklist retrieval %s for %s is not supported; only USB is wired up.",
                media, self.entity_id,
            )
            self._trackq = []
            return

        queuename = "USBDiskQueue"
        rootdir = _ROOTDIR_USB

        self._service = self._upnp_device.service(_PLAY_QUEUE)

        media_metadata = None
        try:
            media_info = await self._service.action("BrowseQueue").async_call(QueueName=queuename)
            media_metadata = media_info.get("QueueContext")
        except Exception:
            _LOGGER.debug("PlayQueue/QueueContext UPNP error, media not present?: %s", self.entity_id)

        if media_metadata is None:
            return

        xml_tree = ET.fromstring(media_metadata)

        trackq: list[str] = []
        for playlist in xml_tree:
            for tracks in playlist:
                for track in tracks:
                    if track.tag == "URL" and track.text and rootdir in track.text:
                        trackq.append(track.text.replace(rootdir, ""))

        if trackq:
            self._trackq = trackq

    async def async_preset_snap_via_upnp(self, presetnum: str) -> None:
        """Save the current Spotify playlist into the device preset slot ``presetnum``."""
        if self._upnp_device is None or not self._playing_spotify:
            return

        self._service = self._upnp_device.service(_PLAY_QUEUE)

        result = None
        try:
            media_info = await self._service.action("SetSpotifyPreset").async_call(
                KeyIndex=int(presetnum)
            )
            _LOGGER.debug(
                "PlayQueue/SetSpotifyPreset for: %s, UPNP media_info:%s",
                self.entity_id, media_info,
            )
            result = str(media_info.get("Result"))
        except Exception:
            _LOGGER.debug(
                "SetSpotifyPreset UPNP error for: %s, presetnum: %s",
                self.entity_id, presetnum,
            )
            return

        try:
            preset_map_raw = (
                await self._service.action("GetKeyMapping").async_call()
            ).get("QueueContext")
        except Exception:
            _LOGGER.debug("GetKeyMapping UPNP error: %s", self.entity_id)
            return

        xml_tree = ET.fromstring(preset_map_raw)

        if xml_tree.find(f"Key{presetnum}") is None:
            _LOGGER.error(
                "Preset Map error: %s num: %s. Please create a Spotify preset "
                "first with the mobile app for this player. Tree: %s",
                self.entity_id, presetnum, preset_map_raw,
            )
            self.hass.components.persistent_notification.async_create(
                "<b>Preset Map error:</b><br><br><br>This player can't store "
                "presets yet!<br>Please create a preset first manually with "
                "the mobile app for this player and then try again.",
                title=self.entity_id,
            )
            return

        tme = time.strftime("%Y-%m-%d %H:%M:%S")
        snap_name = f"Snapshot set by Home Assistant ({result})_#~{tme}"
        snap_source = "SPOTIFY"
        snap_pic = "https://brands.home-assistant.io/_/media_player/icon.png"

        _ensure_child_text(xml_tree, presetnum, "Name", snap_name)
        _ensure_child_text(xml_tree, presetnum, "Source", snap_source)
        _ensure_child_text(xml_tree, presetnum, "PicUrl", snap_pic)

        preset_map = ET.tostring(xml_tree, encoding="unicode")

        try:
            await self._service.action("SetKeyMapping").async_call(QueueContext=preset_map)
        except Exception:
            _LOGGER.debug("SetKeyMapping UPNP error: %s, %s", self.entity_id, preset_map)


def _ensure_child_text(xml_tree: ET.Element, presetnum: str, tag: str, value: str) -> None:
    """Set ``Key<presetnum>/<tag>`` to ``value``, creating it if necessary."""
    parent = xml_tree.find(f"Key{presetnum}")
    if parent is None:
        return
    node = parent.find(tag)
    if node is None:
        node = ET.SubElement(parent, tag)
    node.text = value
