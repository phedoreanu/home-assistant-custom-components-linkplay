"""Tests for the LinkPlay HTTPAPI / TCP UART client mixin."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.linkplay.api_client_mixin import LinkPlayAPIClientMixin


class _FakeDevice(LinkPlayAPIClientMixin):
    """Bare host for the API client mixin; supplies just the state the
    methods read so we can exercise the transport layer in isolation."""

    def __init__(self, *, protocol: str | None = "http") -> None:
        self.hass = MagicMock()
        self.hass.async_add_executor_job = AsyncMock()
        self.entity_id = "media_player.fake"
        self._name = "fake"
        self._host = "1.2.3.4"
        self._protocol = protocol
        self._first_update = False
        # Fields async_get_status mutates on failure:
        self._state = "playing"
        self._unav_throttle = False
        self._wait_for_mcu = 1
        self._playhead_position = 1
        self._duration = 1
        self._position_updated_at = "x"
        self._media_title = "x"
        self._media_artist = "x"
        self._media_album = "x"
        self._media_image_url = "x"
        self._media_uri = "x"
        self._media_uri_final = "x"
        self._media_source_uri = "x"
        self._playing_mediabrowser = True
        self._playing_stream = True
        self._icecast_name = "x"
        self._source = "x"
        self._upnp_device = "x"
        self._slave_mode = True
        self._is_master = True
        self._player_statdata = {"vol": 50}


def _session_with(get_mock: AsyncMock):
    session = MagicMock()
    session.get = get_mock
    return session


def _patch_session(session):
    return patch(
        "custom_components.linkplay.api_client_mixin.async_get_clientsession",
        return_value=session,
    )


class TestCallLinkplayHttpapi:
    @pytest.mark.asyncio
    async def test_returns_text_on_ok(self) -> None:
        dev = _FakeDevice()
        response = MagicMock(status=HTTPStatus.OK)
        response.text = AsyncMock(return_value="OK")
        with _patch_session(_session_with(AsyncMock(return_value=response))):
            assert await dev.call_linkplay_httpapi("getPlayerStatus", None) == "OK"

    @pytest.mark.asyncio
    async def test_returns_json_when_requested(self) -> None:
        dev = _FakeDevice()
        response = MagicMock(status=HTTPStatus.OK)
        response.json = AsyncMock(return_value={"vol": 42})
        with _patch_session(_session_with(AsyncMock(return_value=response))):
            assert await dev.call_linkplay_httpapi("getPlayerStatus", True) == {"vol": 42}

    @pytest.mark.asyncio
    async def test_missing_protocol_returns_false(self) -> None:
        dev = _FakeDevice(protocol=None)
        # No session call needed - guard fires before transport.
        assert await dev.call_linkplay_httpapi("noop", None) is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self) -> None:
        dev = _FakeDevice()
        with _patch_session(_session_with(AsyncMock(side_effect=TimeoutError()))):
            assert await dev.call_linkplay_httpapi("noop", None) is False

    @pytest.mark.asyncio
    async def test_ssl_error_returns_false(self) -> None:
        dev = _FakeDevice(protocol="https")
        err = aiohttp.ClientSSLError(MagicMock(), OSError("ssl"))
        with _patch_session(_session_with(AsyncMock(side_effect=err))):
            assert await dev.call_linkplay_httpapi("noop", None) is False

    @pytest.mark.asyncio
    async def test_connector_error_returns_false(self) -> None:
        dev = _FakeDevice()
        err = aiohttp.ClientConnectorError(MagicMock(), OSError("nope"))
        with _patch_session(_session_with(AsyncMock(side_effect=err))):
            assert await dev.call_linkplay_httpapi("noop", None) is False

    @pytest.mark.asyncio
    async def test_generic_client_error_returns_false(self) -> None:
        dev = _FakeDevice()
        with _patch_session(_session_with(AsyncMock(side_effect=aiohttp.ClientError()))):
            assert await dev.call_linkplay_httpapi("noop", None) is False

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_false(self) -> None:
        dev = _FakeDevice()
        with _patch_session(_session_with(AsyncMock(side_effect=RuntimeError("boom")))):
            assert await dev.call_linkplay_httpapi("noop", None) is False

    @pytest.mark.asyncio
    async def test_non_200_returns_false(self) -> None:
        dev = _FakeDevice()
        response = MagicMock(status=HTTPStatus.SERVICE_UNAVAILABLE)
        with _patch_session(_session_with(AsyncMock(return_value=response))):
            assert await dev.call_linkplay_httpapi("noop", None) is False

    @pytest.mark.asyncio
    async def test_explicit_protocol_overrides_self(self) -> None:
        dev = _FakeDevice(protocol="http")
        captured: list[str] = []

        async def _get(url, **_kwargs):
            captured.append(url)
            r = MagicMock(status=HTTPStatus.OK)
            r.text = AsyncMock(return_value="ok")
            return r

        with _patch_session(_session_with(AsyncMock(side_effect=_get))):
            await dev.call_linkplay_httpapi("noop", None, protocol="https")

        assert captured[0].startswith("https://")


class TestCallLinkplayTcpuart:
    @pytest.mark.asyncio
    async def test_marker_axx_slice(self) -> None:
        dev = _FakeDevice()
        # Synthetic blob; "AXX" appears, trailing 2 chars trimmed by impl.
        dev.hass.async_add_executor_job = AsyncMock(return_value="garbage AXXpayload\\r\\n")
        result = await dev.call_linkplay_tcpuart("MCU+PAS+RAKOIT:LED:1&")
        assert result == "AXXpayload\\r"

    @pytest.mark.asyncio
    async def test_marker_mcu_fallback(self) -> None:
        dev = _FakeDevice()
        dev.hass.async_add_executor_job = AsyncMock(return_value="zzzMCU+OK\\r\\n")
        result = await dev.call_linkplay_tcpuart("noop")
        assert result == "MCU+OK\\r"

    @pytest.mark.asyncio
    async def test_executor_failure_returns_none(self) -> None:
        dev = _FakeDevice()
        dev.hass.async_add_executor_job = AsyncMock(return_value=None)
        assert await dev.call_linkplay_tcpuart("noop") is None


class TestAsyncGetStatus:
    @pytest.mark.asyncio
    async def test_success_stores_payload(self) -> None:
        dev = _FakeDevice()
        payload = {"vol": "30", "mode": "1"}
        with patch.object(
            type(dev),
            "call_linkplay_httpapi",
            new=AsyncMock(return_value=payload),
        ):
            await dev.async_get_status.__wrapped__(dev)
        assert dev._player_statdata == payload
        assert dev._state == "playing"  # untouched on success

    @pytest.mark.asyncio
    async def test_failure_marks_unavailable_and_clears_state(self) -> None:
        dev = _FakeDevice()
        with patch.object(
            type(dev),
            "call_linkplay_httpapi",
            new=AsyncMock(return_value=False),
        ):
            await dev.async_get_status.__wrapped__(dev)
        assert dev._state == "unavailable"
        assert dev._unav_throttle is True
        assert dev._media_title is None
        assert dev._media_artist is None
        assert dev._upnp_device is None
        assert dev._slave_mode is False
        assert dev._is_master is False
        assert dev._player_statdata is None
