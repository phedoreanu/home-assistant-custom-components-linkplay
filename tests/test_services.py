"""Tests for Linkplay services.

These tests exercise the real entity implementation of
``async_set_group_volume`` (media_player.py) rather than re-implementing
the logic in the test itself. The MockLinkplayDevice supplies the
attributes the method touches, and we bind the real coroutine onto the
master mock with ``__get__``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.const import ATTR_ENTITY_ID

from custom_components.linkplay import (
    DOMAIN,
    SERVICE_SET_GROUP_VOLUME,
    ATTR_VOLUME,
    async_setup_services,
)
from custom_components.linkplay.media_player import LinkPlayDevice


class MockLinkplayDevice:
    """Stand-in for LinkPlayDevice carrying just the state the service
    handler and async_set_group_volume actually touch."""

    def __init__(self, entity_id: str, hass: HomeAssistant) -> None:
        self.entity_id = entity_id
        self.hass = hass
        self._is_master = False
        self._slave_mode = False
        self._multiroom_group: list[str] = []
        self.volume_level: float | None = None
        # Make async_set_volume_level update volume_level too so tests
        # that issue multiple group-volume calls see the delta-shift
        # against the value left behind by the previous call.
        async def _set(level: float) -> None:
            self.volume_level = level
        self.async_set_volume_level = AsyncMock(side_effect=_set)

    @property
    def is_master(self) -> bool:
        return self._is_master


def _bind_real_set_group_volume(master: MockLinkplayDevice) -> None:
    """Bind the real LinkPlayDevice.async_set_group_volume to a mock."""
    master.async_set_group_volume = LinkPlayDevice.async_set_group_volume.__get__(
        master
    )


def _make_group(hass: HomeAssistant, master_eid: str, slave_eids: list[str]):
    """Build a master with N slaves, register them under hass.data[DOMAIN],
    and bind the real group-volume implementation on the master."""
    from custom_components.linkplay import LinkPlayData

    master = MockLinkplayDevice(master_eid, hass)
    master._is_master = True
    master._multiroom_group = [master_eid, *slave_eids]
    _bind_real_set_group_volume(master)

    slaves = []
    for eid in slave_eids:
        slave = MockLinkplayDevice(eid, hass)
        slave._slave_mode = True
        _bind_real_set_group_volume(slave)
        slaves.append(slave)

    data = LinkPlayData()
    data.entities = [master, *slaves]
    hass.data[DOMAIN] = data
    return master, slaves


class TestSetGroupVolumeService:
    """End-to-end coverage of linkplay.set_group_volume.

    Each test routes through hass.services.async_call, the real service
    handler in __init__.py, and the real entity method.
    """

    @pytest.mark.asyncio
    async def test_without_offsets_sets_same_volume_on_all(
        self, hass: HomeAssistant
    ) -> None:
        master, (kitchen, bedroom) = _make_group(
            hass,
            "media_player.living_room",
            ["media_player.kitchen", "media_player.bedroom"],
        )
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.5,
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.5)
        kitchen.async_set_volume_level.assert_called_once_with(0.5)
        bedroom.async_set_volume_level.assert_called_once_with(0.5)

    @pytest.mark.asyncio
    async def test_service_called_on_slave_targets_slave(
        self, hass: HomeAssistant
    ) -> None:
        master, (kitchen,) = _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        # Override slave's group so the real method has something to iterate;
        # the real handler resolves the entity by id and calls its
        # async_set_group_volume.
        kitchen._multiroom_group = [
            "media_player.living_room",
            "media_player.kitchen",
        ]
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.kitchen",
                ATTR_VOLUME: 0.6,
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.6)
        kitchen.async_set_volume_level.assert_called_once_with(0.6)

    @pytest.mark.asyncio
    async def test_delta_shift_preserves_slave_offsets(
        self, hass: HomeAssistant
    ) -> None:
        """Master moves +0.20; each slave shifts by the same +0.20 from its
        own current volume, preserving the offset captured at group time."""
        master, (kitchen, bedroom) = _make_group(
            hass,
            "media_player.living_room",
            ["media_player.kitchen", "media_player.bedroom"],
        )
        master.volume_level = 0.40
        kitchen.volume_level = 0.30  # -0.10 offset
        bedroom.volume_level = 0.60  # +0.20 offset
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.60,
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.60)
        kitchen.async_set_volume_level.assert_called_once_with(
            pytest.approx(0.50)
        )
        bedroom.async_set_volume_level.assert_called_once_with(
            pytest.approx(0.80)
        )

    @pytest.mark.asyncio
    async def test_delta_shift_clamps_slave_at_upper_bound(
        self, hass: HomeAssistant
    ) -> None:
        master, (kitchen,) = _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        master.volume_level = 0.50
        kitchen.volume_level = 0.90
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.90,  # +0.40 delta -> kitchen would be 1.30
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.90)
        kitchen.async_set_volume_level.assert_called_once_with(1.0)

    @pytest.mark.asyncio
    async def test_delta_shift_clamps_slave_at_lower_bound(
        self, hass: HomeAssistant
    ) -> None:
        master, (kitchen,) = _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        master.volume_level = 0.50
        kitchen.volume_level = 0.10
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.20,  # -0.30 delta -> kitchen would be -0.20
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.20)
        kitchen.async_set_volume_level.assert_called_once_with(0.0)

