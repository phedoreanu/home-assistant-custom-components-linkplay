"""Tests for async_setup_platform (YAML) and async_setup_entry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.linkplay.media_player import (
    async_setup_entry,
    async_setup_platform,
)


def _payload(uuid: str = "AABBCCDDEEFF", name: str = "Office"):
    return {
        "uuid": uuid,
        "DeviceName": name,
        "firmware": "4.6.328",
        "hardware": "A31",
    }


@pytest.fixture
def _mock_response_ok():
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value=_payload())
    return response


def _patched_session(response):
    """Return a context-manager patcher that makes async_get_clientsession()
    yield a session whose .get() returns `response`."""
    session = MagicMock()
    session.get = AsyncMock(return_value=response)
    return patch(
        "custom_components.linkplay.media_player.async_get_clientsession",
        return_value=session,
    )


class TestAsyncSetupPlatform:
    @pytest.mark.asyncio
    async def test_happy_path_http(self, _mock_response_ok) -> None:
        hass = MagicMock()
        hass.data = {}
        add_entities = MagicMock()
        config = {
            "name": None,
            "host": "1.2.3.4",
            "protocol": "http",
            "sources": None,
            "common_sources": None,
            "icecast_metadata": "StationName",
            "multiroom_wifidirect": False,
            "led_off": False,
            "volume_step": 5,
            "lastfm_api_key": None,
            "uuid": None,
        }
        patcher = _patched_session(_mock_response_ok)
        with patcher, patch(
            "custom_components.linkplay.media_player.AiohttpRequester"
        ), patch("custom_components.linkplay.media_player.UpnpFactory"):
            await async_setup_platform(hass, config, add_entities)

        add_entities.assert_called_once()
        entity = add_entities.call_args.args[0][0]
        assert entity._uuid == "AABBCCDDEEFF"
        # name was None in config -> populated from response
        assert entity._name == "Office"

    @pytest.mark.asyncio
    async def test_protocol_default_falls_back_to_https(self) -> None:
        """When protocol is unset, http fails, then https is tried."""
        hass = MagicMock()
        hass.data = {}
        add_entities = MagicMock()
        config = {
            "host": "1.2.3.4",
            "protocol": None,
            "name": None,
            "sources": None,
            "common_sources": None,
            "icecast_metadata": None,
            "multiroom_wifidirect": False,
            "led_off": False,
            "volume_step": 5,
            "lastfm_api_key": None,
            "uuid": None,
        }
        ok_resp = MagicMock()
        ok_resp.status = 200
        ok_resp.json = AsyncMock(return_value=_payload(name="Kitchen"))
        session = MagicMock()
        # first call raises, second returns ok_resp
        session.get = AsyncMock(
            side_effect=[aiohttp.ClientError("boom"), ok_resp]
        )
        with patch(
            "custom_components.linkplay.media_player.async_get_clientsession",
            return_value=session,
        ), patch(
            "custom_components.linkplay.media_player.AiohttpRequester"
        ), patch("custom_components.linkplay.media_player.UpnpFactory"):
            await async_setup_platform(hass, config, add_entities)

        add_entities.assert_called_once()
        entity = add_entities.call_args.args[0][0]
        assert entity._protocol == "https"
        assert entity._name == "Kitchen"

    @pytest.mark.asyncio
    async def test_both_protocols_fail_marks_unavailable(self) -> None:
        hass = MagicMock()
        hass.data = {}
        add_entities = MagicMock()
        config = {
            "host": "1.2.3.4",
            "protocol": None,
            "name": "FallbackName",
            "sources": None,
            "common_sources": None,
            "icecast_metadata": None,
            "multiroom_wifidirect": False,
            "led_off": False,
            "volume_step": 5,
            "lastfm_api_key": None,
            "uuid": None,
        }
        session = MagicMock()
        session.get = AsyncMock(side_effect=aiohttp.ClientError("nope"))
        with patch(
            "custom_components.linkplay.media_player.async_get_clientsession",
            return_value=session,
        ), patch(
            "custom_components.linkplay.media_player.AiohttpRequester"
        ), patch("custom_components.linkplay.media_player.UpnpFactory"):
            await async_setup_platform(hass, config, add_entities)

        entity = add_entities.call_args.args[0][0]
        from homeassistant.const import STATE_UNAVAILABLE
        assert entity._state == STATE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_explicit_protocol_failure_marks_unavailable(self) -> None:
        """With protocol explicitly set, a failed connect skips the fallback
        and goes straight to UNAVAILABLE."""
        hass = MagicMock()
        hass.data = {}
        add_entities = MagicMock()
        config = {
            "host": "1.2.3.4",
            "protocol": "https",
            "name": "Manual",
            "sources": None,
            "common_sources": None,
            "icecast_metadata": None,
            "multiroom_wifidirect": False,
            "led_off": False,
            "volume_step": 5,
            "lastfm_api_key": None,
            "uuid": None,
        }
        session = MagicMock()
        session.get = AsyncMock(side_effect=TimeoutError())
        with patch(
            "custom_components.linkplay.media_player.async_get_clientsession",
            return_value=session,
        ), patch(
            "custom_components.linkplay.media_player.AiohttpRequester"
        ), patch("custom_components.linkplay.media_player.UpnpFactory"):
            await async_setup_platform(hass, config, add_entities)

        entity = add_entities.call_args.args[0][0]
        from homeassistant.const import STATE_UNAVAILABLE
        assert entity._state == STATE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_non_200_response_marks_unavailable(self) -> None:
        hass = MagicMock()
        hass.data = {}
        add_entities = MagicMock()
        config = {
            "host": "1.2.3.4",
            "protocol": "http",
            "name": "Test",
            "sources": None,
            "common_sources": None,
            "icecast_metadata": None,
            "multiroom_wifidirect": False,
            "led_off": False,
            "volume_step": 5,
            "lastfm_api_key": None,
            "uuid": None,
        }
        bad_resp = MagicMock()
        bad_resp.status = 500
        session = MagicMock()
        session.get = AsyncMock(return_value=bad_resp)
        with patch(
            "custom_components.linkplay.media_player.async_get_clientsession",
            return_value=session,
        ), patch(
            "custom_components.linkplay.media_player.AiohttpRequester"
        ), patch("custom_components.linkplay.media_player.UpnpFactory"):
            await async_setup_platform(hass, config, add_entities)

        entity = add_entities.call_args.args[0][0]
        from homeassistant.const import STATE_UNAVAILABLE
        assert entity._state == STATE_UNAVAILABLE


class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_happy_path(self, _mock_response_ok) -> None:
        hass = MagicMock()
        hass.data = {}
        entry = MagicMock()
        entry.data = {
            "host": "1.2.3.4",
            "name": "Living",
            "protocol": "http",
            "sources": None,
            "common_sources": None,
            "lastfm_api_key": None,
        }
        entry.options = {
            "icecast_metadata": "StationNameSongTitle",
            "multiroom_wifidirect": True,
            "led_off": True,
            "volume_step": 10,
            "crossfade_ms": 500,
        }
        entry.unique_id = "OLD-UUID"
        add_entities = MagicMock()
        patcher = _patched_session(_mock_response_ok)
        with patcher, patch(
            "custom_components.linkplay.media_player.AiohttpRequester"
        ), patch("custom_components.linkplay.media_player.UpnpFactory"):
            await async_setup_entry(hass, entry, add_entities)

        add_entities.assert_called_once()
        entity = add_entities.call_args.args[0][0]
        assert entity._volume_step == 10
        assert entity._multiroom_wifidirect is True
        assert entity._crossfade_ms == 500
        # entry unique_id preserved when set
        assert entity._uuid == "OLD-UUID"
        # response's DeviceName overrides entry name
        assert entity._name == "Office"

    @pytest.mark.asyncio
    async def test_entry_picks_up_response_uuid_when_unique_id_empty(
        self, _mock_response_ok
    ) -> None:
        hass = MagicMock()
        hass.data = {}
        entry = MagicMock()
        entry.data = {
            "host": "1.2.3.4",
            "protocol": "http",
        }
        entry.options = {}
        entry.unique_id = None
        add_entities = MagicMock()
        patcher = _patched_session(_mock_response_ok)
        with patcher, patch(
            "custom_components.linkplay.media_player.AiohttpRequester"
        ), patch("custom_components.linkplay.media_player.UpnpFactory"):
            await async_setup_entry(hass, entry, add_entities)

        entity = add_entities.call_args.args[0][0]
        assert entity._uuid == "AABBCCDDEEFF"

    @pytest.mark.asyncio
    async def test_entry_connection_error_marks_unavailable(self) -> None:
        hass = MagicMock()
        hass.data = {}
        entry = MagicMock()
        entry.data = {"host": "1.2.3.4", "protocol": "http", "name": "X"}
        entry.options = {}
        entry.unique_id = "ID-1"
        add_entities = MagicMock()
        session = MagicMock()
        session.get = AsyncMock(side_effect=aiohttp.ClientError())
        with patch(
            "custom_components.linkplay.media_player.async_get_clientsession",
            return_value=session,
        ), patch(
            "custom_components.linkplay.media_player.AiohttpRequester"
        ), patch("custom_components.linkplay.media_player.UpnpFactory"):
            await async_setup_entry(hass, entry, add_entities)

        entity = add_entities.call_args.args[0][0]
        from homeassistant.const import STATE_UNAVAILABLE
        assert entity._state == STATE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_entry_non_200_marks_unavailable(self) -> None:
        hass = MagicMock()
        hass.data = {}
        entry = MagicMock()
        entry.data = {"host": "1.2.3.4", "protocol": "http", "name": "X"}
        entry.options = {}
        entry.unique_id = "ID-1"
        add_entities = MagicMock()
        bad = MagicMock()
        bad.status = 404
        session = MagicMock()
        session.get = AsyncMock(return_value=bad)
        with patch(
            "custom_components.linkplay.media_player.async_get_clientsession",
            return_value=session,
        ), patch(
            "custom_components.linkplay.media_player.AiohttpRequester"
        ), patch("custom_components.linkplay.media_player.UpnpFactory"):
            await async_setup_entry(hass, entry, add_entities)

        entity = add_entities.call_args.args[0][0]
        from homeassistant.const import STATE_UNAVAILABLE
        assert entity._state == STATE_UNAVAILABLE
