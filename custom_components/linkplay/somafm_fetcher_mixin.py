"""SomaFM now-playing fallback.

Linkplay's TuneIn integration on AudioPro (and similar) firmware only
populates the station name in getPlayerStatus / UPnP DIDL - the actual
track artist + title aren't proxied. For SomaFM channels we hit
SomaFM's own JSON endpoint:

    https://somafm.com/songs/<channel>.json
    https://somafm.com/channels.json  (for name -> id resolution)

The channel slug isn't always derivable from the title - e.g.
"Space Station Soma" has the slug ``spacestation``, not
``spacestationsoma``. So we fetch the channel list once and build a
name-to-slug map.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from http import HTTPStatus

import aiohttp
import async_timeout
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

# Throttle the SomaFM now-playing fetch. Set tight enough that
# track changes on the stream show up on the card within one poll
# cycle, loose enough that we don't hit SomaFM 20 times per minute
# while a track is mid-play (they don't aggressively rate-limit, but
# it's still polite).
_SOMAFM_THROTTLE = timedelta(seconds=5)
_SOMAFM_NOW_PLAYING_URL = "https://somafm.com/songs/{channel}.json"
_SOMAFM_CHANNELS_URL = "https://somafm.com/channels.json"
_SOMAFM_PREFIX_RE = re.compile(r"^\s*somafm\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)

# Module-level cache for the channel-name -> {"id", "image"} map.
# Populated on first SomaFM lookup, kept for the lifetime of the HA
# process. Image URLs come from SomaFM's channels.json and stand in
# for media_image_url until the per-track albumart is available.
_channel_map_cache: dict[str, dict[str, str]] | None = None
_channel_map_lock = asyncio.Lock()


def _slug_from_title(station_title: str | None) -> str | None:
    """Strip the 'SomaFM: ' prefix and lowercase. Doesn't normalise spaces."""
    if not station_title:
        return None
    match = _SOMAFM_PREFIX_RE.match(station_title)
    if not match:
        return None
    return match.group(1).strip().lower() or None


def _station_display_name(station_title: str | None) -> str | None:
    """The SomaFM channel name without the 'SomaFM:' prefix, original case.

    Unlike ``_slug_from_title`` this preserves casing (so "DEF CON Radio"
    isn't mangled) and falls back to the whole string when there's no
    prefix. Used to label the track title, e.g. "<track> (Fluid)".
    """
    if not station_title:
        return None
    match = _SOMAFM_PREFIX_RE.match(station_title)
    name = (match.group(1) if match else station_title).strip()
    return name or None


def somafm_channel_slug(station_title: str | None) -> str | None:
    """Best-effort SomaFM channel slug from a station-name string, no fetch.

    Returns the alphanumeric-only form ("groovesalad"). Caller still
    needs the channel map (or has to handle a 404) for stations like
    "Space Station Soma" -> "spacestation".
    """
    title = _slug_from_title(station_title)
    if title is None:
        return None
    slug = re.sub(r"[^a-z0-9]", "", title)
    return slug or None


async def _get_channel_map(
    session: aiohttp.ClientSession,
) -> dict[str, dict[str, str]]:
    """Fetch SomaFM's channels.json once and return a name -> {id, image} map.

    Subsequent calls return the cached map. On fetch failure returns
    an empty dict (cached) so we don't hammer the endpoint on every
    poll. The map is indexed by lower-case channel title.
    """
    global _channel_map_cache
    if _channel_map_cache is not None:
        return _channel_map_cache

    async with _channel_map_lock:
        if _channel_map_cache is not None:
            return _channel_map_cache

        mapping: dict[str, dict[str, str]] = {}
        try:
            async with async_timeout.timeout(5):
                response = await session.get(_SOMAFM_CHANNELS_URL)
            if response.status == HTTPStatus.OK:
                data = await response.json(content_type=None)
                for channel in data.get("channels", []) or []:
                    title = (channel.get("title") or "").strip().lower()
                    channel_id = channel.get("id")
                    if not (title and channel_id):
                        continue
                    mapping[title] = {
                        "id": channel_id,
                        # 'xlimage' is the 600x600 cover; fall through
                        # to the smaller 'largeimage' / 'image' fields
                        # if it's missing.
                        "image": (
                            channel.get("xlimage")
                            or channel.get("largeimage")
                            or channel.get("image")
                            or ""
                        ),
                    }
                _LOGGER.debug("SomaFM channels loaded: %d entries", len(mapping))
            else:
                _LOGGER.debug(
                    "SomaFM channels.json -> HTTP %s; cache empty",
                    response.status,
                )
        except (TimeoutError, aiohttp.ClientError, ValueError) as error:
            _LOGGER.debug("SomaFM channels.json fetch failed: %s", error)

        _channel_map_cache = mapping
        return mapping


