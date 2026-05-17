"""HTTP-side stream resolution for LinkPlayDevice.

Follows redirects on stream URIs and unwraps M3U / PLS playlist
wrappers to the first concrete URL. Side-effects on the entity are
limited to ``self._nometa`` when a playlist body has no playable URL.
"""

from __future__ import annotations

import logging
from http import HTTPStatus

import aiohttp
import async_timeout
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .metadata import parse_m3u_first_url, parse_pls_first_url

_LOGGER = logging.getLogger(__name__)

_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_USER_AGENT = "VLC/3.0.16 LibVLC/3.0.16"


class LinkPlayStreamResolverMixin:
    """Stream / playlist URL resolution helpers."""

    async def async_detect_stream_url_redirection(self, uri: str) -> str:
        """Follow up to 10 redirects and return the final URL.

        Skips redirect detection for the locally-served TTS proxy URI.
        On any HTTP error, returns the last URI successfully observed
        (or the original URI if none).
        """
        if "tts_proxy" in uri:
            return uri

        _LOGGER.debug("For: %s detect URI redirect-from: %s", self._name, uri)
        check_uri = uri
        max_redirects = 10

        try:
            session = async_get_clientsession(self.hass)
            for _ in range(max_redirects):
                resp = await session.head(
                    check_uri,
                    allow_redirects=False,
                    headers={"User-Agent": _USER_AGENT},
                )
                if resp.status in _REDIRECT_STATUSES and "Location" in resp.headers:
                    check_uri = resp.headers["Location"]
                else:
                    break
            else:
                _LOGGER.warning(
                    "For: %s redirect limit (%d) reached at: %s",
                    self._name, max_redirects, check_uri,
                )
        except Exception as error:  # network errors are common; downgrade
            _LOGGER.debug("Redirect detection exception: %s", error)

        _LOGGER.debug("For: %s detect URI redirect - to: %s", self._name, check_uri)
        return check_uri

    async def async_parse_m3u_url(self, playlist: str) -> str:
        """Return the first stream URL from an M3U playlist, or the playlist URL on failure."""
        data = await self._fetch_playlist_body(playlist, kind="M3U")
        if data is None:
            return playlist
        url = parse_m3u_first_url(data)
        if url is not None:
            return url
        _LOGGER.error(
            "For: %s M3U playlist: %s No valid http URL in the playlist",
            self._name, playlist,
        )
        self._nometa = True
        return playlist

    async def async_parse_pls_url(self, playlist: str) -> str:
        """Return the first stream URL from a PLS playlist, or the playlist URL on failure."""
        data = await self._fetch_playlist_body(playlist, kind="PLS")
        if data is None:
            return playlist
        url = parse_pls_first_url(data)
        if url is not None:
            return url
        _LOGGER.error(
            "For: %s PLS playlist: %s No valid File entry in the playlist",
            self._name, playlist,
        )
        self._nometa = True
        return playlist

    async def _fetch_playlist_body(self, playlist: str, kind: str) -> str | None:
        """Fetch a playlist body and return its text. Logs and returns None on error."""
        try:
            session = async_get_clientsession(self.hass)
            async with async_timeout.timeout(10):
                response = await session.get(playlist)
        except (TimeoutError, aiohttp.ClientError):
            _LOGGER.warning(
                "For: %s unable to get the %s playlist: %s",
                self._name, kind, playlist,
            )
            return None

        if response.status != HTTPStatus.OK:
            _LOGGER.error(
                "For: %s (%s) %s playlist GET failed, response code: %s",
                self._name, self._host, kind, response.status,
            )
            return None

        data = await response.text()
        _LOGGER.debug("For: %s %s playlist: %s contents: %s", self._name, kind, playlist, data)
        return data
