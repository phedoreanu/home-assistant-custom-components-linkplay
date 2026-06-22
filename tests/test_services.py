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
        self._volume_offset = 0  # default: slave tracks master target
        # Make async_set_volume_level update volume_level too so tests
        # that issue multiple group-volume calls see the result of the
        # previous call reflected on the next iteration.
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
    async def test_per_slave_offsets_anchored_to_master_target(
        self, hass: HomeAssistant
    ) -> None:
        """v4.5.13: each slave's target is ``master_target + offset/100``
        with offset in signed percentage points. Mirrors mini-media-player's
        per-entity ``volume_offset`` semantics."""
        master, (kitchen, office) = _make_group(
            hass,
            "media_player.living_room",
            ["media_player.kitchen", "media_player.office"],
        )
        # Master's current volume is irrelevant - the new behaviour
        # anchors every slave to the new master target plus the
        # configured per-slave offset.
        master.volume_level = 1.0  # post-Bluetooth, irrelevant
        kitchen._volume_offset = -10
        office._volume_offset = -15
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.18,
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.18)
        kitchen.async_set_volume_level.assert_called_once_with(
            pytest.approx(0.08)
        )
        office.async_set_volume_level.assert_called_once_with(
            pytest.approx(0.03)
        )

    @pytest.mark.asyncio
    async def test_zero_offset_keeps_slave_on_master_target(
        self, hass: HomeAssistant
    ) -> None:
        """Slave with default offset 0 ends at the same value as master."""
        master, (kitchen,) = _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.42,
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.42)
        kitchen.async_set_volume_level.assert_called_once_with(0.42)

    @pytest.mark.asyncio
    async def test_positive_offset_above_master_clamps_at_one(
        self, hass: HomeAssistant
    ) -> None:
        master, (kitchen,) = _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        kitchen._volume_offset = 50
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.90,  # 0.90 + 0.50 -> would be 1.40
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.90)
        kitchen.async_set_volume_level.assert_called_once_with(1.0)

    @pytest.mark.asyncio
    async def test_master_always_set_even_with_empty_group(
        self, hass: HomeAssistant
    ) -> None:
        """v4.5.9 defensive guard: the master is always reached by
        ``async_set_group_volume`` even if ``_multiroom_group`` is empty
        (e.g. the master-side poll briefly cleared the list during a
        WiFi-direct join propagation race that outlived the join-grace
        window).
        """
        master, _ = _make_group(
            hass, "media_player.living_room", []
        )
        master._multiroom_group = []  # poll-cleared
        master.volume_level = 0.40
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.18,
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.18)

    @pytest.mark.asyncio
    async def test_negative_offset_below_master_clamps_at_zero(
        self, hass: HomeAssistant
    ) -> None:
        master, (kitchen,) = _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        kitchen._volume_offset = -50
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.20,  # 0.20 + (-0.50) -> would be -0.30
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.20)
        kitchen.async_set_volume_level.assert_called_once_with(0.0)