class LinkPlaySomaFmFetcherMixin:
    """SomaFM now-playing fetch, throttled to 20 s."""

    @Throttle(_SOMAFM_THROTTLE)
    async def async_update_from_somafm(self) -> bool:
        """If the current title looks like a SomaFM station, fetch real track info.

        Returns True when artist + title were populated, False otherwise.
        """
        # Prefer the sticky cached station name: after the first
        # successful fetch ``_media_title`` is the track title, not the
        # "SomaFM: <station>" prefix, so deriving from it would freeze
        # the entity on the first track of every session.
        title = _slug_from_title(
            getattr(self, "_somafm_cached_station", None)
        ) or _slug_from_title(self._media_title)
        if title is None:
            return False

        session = async_get_clientsession(self.hass)

        # Resolve via the official channel list first; fall back to the
        # alphanum-only slug for stations missing from the map.
        channel_map = await _get_channel_map(session)
        channel = channel_map.get(title)
        slug = (channel or {}).get("id") or re.sub(r"[^a-z0-9]", "", title)
        if not slug:
            return False

        # Station-level artwork is the final fallback. We defer
        # assigning it until after the per-track + iTunes lookups so
        # we don't clobber a track-accurate cover that was set on a
        # previous poll (the iTunes throttle returns None on the
        # second call, so overwriting up-front would lose the art
        # for the rest of the song).
        channel_image = (channel or {}).get("image")

        url = _SOMAFM_NOW_PLAYING_URL.format(channel=slug)
        try:
            async with async_timeout.timeout(5):
                response = await session.get(url)
        except (TimeoutError, aiohttp.ClientError) as error:
            _LOGGER.debug(
                "[%s @ %s] SomaFM fetch failed: %s",
                self._name, self._host, type(error).__name__,
            )
            return False

        if response.status != HTTPStatus.OK:
            _LOGGER.debug(
                "[%s @ %s] SomaFM %s -> HTTP %s",
                self._name, self._host, url, response.status,
            )
            return False

        try:
            data = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError) as error:
            _LOGGER.debug(
                "[%s @ %s] SomaFM JSON parse failed: %s",
                self._name, self._host, error,
            )
            return False

        songs = data.get("songs") or []
        if not songs:
            return False
        current = songs[0]
        title = current.get("title")
        artist = current.get("artist")
        album = current.get("album") or None
        albumart = current.get("albumart") or None
        if not (title and artist):
            return False

        # Append the SomaFM station name after the artist so the card
        # shows which channel is playing, e.g. "efesoul (Fluid)". Rebuilt
        # from the raw artist on every fetch, so the suffix never
        # accumulates across polls.
        station = _station_display_name(
            getattr(self, "_somafm_cached_station", None)
        )
        display_artist = f"{artist} ({station})" if station else artist

        prev = (self._media_title, self._media_artist)
        track_changed = (title, display_artist) != prev
        self._media_title = title
        self._media_artist = display_artist
        if album:
            self._media_album = album

        # On every fresh track inside the same station, drop the prior
        # cover before resolving a new one - otherwise either the
        # previous track's iTunes art or the station logo lingers when
        # the new resolution chain returns nothing.
        if track_changed:
            self._media_image_url = None

        # Artwork priority:
        #   1. iTunes Search by (artist, title) - the real album cover
        #      for the song actually playing.
        #   2. SomaFM per-track ``albumart`` field - some channels
        #      populate it, most don't.
        #   3. SomaFM channel image - station-level fallback so the
        #      card never goes blank.
        # iTunes is throttled to 4 s and caches per (artist, title);
        # after the first successful lookup subsequent calls inside
        # the same track return False/None. We only fall through to
        # the next source when ``_media_image_url`` is still empty,
        # so a sticky iTunes URL from a previous poll isn't clobbered
        # by the station logo on the next poll inside the same track.
        itunes_ok = False
        itunes = getattr(self, "async_get_itunes_artwork", None)
        if itunes is not None:
            try:
                itunes_ok = bool(await itunes())
            except Exception as error:
                _LOGGER.debug(
                    "[%s @ %s] iTunes art lookup raised: %s",
                    self._name, self._host, error,
                )
        if not itunes_ok and not self._media_image_url and albumart:
            self._media_image_url = albumart
        if not self._media_image_url and channel_image:
            self._media_image_url = channel_image
        if (title, display_artist) != prev:
            _LOGGER.debug(
                "[%s @ %s] SomaFM %s -> %r / %r (art=%s)",
                self._name, self._host, slug, display_artist, title,
                "track" if albumart else "channel" if channel_image else "none",
            )
            # HA reads the entity state at the end of async_update, but
            # pushing it now means the card reflects the new track
            # without waiting for the surrounding update to finish.
            if getattr(self, "hass", None) is not None:
                try:
                    self.async_write_ha_state()
                except Exception:
                    pass
        return True
