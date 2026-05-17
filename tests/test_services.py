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
    ATTR_VOLUME_OFFSETS,
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
    async def test_percentage_offsets_apply_per_speaker(
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
                ATTR_VOLUME_OFFSETS: {
                    "media_player.kitchen": -10,
                    "media_player.bedroom": 20,
                },
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.5)
        kitchen.async_set_volume_level.assert_called_once_with(0.4)
        bedroom.async_set_volume_level.assert_called_once_with(0.7)

    @pytest.mark.asyncio
    async def test_offset_clamps_at_upper_and_lower_bounds(
        self, hass: HomeAssistant
    ) -> None:
        master, (kitchen,) = _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.9,
                ATTR_VOLUME_OFFSETS: {"media_player.kitchen": 50},
            },
            blocking=True,
        )
        master.async_set_volume_level.assert_called_with(0.9)
        kitchen.async_set_volume_level.assert_called_with(1.0)

        master.async_set_volume_level.reset_mock()
        kitchen.async_set_volume_level.reset_mock()

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.1,
                ATTR_VOLUME_OFFSETS: {"media_player.kitchen": -50},
            },
            blocking=True,
        )
        master.async_set_volume_level.assert_called_with(0.1)
        kitchen.async_set_volume_level.assert_called_with(0.0)

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
    async def test_fractional_offsets_preserved(self, hass: HomeAssistant) -> None:
        master, (kitchen,) = _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.5,
                ATTR_VOLUME_OFFSETS: {"media_player.kitchen": 0.15},
            },
            blocking=True,
        )

        kitchen.async_set_volume_level.assert_called_once_with(0.65)

    @pytest.mark.asyncio
    async def test_fractional_extreme_offsets_clamp(
        self, hass: HomeAssistant
    ) -> None:
        master, (kitchen,) = _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.5,
                ATTR_VOLUME_OFFSETS: {"media_player.kitchen": 1.0},
            },
            blocking=True,
        )
        kitchen.async_set_volume_level.assert_called_with(1.0)

        kitchen.async_set_volume_level.reset_mock()

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.5,
                ATTR_VOLUME_OFFSETS: {"media_player.kitchen": -1.0},
            },
            blocking=True,
        )
        kitchen.async_set_volume_level.assert_called_with(0.0)

    @pytest.mark.asyncio
    async def test_invalid_percentage_range_raises(
        self, hass: HomeAssistant
    ) -> None:
        _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        await async_setup_services(hass)

        with pytest.raises(ValueError, match="expected value between -100 and 100"):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_SET_GROUP_VOLUME,
                {
                    ATTR_ENTITY_ID: "media_player.living_room",
                    ATTR_VOLUME: 0.5,
                    ATTR_VOLUME_OFFSETS: {"media_player.kitchen": 150},
                },
                blocking=True,
            )

        with pytest.raises(ValueError, match="expected value between -100 and 100"):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_SET_GROUP_VOLUME,
                {
                    ATTR_ENTITY_ID: "media_player.living_room",
                    ATTR_VOLUME: 0.5,
                    ATTR_VOLUME_OFFSETS: {"media_player.kitchen": -200},
                },
                blocking=True,
            )

    @pytest.mark.asyncio
    async def test_invalid_fractional_range_raises(
        self, hass: HomeAssistant
    ) -> None:
        _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        await async_setup_services(hass)

        with pytest.raises(ValueError, match="expected value between -1.0 and 1.0"):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_SET_GROUP_VOLUME,
                {
                    ATTR_ENTITY_ID: "media_player.living_room",
                    ATTR_VOLUME: 0.5,
                    ATTR_VOLUME_OFFSETS: {"media_player.kitchen": 1.5},
                },
                blocking=True,
            )

        with pytest.raises(ValueError, match="expected value between -1.0 and 1.0"):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_SET_GROUP_VOLUME,
                {
                    ATTR_ENTITY_ID: "media_player.living_room",
                    ATTR_VOLUME: 0.5,
                    ATTR_VOLUME_OFFSETS: {"media_player.kitchen": -1.5},
                },
                blocking=True,
            )

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

    @pytest.mark.asyncio
    async def test_offsets_override_delta_for_listed_speakers(
        self, hass: HomeAssistant
    ) -> None:
        """Speakers in volume_offsets get ``volume + offset`` absolute;
        speakers not listed still follow the delta-shift."""
        master, (kitchen, bedroom) = _make_group(
            hass,
            "media_player.living_room",
            ["media_player.kitchen", "media_player.bedroom"],
        )
        master.volume_level = 0.40
        kitchen.volume_level = 0.30  # delta-shift candidate
        bedroom.volume_level = 0.60  # overridden
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.60,  # delta = +0.20
                ATTR_VOLUME_OFFSETS: {"media_player.bedroom": 10},  # absolute
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.60)
        kitchen.async_set_volume_level.assert_called_once_with(
            pytest.approx(0.50)
        )
        bedroom.async_set_volume_level.assert_called_once_with(
            pytest.approx(0.70)
        )

    @pytest.mark.asyncio
    async def test_master_in_offsets_still_pinned_to_volume(
        self, hass: HomeAssistant
    ) -> None:
        """Master entity passed inside volume_offsets must still land on
        `volume`, not `volume + offset` - otherwise a stray master entry
        would double-shift the master's own slider."""
        master, (kitchen,) = _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        master.volume_level = 0.30
        kitchen.volume_level = 0.30
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.50,
                ATTR_VOLUME_OFFSETS: {"media_player.living_room": 20},
            },
            blocking=True,
        )

        master.async_set_volume_level.assert_called_once_with(0.50)

    @pytest.mark.asyncio
    async def test_volume_offsets_emits_deprecation_warning_once_per_entity(
        self, hass: HomeAssistant
    ) -> None:
        import warnings

        _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        await async_setup_services(hass)

        call_payload = {
            ATTR_ENTITY_ID: "media_player.living_room",
            ATTR_VOLUME: 0.50,
            ATTR_VOLUME_OFFSETS: {"media_player.kitchen": 10},
        }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            await hass.services.async_call(
                DOMAIN, SERVICE_SET_GROUP_VOLUME, call_payload, blocking=True,
            )
            await hass.services.async_call(
                DOMAIN, SERVICE_SET_GROUP_VOLUME, call_payload, blocking=True,
            )

        deprecation_count = sum(
            1
            for w in caught
            if issubclass(w.category, DeprecationWarning)
            and "volume_offsets is deprecated" in str(w.message)
        )
        assert deprecation_count == 1, (
            f"expected one DeprecationWarning across two calls; got {deprecation_count}"
        )

    @pytest.mark.asyncio
    async def test_invalid_offset_types_raise(self, hass: HomeAssistant) -> None:
        _make_group(
            hass, "media_player.living_room", ["media_player.kitchen"]
        )
        await async_setup_services(hass)

        for bad_value, type_name in (("invalid", "str"), ([0.5], "list"), (True, "bool")):
            with pytest.raises(
                ValueError,
                match=rf"Invalid type {type_name} for volume offset.*expected int \(percentage\) or float \(fractional\)",
            ):
                await hass.services.async_call(
                    DOMAIN,
                    SERVICE_SET_GROUP_VOLUME,
                    {
                        ATTR_ENTITY_ID: "media_player.living_room",
                        ATTR_VOLUME: 0.5,
                        ATTR_VOLUME_OFFSETS: {"media_player.kitchen": bad_value},
                    },
                    blocking=True,
                )
