"""iTunes Search API fallback for per-track artwork.

When the upstream stream (SomaFM via TuneIn, generic Icecast) doesn't
expose per-track cover art - only a channel logo or nothing - we hit
the public iTunes Search endpoint with the resolved artist + title
and replace the placeholder with the 600x600 album cover. No API
key, no rate-limit headers, JSON response.

    https://itunes.apple.com/search?term=<artist>+<title>&entity=song&limit=1

The mixin populates ``self._media_image_url`` and remembers the last
``(artist, title)`` it looked up so subsequent polls inside the same
track skip the network call entirely.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import timedelta
from http import HTTPStatus

import aiohttp
import async_timeout
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

_ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
_ITUNES_THROTTLE = timedelta(seconds=4)
# iTunes serves the bbb cover at multiple resolutions by substituting
# the dimension in the URL ("100x100bb" -> "600x600bb"). 600 is the
# largest tile served reliably for the song-entity endpoint.
_THUMB_RE = re.compile(r"/\d+x\d+(bb)?(?=\.(jpg|jpeg|png)$)", re.IGNORECASE)


def _upscale_artwork(url: str) -> str:
    """Rewrite a 100x100 iTunes thumb URL to a 600x600 cover URL."""
    return _THUMB_RE.sub(r"/600x600\1", url, count=1)


class LinkPlayItunesArtworkMixin:
    """iTunes Search artwork fallback. Inert when artist/title missing."""

    @Throttle(_ITUNES_THROTTLE)
    async def async_get_itunes_artwork(self) -> bool:
        """Replace ``self._media_image_url`` with iTunes art if available.

        Returns True when a cover URL was set, False otherwise.
        """
        artist = self._media_artist
        title = self._media_title
        if not artist or not title:
            return False

        # Skip the network round-trip when we already looked up the
        # same (artist, title). The track-cache survives between polls
        # so an entire song-long stream only hits iTunes once.
        last = getattr(self, "_itunes_last_lookup", None)
        if last == (artist, title):
            return False

        term = urllib.parse.quote_plus(f"{artist} {title}")
        url = f"{_ITUNES_SEARCH_URL}?term={term}&entity=song&limit=1"

        session = async_get_clientsession(self.hass)
        try:
            async with async_timeout.timeout(5):
                response = await session.get(url)
        except (TimeoutError, aiohttp.ClientError) as error:
            _LOGGER.debug(
                "[%s @ %s] iTunes fetch failed: %s",
                self._name, self._host, type(error).__name__,
            )
            return False

        if response.status != HTTPStatus.OK:
            _LOGGER.debug(
                "[%s @ %s] iTunes search -> HTTP %s",
                self._name, self._host, response.status,
            )
            return False

        try:
            data = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError) as error:
            _LOGGER.debug(
                "[%s @ %s] iTunes JSON parse failed: %s",
                self._name, self._host, error,
            )
            return False

        results = data.get("results") or []
        if not results:
            self._itunes_last_lookup = (artist, title)
            return False

        thumb = results[0].get("artworkUrl100") or results[0].get("artworkUrl60")
        if not thumb:
            self._itunes_last_lookup = (artist, title)
            return False

        self._media_image_url = _upscale_artwork(thumb)
        self._itunes_last_lookup = (artist, title)
        _LOGGER.debug(
            "[%s @ %s] iTunes art -> %s",
            self._name, self._host, self._media_image_url,
        )
        return True
