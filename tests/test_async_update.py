"""Regression tests for the poll cycle (async_update).

Most of async_update is wrapped around the live device-status response,
so these tests target the discrete branches that can be exercised
without spinning up a full status-response fixture:

- multiroom master status polling (extracted method)
- slave-mode and master-ref recovery (already in test_multiroom_state)
- unjoin-wait window
- protocol auto-detect failure path
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.linkplay.media_player import LinkPlayDevice


def _make_device(name: str) -> LinkPlayDevice:
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
            icecast_metadata="Off",
            multiroom_wifidirect=False,
            led_off=False,
            volume_step=5,
            lastfm_api_key=None,
            uuid="",
            state="idle",
        )
    dev.entity_id = f"media_player.{name}"
    dev.hass = hass
    dev.async_write_ha_state = MagicMock()
    return dev


def _share_entities(*devices: LinkPlayDevice) -> None:
    """Make all devices visible to each other via hass.data[DOMAIN].entities."""
    entities = list(devices)
    for d in entities:
        d.hass.data["linkplay"].entities = entities


class TestPollMultiroomMasterStatus:
    """Cover the extracted _async_poll_multiroom_master_status method."""

    @pytest.mark.asyncio
    async def test_slave_short_circuits_without_http(self) -> None:
        slave = _make_device("slave")
        slave._slave_mode = True
        slave.call_linkplay_httpapi = AsyncMock(
            side_effect=AssertionError("slaves must not query getSlaveList")
        )

        result = await slave._async_poll_multiroom_master_status()

        assert result is True

    @pytest.mark.asyncio
    async def test_api_failure_clears_master_state(self) -> None:
        master = _make_device("master")
        master._is_master = True
        master._slave_list = [{"name": "x"}]
        master._multiroom_group = ["media_player.master", "media_player.slave"]
        master.call_linkplay_httpapi = AsyncMock(return_value=None)

        await master._async_poll_multiroom_master_status()

        assert master._is_master is False
        assert master._slave_list is None
        assert master._multiroom_group == []

    @pytest.mark.asyncio
    async def test_zero_slaves_resets_group_and_drops_master_flag(self) -> None:
        master = _make_device("master")
        master._is_master = True
        master._multiroom_group = ["media_player.master"]
        master.call_linkplay_httpapi = AsyncMock(return_value={"slaves": 0, "slave_list": []})

        await master._async_poll_multiroom_master_status()

        assert master._is_master is False
        assert master._multiroom_group == []
        assert master._slave_list == []

    @pytest.mark.asyncio
    async def test_master_populates_group_and_pushes_to_slaves(self) -> None:
        master = _make_device("master")
        slave_kitchen = _make_device("kitchen")
        slave_office = _make_device("office")
        _share_entities(master, slave_kitchen, slave_office)

        # The integration matches slaves by their HA-side _name (the friendly
        # name HA was given), which is what the device firmware also reports
        # in the multiroom protocol.
        slave_kitchen._name = "kitchen"
        slave_office._name = "office"

        master.call_linkplay_httpapi = AsyncMock(
            return_value={
                "slaves": 2,
                "slave_list": [
                    {"name": "kitchen", "volume": 30, "ip": "10.0.0.2"},
                    {"name": "office", "volume": 50, "ip": "10.0.0.3"},
                ],
            }
        )

        await master._async_poll_multiroom_master_status()

        assert master._is_master is True
        assert master._multiroom_group == [
            "media_player.master",
            "media_player.kitchen",
            "media_player.office",
        ]
        assert slave_kitchen._slave_mode is True
        assert slave_office._slave_mode is True
        assert slave_kitchen._master is master
        assert slave_kitchen._multiroom_group == master._multiroom_group
        assert slave_office._multiroom_group == master._multiroom_group

    @pytest.mark.asyncio
    async def test_unmatched_slave_name_is_silently_skipped(self) -> None:
        """When the device reports a slave name that no HA entity matches,
        the master's group should only contain itself."""
        master = _make_device("master")
        stranger = _make_device("stranger")
        _share_entities(master, stranger)
        stranger._name = "actually_different_name"

        master.call_linkplay_httpapi = AsyncMock(
            return_value={
                "slaves": 1,
                "slave_list": [{"name": "kitchen", "volume": 30, "ip": "10.0.0.2"}],
            }
        )

        await master._async_poll_multiroom_master_status()

        assert master._multiroom_group == ["media_player.master"]
        assert stranger._slave_mode is False


class TestUnjoinWaitWindow:
    """async_update returns early while _multiroom_unjoinat is within the
    wait window — the device firmware needs time after Ungroup before its
    status response is reliable again.
    """

    @pytest.mark.asyncio
    async def test_within_wait_window_returns_idle_state(self) -> None:
        from homeassistant.util.dt import utcnow

        dev = _make_device("device")
        dev._multiroom_unjoinat = utcnow()  # just now
        dev._multiroom_wifidirect = False  # router mode -> 3s wait window
        dev.call_linkplay_httpapi = AsyncMock(
            side_effect=AssertionError("update should short-circuit in wait window")
        )

        result = await dev.async_update()

        assert result is True
        assert dev._source is None
        assert dev._media_title is None
        assert dev._media_artist is None
        assert dev._state == "idle"

    @pytest.mark.asyncio
    async def test_outside_wait_window_restores_previous_source(self) -> None:
        from homeassistant.util.dt import utcnow

        dev = _make_device("device")
        dev._multiroom_unjoinat = utcnow() - timedelta(minutes=5)  # long ago
        dev._multiroom_wifidirect = False
        dev._multiroom_prevsrc = "Line-in"
        dev.async_select_source = AsyncMock()

        result = await dev.async_update()

        assert result is True
        assert dev._multiroom_unjoinat is None
        assert dev._multiroom_prevsrc is None
        dev.async_select_source.assert_awaited_once_with("Line-in")


class TestProtocolAutoDetectFailure:
    """If _protocol is None and both https and http probes fail, async_update
    must return False without raising."""

    @pytest.mark.asyncio
    async def test_both_protocols_fail(self) -> None:
        dev = _make_device("device")
        dev._protocol = None
        dev.call_linkplay_httpapi = AsyncMock(return_value=None)

        result = await dev.async_update()

        assert result is False
        assert dev._protocol is None

    @pytest.mark.asyncio
    async def test_https_succeeds(self) -> None:
        dev = _make_device("device")
        dev._protocol = None

        async def fake_call(cmd, jsn, protocol=None):
            if protocol == "https":
                return {"ok": True}
            return None

        dev.call_linkplay_httpapi = AsyncMock(side_effect=fake_call)
        # Short-circuit the rest of async_update by leaving _player_statdata
        # at its sentinel; the function will fall through quickly.
        dev.async_get_status = AsyncMock()
        dev._player_statdata = None

        await dev.async_update()

        assert dev._protocol == "https"
