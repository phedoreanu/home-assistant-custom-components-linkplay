"""Icecast metadata fetch + parse for LinkPlayDevice.

The HTTP side of the icecast pipeline. Pure parsing lives in
:mod:`metadata`; this module owns the network fetch (offloaded to an
executor because urllib is blocking) and the assignment back onto the
entity.
"""

from __future__ import annotations

import logging
import struct
import urllib.request
from datetime import timedelta

from homeassistant.util import Throttle

from .metadata import parse_icy_name, parse_icy_stream_title

_LOGGER = logging.getLogger(__name__)

_API_TIMEOUT = 2
_ICE_THROTTLE = timedelta(seconds=45)
_MAX_METADATA_CHUNKS = 10
_USER_AGENT = "VLC/3.0.16 LibVLC/3.0.16"


def _fetch_icecast_headers_and_chunks(uri: str):
    """Open ``uri`` with Icy-MetaData enabled and return ``(icy_name, icy_metaint, chunks)``.

    Reads up to :data:`_MAX_METADATA_CHUNKS` metadata chunks. Designed to
    run inside ``hass.async_add_executor_job`` because urllib is blocking.
    """
    req = urllib.request.Request(
        uri,
        headers={"Icy-MetaData": "1", "User-Agent": _USER_AGENT},
    )
    resp = urllib.request.urlopen(req, timeout=_API_TIMEOUT)
    try:
        icy_name = resp.headers.get("icy-name")
        icy_metaint = resp.headers.get("icy-metaint")
        chunks: list[bytes] = []
        if icy_metaint is not None:
            metaint = int(icy_metaint)
            for _ in range(_MAX_METADATA_CHUNKS):
                resp.read(metaint)
                length_byte = resp.read(1)
                if not length_byte:
                    break
                metadata_length = struct.unpack("B", length_byte)[0] * 16
                chunks.append(resp.read(metadata_length).rstrip(b"\0"))
    finally:
        resp.close()
    return icy_name, icy_metaint, chunks


class LinkPlayIcecastFetcherMixin:
    """Throttled icecast metadata refresh."""

    @Throttle(_ICE_THROTTLE)
    async def async_update_from_icecast(self) -> bool:
        """Update title / artist / station from the live icecast stream."""
        if self._icecast_meta == "Off":
            return True

        try:
            icy_name, icy_metaint, chunks = await self.hass.async_add_executor_job(
                _fetch_icecast_headers_and_chunks, self._media_uri_final,
            )
        except Exception:
            _LOGGER.debug(
                "For: %s Metadata error: %s", self._name, self._media_uri_final,
            )
            self._media_title = None
            self._media_artist = None
            self._icecast_name = None
            self._media_image_url = None
            return True

        self._icecast_name = parse_icy_name(icy_name)

        if self._icecast_meta == "StationName" or icy_metaint is None:
            self._media_title = self._icecast_name
            self._media_artist = None
            self._media_image_url = None
            return True

        # Title may not be in the first chunk; try several.
        for chunk in chunks:
            artist, title = parse_icy_stream_title(chunk, self._icecast_name)
            if artist is None and title is None:
                # No StreamTitle in this chunk; fall back to station name
                # and keep scanning subsequent chunks.
                self._media_title = self._icecast_name
                self._media_artist = None
                self._media_image_url = None
                continue
            self._media_artist = artist
            self._media_title = title
            return True

        return True
