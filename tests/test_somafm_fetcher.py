"""Tests for SomaFM channel-slug detection + now-playing fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.linkplay.somafm_fetcher_mixin import (
    _station_display_name,
    somafm_channel_slug,
)
from tests._helpers import make_device as _make_device


@pytest.fixture(autouse=True)
def _reset_somafm_channel_cache():
    """Default each test to an empty channel map so the per-test session
    mocks only have to handle the songs endpoint. Tests that exercise the
    map-fetch path reset the cache themselves."""
    import custom_components.linkplay.somafm_fetcher_mixin as mod
    mod._channel_map_cache = {}
    yield
    mod._channel_map_cache = None


class TestSlug:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("SomaFM: Groove Salad", "groovesalad"),
            ("somafm: Drone Zone", "dronezone"),
            ("SOMAFM - Lush", "lush"),
            ("SomaFM:u80s", "u80s"),
            ("SomaFM:   Boot Liquor", "bootliquor"),
        ],
    )
    def test_extracts_channel(self, title: str, expected: str) -> None:
        assert somafm_channel_slug(title) == expected

    @pytest.mark.parametrize(
        "title",
        [
            None,
            "",
            "BBC Radio 1",
            "Carbon Based Lifeforms - World Of Sleepers",
            "  ",
        ],
    )
    def test_non_somafm_returns_none(self, title) -> None:
        assert somafm_channel_slug(title) is None


class TestStationDisplayName:
    @pytest.mark.parametrize(
        ("station", "expected"),
        [
            ("SomaFM: Fluid", "Fluid"),
            ("somafm: Drone Zone", "Drone Zone"),
            ("SomaFM - DEF CON Radio", "DEF CON Radio"),  # casing preserved
            ("Groove Salad", "Groove Salad"),  # no prefix -> whole string
            (None, None),
            ("", None),
            ("   ", None),
        ],
    )
    def test_station_display_name(self, station, expected) -> None:
        assert _station_display_name(station) == expected


class TestUpdateFromSomafm:
    @pytest.mark.asyncio
    async def test_no_station_title_returns_false(self) -> None:
        dev = _make_device()
        dev._media_title = "BBC Radio 1"

        ok = await dev.async_update_from_somafm()

        assert ok is False
        assert dev._media_title == "BBC Radio 1"

    @pytest.mark.asyncio
    async def test_somafm_response_populates_track(self) -> None:
        dev = _make_device()
        dev._media_title = "SomaFM: Groove Salad"

        json_payload = {
            "songs": [
                {
                    "title": "Carbon Mind",
                    "artist": "Carbon Based Lifeforms",
                    "album": "World Of Sleepers",
                    "date": "1234567890",
                },
                {"title": "previous track", "artist": "x", "album": "y"},
            ]
        }

        response = MagicMock()
        response.status = 200
        response.json = AsyncMock(return_value=json_payload)
        session = MagicMock()
        session.get = AsyncMock(return_value=response)

        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm()

        assert ok is True
        assert dev._media_title == "Carbon Mind"
        assert dev._media_artist == "Carbon Based Lifeforms"
        assert dev._media_album == "World Of Sleepers"

    @pytest.mark.asyncio
    async def test_artist_gets_station_suffix(self) -> None:
        """With a known station, the artist is suffixed with the SomaFM
        channel name in parens, e.g. 'Carbon Based Lifeforms (Groove
        Salad)'. The title stays the raw track name."""
        dev = _make_device()
        dev._media_title = "SomaFM: Groove Salad"
        dev._somafm_cached_station = "SomaFM: Groove Salad"

        response = MagicMock()
        response.status = 200
        response.json = AsyncMock(return_value={
            "songs": [{
                "title": "Carbon Mind",
                "artist": "Carbon Based Lifeforms",
                "album": "World Of Sleepers",
            }]
        })
        session = MagicMock()
        session.get = AsyncMock(return_value=response)

        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm.__wrapped__(dev)

        assert ok is True
        assert dev._media_title == "Carbon Mind"
        assert dev._media_artist == "Carbon Based Lifeforms (Groove Salad)"

    @pytest.mark.asyncio
    async def test_empty_songs_list_returns_false(self) -> None:
        dev = _make_device()
        dev._media_title = "SomaFM: Drone Zone"

        response = MagicMock()
        response.status = 200
        response.json = AsyncMock(return_value={"songs": []})
        session = MagicMock()
        session.get = AsyncMock(return_value=response)

        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm()

        assert ok is False

    @pytest.mark.asyncio
    async def test_channel_map_resolves_correct_slug_and_image(self) -> None:
        """`channels.json` lookup should turn 'Space Station Soma' into
        'spacestation' (the real slug) instead of the alphanum-only
        fallback 'spacestationsoma', and surface the channel image."""
        import custom_components.linkplay.somafm_fetcher_mixin as mod
        mod._channel_map_cache = None  # reset cache between tests

        dev = _make_device()
        dev._media_title = "SomaFM: Space Station Soma"

        channels_response = MagicMock()
        channels_response.status = 200
        channels_response.json = AsyncMock(return_value={
            "channels": [
                {"id": "spacestation", "title": "Space Station Soma",
                 "xlimage": "https://api.somafm.com/img/spacestation600.jpg"},
                {"id": "groovesalad", "title": "Groove Salad",
                 "xlimage": "https://api.somafm.com/img/groovesalad600.jpg"},
            ]
        })
        songs_response = MagicMock()
        songs_response.status = 200
        songs_response.json = AsyncMock(return_value={
            "songs": [{
                "title": "Ambient Track",
                "artist": "Ambient Artist",
                "album": "Ambient Album",
            }]
        })

        session = MagicMock()
        session.get = AsyncMock(side_effect=[channels_response, songs_response])

        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm()

        assert ok is True
        assert dev._media_artist == "Ambient Artist"
        assert dev._media_title == "Ambient Track"
        # Second .get call should have hit the real spacestation slug.
        called_urls = [call.args[0] for call in session.get.await_args_list]
        assert called_urls[1] == "https://somafm.com/songs/spacestation.json"
        # Channel image surfaced even though songs[0].albumart wasn't set.
        assert dev._media_image_url == "https://api.somafm.com/img/spacestation600.jpg"

    @pytest.mark.asyncio
    async def test_cached_station_drives_refetch_after_first_track(self) -> None:
        """After the first successful fetch, ``_media_title`` is the
        track name (not "SomaFM: <station>"), so the slug must be
        derived from ``_somafm_cached_station`` instead - otherwise the
        entity freezes on the first track of the session."""
        dev = _make_device()
        # State after the first fetch: _media_title is a track, sticky
        # cached station retains the prefixed form.
        dev._media_title = "Carbon Mind"
        dev._media_artist = "Carbon Based Lifeforms"
        dev._somafm_cached_station = "SomaFM: Groove Salad"

        response = MagicMock()
        response.status = 200
        response.json = AsyncMock(return_value={
            "songs": [{
                "title": "New Track",
                "artist": "New Artist",
                "album": "New Album",
            }]
        })
        session = MagicMock()
        session.get = AsyncMock(return_value=response)

        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm.__wrapped__(dev)

        assert ok is True
        assert dev._media_title == "New Track"
        # Artist carries the SomaFM station name in parens.
        assert dev._media_artist == "New Artist (Groove Salad)"
        # The slug came from the cached station, not the track-flavoured
        # _media_title.
        called_url = session.get.await_args.args[0]
        assert called_url == "https://somafm.com/songs/groovesalad.json"

    @pytest.mark.asyncio
    async def test_itunes_called_first_then_used_when_successful(self) -> None:
        """iTunes is the primary artwork source; SomaFM's per-track
        ``albumart`` is the fallback when iTunes returns nothing."""
        dev = _make_device()
        dev._media_title = "SomaFM: Drone Zone"
        dev._somafm_cached_station = "SomaFM: Drone Zone"

        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={
            "songs": [{
                "title": "Spira Mirabilis",
                "artist": "Kodomo",
                "album": "Patterns and Light",
                # SomaFM albumart present, but iTunes wins
                "albumart": "https://api.somafm.com/img/somafm-track.jpg",
            }]
        })
        session = MagicMock()
        session.get = AsyncMock(return_value=resp)

        def _itunes_success():
            dev._media_image_url = "https://is1.mzstatic.com/cover/600x600bb.jpg"
            return True

        dev.async_get_itunes_artwork = AsyncMock(side_effect=_itunes_success)

        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm.__wrapped__(dev)
        assert ok is True
        dev.async_get_itunes_artwork.assert_awaited_once()
        # iTunes art wins over the SomaFM-provided albumart
        assert "mzstatic" in dev._media_image_url

    @pytest.mark.asyncio
    async def test_itunes_lookup_sees_raw_artist_not_station_suffix(self) -> None:
        """Regression: the station "(<channel>)" suffix must NOT leak into
        the iTunes Search. iTunes builds its term from ``_media_artist``,
        so the suffix has to be applied only AFTER artwork resolution -
        otherwise the term is "Kodomo (Drone Zone) <title>" and every
        cover lookup misses, leaving the card on the station logo."""
        dev = _make_device()
        dev._media_title = "SomaFM: Drone Zone"
        dev._somafm_cached_station = "SomaFM: Drone Zone"

        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={
            "songs": [{
                "title": "Spira Mirabilis",
                "artist": "Kodomo",
                "album": "Patterns and Light",
            }]
        })
        session = MagicMock()
        session.get = AsyncMock(return_value=resp)

        seen = {}

        def _capture_artist():
            # Snapshot what iTunes would search on at call time.
            seen["artist"] = dev._media_artist
            seen["title"] = dev._media_title
            return True

        dev.async_get_itunes_artwork = AsyncMock(side_effect=_capture_artist)

        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm.__wrapped__(dev)

        assert ok is True
        # iTunes saw the raw artist, no "(Drone Zone)" suffix.
        assert seen["artist"] == "Kodomo"
        assert seen["title"] == "Spira Mirabilis"
        # But the card still ends up with the station label applied.
        assert dev._media_artist == "Kodomo (Drone Zone)"

    @pytest.mark.asyncio
    async def test_itunes_art_persists_through_throttled_calls(self) -> None:
        """Once iTunes has populated the cover for a track, subsequent
        polls inside the same track must keep it - the SomaFM channel
        logo cannot win just because iTunes' throttle returned False."""
        dev = _make_device()
        # Simulate state at the start of the second poll inside the
        # same track: _media_title/_media_artist already match the
        # SomaFM-resolved track from the previous poll - including the
        # "(<station>)" suffix the previous poll appended to the artist.
        dev._media_title = "Spira Mirabilis"
        dev._media_artist = "Kodomo (Drone Zone)"
        dev._somafm_cached_station = "SomaFM: Drone Zone"
        # Pretend iTunes already populated the cover on the previous poll
        dev._media_image_url = "https://is1.mzstatic.com/cover/600x600bb.jpg"

        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={
            "songs": [{
                "title": "Spira Mirabilis",
                "artist": "Kodomo",
                "album": "Patterns and Light",
            }]
        })
        session = MagicMock()
        session.get = AsyncMock(return_value=resp)

        # iTunes throttle returns False (same track, cached lookup)
        dev.async_get_itunes_artwork = AsyncMock(return_value=False)

        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm.__wrapped__(dev)

        assert ok is True
        # iTunes art still in place, not clobbered by the station logo
        assert "mzstatic" in dev._media_image_url

    @pytest.mark.asyncio
    async def test_track_change_drops_stale_art_before_resolving(self) -> None:
        """When the track changes inside the same station, the previous
        track's image is dropped before the resolution chain runs."""
        dev = _make_device()
        dev._media_title = "Old Track"  # prior poll's title
        dev._media_artist = "Old Artist"
        dev._somafm_cached_station = "SomaFM: Drone Zone"
        dev._media_image_url = "https://is1.mzstatic.com/old/600x600bb.jpg"

        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={
            "songs": [{
                "title": "Spira Mirabilis",  # different track
                "artist": "Kodomo",
                "album": "Patterns and Light",
            }]
        })
        session = MagicMock()
        session.get = AsyncMock(return_value=resp)

        # iTunes lookup for the new track succeeds with fresh URL
        def _itunes_set_new():
            dev._media_image_url = "https://is1.mzstatic.com/new/600x600bb.jpg"
            return True

        dev.async_get_itunes_artwork = AsyncMock(side_effect=_itunes_set_new)

        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm.__wrapped__(dev)
        assert ok is True
        assert "new/600x600bb.jpg" in dev._media_image_url

    @pytest.mark.asyncio
    async def test_somafm_albumart_used_when_itunes_fails(self) -> None:
        """When iTunes returns nothing, SomaFM's per-track ``albumart``
        is the next-best art source before the station logo."""
        dev = _make_device()
        dev._media_title = "SomaFM: Drone Zone"
        dev._somafm_cached_station = "SomaFM: Drone Zone"

        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={
            "songs": [{
                "title": "Spira Mirabilis",
                "artist": "Kodomo",
                "album": "Patterns and Light",
                "albumart": "https://api.somafm.com/img/somafm-track.jpg",
            }]
        })
        session = MagicMock()
        session.get = AsyncMock(return_value=resp)

        # iTunes lookup fails (no match)
        dev.async_get_itunes_artwork = AsyncMock(return_value=False)

        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm.__wrapped__(dev)
        assert ok is True
        assert dev._media_image_url == "https://api.somafm.com/img/somafm-track.jpg"

    @pytest.mark.asyncio
    async def test_http_error_returns_false_silently(self) -> None:
        dev = _make_device()
        dev._media_title = "SomaFM: Lush"

        response = MagicMock()
        response.status = 503
        session = MagicMock()
        session.get = AsyncMock(return_value=response)

        with patch(
            "custom_components.linkplay.somafm_fetcher_mixin.async_get_clientsession",
            return_value=session,
        ):
            ok = await dev.async_update_from_somafm()

        assert ok is False
        assert dev._media_title == "SomaFM: Lush"
        assert dev._media_artist is None
