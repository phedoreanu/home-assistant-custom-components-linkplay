"""Integration tests for the multiroom join / unjoin paths.

Uses real LinkPlayDevice instances (no I/O — call_linkplay_httpapi is
mocked, and async_write_ha_state is replaced with a noop because the
entity is not attached to a running HA instance).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.linkplay.media_player import LinkPlayDevice


def _make_device(name: str, host: str = "1.2.3.4") -> LinkPlayDevice:
    hass = MagicMock()
    hass.data = {"linkplay": MagicMock(entities=[])}

    with patch("custom_components.linkplay.media_player.AiohttpRequester"), patch(
        "custom_components.linkplay.media_player.UpnpFactory"
    ):
        dev = LinkPlayDevice(
            name=name,
            host=host,
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


def _make_group(master_name: str, slave_names: list[str]):
    """Create a master + N slaves sharing a single hass entities list."""
    master = _make_device(master_name)
    slaves = [_make_device(name) for name in slave_names]
    entities = [master, *slaves]
    for entity in entities:
        entity.hass.data["linkplay"].entities = entities
    return master, slaves


class TestAsyncJoin:
    @pytest.mark.asyncio
    async def test_join_adds_slaves_and_marks_master(self) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        master.call_linkplay_httpapi = AsyncMock(return_value="OK")
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")

        await master.async_join([slave])

        assert master._is_master is True
        assert master.entity_id in master._multiroom_group
        assert slave.entity_id in master._multiroom_group
        assert slave._slave_mode is True
        assert slave._master is master
        assert slave._multiroom_group == master._multiroom_group

    @pytest.mark.asyncio
    async def test_join_pushes_state_for_master_and_slaves(self) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        master.call_linkplay_httpapi = AsyncMock(return_value="OK")
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")

        await master.async_join([slave])

        master.async_write_ha_state.assert_called()
        slave.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_join_skips_slave_when_httpapi_fails(self) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        master.call_linkplay_httpapi = AsyncMock(return_value="OK")
        slave.call_linkplay_httpapi = AsyncMock(return_value="NOK")

        await master.async_join([slave])

        assert slave.entity_id not in master._multiroom_group
        assert slave._slave_mode is False

    @pytest.mark.asyncio
    async def test_join_unavailable_master_is_noop(self) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        master._state = "unavailable"
        master.call_linkplay_httpapi = AsyncMock(return_value="OK")
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")

        await master.async_join([slave])

        assert master._multiroom_group == []
        slave.call_linkplay_httpapi.assert_not_called()


class TestAsyncUnjoinAll:
    @pytest.mark.asyncio
    async def test_unjoin_all_clears_group_and_pushes_state(self) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        master._is_master = True
        master._multiroom_group = [master.entity_id, slave.entity_id]
        slave._slave_mode = True
        slave._master = master
        slave._multiroom_group = [master.entity_id, slave.entity_id]

        master.call_linkplay_httpapi = AsyncMock(return_value="OK")

        await master.async_unjoin_all()

        assert master._multiroom_group == []
        assert master._is_master is False
        assert slave._slave_mode is False
        assert slave._master is None
        assert slave._multiroom_group == []
        master.async_write_ha_state.assert_called()
        slave.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_unjoin_all_skips_when_unavailable(self) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        master._state = "unavailable"
        master._multiroom_group = [master.entity_id, slave.entity_id]
        master.call_linkplay_httpapi = AsyncMock(return_value="OK")

        await master.async_unjoin_all()

        master.call_linkplay_httpapi.assert_not_called()
        assert master._multiroom_group == [master.entity_id, slave.entity_id]

    @pytest.mark.asyncio
    async def test_unjoin_all_leaves_state_when_httpapi_fails(self) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        master._is_master = True
        master._multiroom_group = [master.entity_id, slave.entity_id]
        slave._slave_mode = True
        master.call_linkplay_httpapi = AsyncMock(return_value="NOK")

        await master.async_unjoin_all()

        assert master._is_master is True
        assert master._multiroom_group == [master.entity_id, slave.entity_id]
        assert slave._slave_mode is True


class TestAsyncUnjoinMe:
    @pytest.mark.asyncio
    async def test_unjoin_me_drops_self_and_notifies_master(self) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        master._is_master = True
        master._multiroom_group = [master.entity_id, slave.entity_id]
        slave._slave_mode = True
        slave._master = master
        slave._multiroom_group = [master.entity_id, slave.entity_id]

        master.call_linkplay_httpapi = AsyncMock(return_value="OK")
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")

        await slave.async_unjoin_me()

        assert slave._slave_mode is False
        assert slave._master is None
        assert slave._multiroom_group == []
        assert slave.entity_id not in master._multiroom_group
        slave.async_write_ha_state.assert_called()


class TestAsyncRemoveFromGroup:
    @pytest.mark.asyncio
    async def test_remove_drops_member_and_resets_when_group_collapses(
        self,
    ) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        master._is_master = True
        master._multiroom_group = [master.entity_id, slave.entity_id]

        await master.async_remove_from_group(slave)

        # When the group collapses to <=1 member, master should reset.
        assert master._multiroom_group == []
        assert master._is_master is False
        master.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_remove_keeps_remaining_slaves_grouped(self) -> None:
        master, (slave1, slave2) = _make_group("master", ["slave1", "slave2"])
        master._is_master = True
        master._multiroom_group = [
            master.entity_id,
            slave1.entity_id,
            slave2.entity_id,
        ]
        slave2._slave_mode = True
        slave2._multiroom_group = list(master._multiroom_group)

        await master.async_remove_from_group(slave1)

        assert master._multiroom_group == [master.entity_id, slave2.entity_id]
        assert slave2._multiroom_group == [master.entity_id, slave2.entity_id]
        slave2.async_write_ha_state.assert_called()
