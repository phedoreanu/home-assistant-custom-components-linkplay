"""Optional Last.fm cover-art lookup for LinkPlayDevice.

Activates only when the entity has a ``_lastfm_api_key`` configured.
The throttle decorator is applied here so the entity-level method
mixed in inherits the rate limit transparently.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from http import HTTPStatus

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

_LASTFM_API_BASE = "http://ws.audioscrobbler.com/2.0/?method="

# Match the original LFM_THROTTLE used inline. Local to the mixin so
# the entity module no longer needs the constant.
_LFM_THROTTLE = timedelta(seconds=4)

# The CDN URL substring last.fm returns for the placeholder "sheriff
# star" cover that signals a rate-limit or unknown album.
_RATELIMIT_MARKER = "2a96cbd8b46e442fc41c2b86b821562f"


class LinkPlayLastFmMixin:
    """Last.fm helper methods. Inert when no API key is configured."""

    async def call_update_lastfm(self, cmd: str, params: str):
        """Hit the Last.fm 2.0 API with the supplied query, return parsed JSON or False."""
        url = (
            f"{_LASTFM_API_BASE}{cmd}&{params}"
            f"&api_key={self._lastfm_api_key}&format=json"
        )
        try:
            session = async_get_clientsession(self.hass)
            response = await session.get(url)
            if response.status != HTTPStatus.OK:
                _LOGGER.error(
                    "Last.fm GET failed, response code: %s", response.status,
                )
                return False
            return await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as error:
            _LOGGER.error(
                "Failed communicating with Last.fm '%s': %s",
                self._name, type(error),
            )
            return False

    @Throttle(_LFM_THROTTLE)
    async def async_get_lastfm_coverart(self) -> None:
        """Populate ``self._media_image_url`` from Last.fm cover art."""
        if self._media_title is None or self._media_artist is None:
            self._media_image_url = None
            return

        lfm_data = await self.call_update_lastfm(
            "track.getInfo",
            f"artist={self._media_artist}&track={self._media_title}",
        )

        coverart_url: str | None
        try:
            coverart_url = lfm_data["track"]["album"]["image"][3]["#text"]
        except (TypeError, ValueError, KeyError):
            coverart_url = None

        if not coverart_url:
            self._media_image_url = None
            return

        if _RATELIMIT_MARKER in coverart_url:
            _LOGGER.debug("Last.fm rate-limited; ignoring placeholder cover")
            self._media_image_url = None
            return

        self._media_image_url = coverart_url
