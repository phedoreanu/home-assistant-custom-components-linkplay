"""Tests for SomaFM channel-slug detection + now-playing fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.linkplay.somafm_fetcher_mixin import somafm_channel_slug


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


def _make_device(name: str = "device"):
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
        assert dev._media_artist == "New Artist"
        # The slug came from the cached station, not the track-flavoured
        # _media_title.
        called_url = session.get.await_args.args[0]
        assert called_url == "https://somafm.com/songs/groovesalad.json"

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
