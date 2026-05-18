"""Tests for the linkplay.* service handlers in __init__.py.

Covers join/unjoin/preset/command/snapshot/restore/play_track dispatch.
``set_group_volume`` already has dedicated coverage in test_services.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from custom_components.linkplay import (
    ATTR_CMD,
    ATTR_MASTER,
    ATTR_NOTIF,
    ATTR_PRESET,
    ATTR_SNAP,
    ATTR_TRACK,
    DOMAIN,
    LinkPlayData,
    SERVICE_CMD,
    SERVICE_JOIN,
    SERVICE_PLAY,
    SERVICE_PRESET,
    SERVICE_REST,
    SERVICE_SNAP,
    SERVICE_UNJOIN,
    async_setup_services,
)


class _MockEntity:
    def __init__(self, entity_id: str, *, master: bool = False) -> None:
        self.entity_id = entity_id
        self.is_master = master
        self.async_join = AsyncMock()
        self.async_unjoin_all = AsyncMock()
        self.async_unjoin_me = AsyncMock()
        self.async_preset_button = AsyncMock()
        self.async_execute_command = AsyncMock()
        self.async_snapshot = AsyncMock()
        self.async_restore = AsyncMock()
        self.async_play_track = AsyncMock()


def _register(hass: HomeAssistant, *entities: _MockEntity) -> None:
    data = LinkPlayData()
    data.entities = list(entities)
    hass.data[DOMAIN] = data


class TestJoinUnjoin:
    @pytest.mark.asyncio
    async def test_join_routes_clients_to_master(self, hass: HomeAssistant) -> None:
        master = _MockEntity("media_player.kitchen", master=True)
        slave_a = _MockEntity("media_player.bath")
        slave_b = _MockEntity("media_player.bedroom")
        _register(hass, master, slave_a, slave_b)
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN, SERVICE_JOIN,
            {
                ATTR_MASTER: "media_player.kitchen",
                ATTR_ENTITY_ID: [
                    "media_player.kitchen", "media_player.bath", "media_player.bedroom",
                ],
            },
            blocking=True,
        )

        master.async_join.assert_awaited_once()
        # Master is filtered out from the client list.
        client_eids = [e.entity_id for e in master.async_join.await_args.args[0]]
        assert "media_player.kitchen" not in client_eids
        assert "media_player.bath" in client_eids

    @pytest.mark.asyncio
    async def test_unjoin_calls_unjoin_all_on_masters(self, hass: HomeAssistant) -> None:
        master = _MockEntity("media_player.kitchen", master=True)
        _register(hass, master)
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN, SERVICE_UNJOIN,
            {ATTR_ENTITY_ID: "media_player.kitchen"},
            blocking=True,
        )
        master.async_unjoin_all.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unjoin_calls_unjoin_me_on_slave(self, hass: HomeAssistant) -> None:
        slave = _MockEntity("media_player.bath")
        _register(hass, slave)
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN, SERVICE_UNJOIN,
            {ATTR_ENTITY_ID: "media_player.bath"},
            blocking=True,
        )
        slave.async_unjoin_me.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_keyword_targets_every_entity(self, hass: HomeAssistant) -> None:
        a = _MockEntity("media_player.a")
        b = _MockEntity("media_player.b")
        _register(hass, a, b)
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN, SERVICE_UNJOIN,
            {ATTR_ENTITY_ID: "all"},
            blocking=True,
        )
        a.async_unjoin_me.assert_awaited_once()
        b.async_unjoin_me.assert_awaited_once()


class TestPresetCmdSnapshotRestorePlay:
    @pytest.mark.asyncio
    async def test_preset_dispatch(self, hass: HomeAssistant) -> None:
        ent = _MockEntity("media_player.a")
        _register(hass, ent)
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN, SERVICE_PRESET,
            {ATTR_ENTITY_ID: "media_player.a", ATTR_PRESET: 2},
            blocking=True,
        )
        ent.async_preset_button.assert_awaited_once_with(2)

    @pytest.mark.asyncio
    async def test_cmd_dispatch_with_notify(self, hass: HomeAssistant) -> None:
        ent = _MockEntity("media_player.a")
        _register(hass, ent)
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN, SERVICE_CMD,
            {
                ATTR_ENTITY_ID: "media_player.a",
                ATTR_CMD: "Rescan",
                ATTR_NOTIF: False,
            },
            blocking=True,
        )
        ent.async_execute_command.assert_awaited_once_with("Rescan", False)

    @pytest.mark.asyncio
    async def test_snapshot_dispatch(self, hass: HomeAssistant) -> None:
        ent = _MockEntity("media_player.a")
        _register(hass, ent)
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN, SERVICE_SNAP,
            {ATTR_ENTITY_ID: "media_player.a", ATTR_SNAP: True},
            blocking=True,
        )
        ent.async_snapshot.assert_awaited_once_with(True)

    @pytest.mark.asyncio
    async def test_restore_dispatch(self, hass: HomeAssistant) -> None:
        ent = _MockEntity("media_player.a")
        _register(hass, ent)
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN, SERVICE_REST,
            {ATTR_ENTITY_ID: "media_player.a"},
            blocking=True,
        )
        ent.async_restore.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_play_track_passes_template(self, hass: HomeAssistant) -> None:
        ent = _MockEntity("media_player.a")
        _register(hass, ent)
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN, SERVICE_PLAY,
            {ATTR_ENTITY_ID: "media_player.a", ATTR_TRACK: "song.mp3"},
            blocking=True,
        )
        ent.async_play_track.assert_awaited_once()
