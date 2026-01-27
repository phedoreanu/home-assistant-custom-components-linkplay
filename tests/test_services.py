"""Tests for Linkplay services."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.linkplay import (
    DOMAIN,
    SERVICE_SET_GROUP_VOLUME,
    ATTR_VOLUME,
    ATTR_VOLUME_OFFSETS,
)
from custom_components.linkplay.const import CONF_ICECAST_METADATA
from homeassistant.const import ATTR_ENTITY_ID

# MockConfigEntry compatibility
try:
    from pytest_homeassistant_custom_component.common import MockConfigEntry
except ImportError:
    try:
        from homeassistant.test.common import MockConfigEntry
    except ImportError:
        # Fallback for older Home Assistant versions
        class MockConfigEntry:  # type: ignore
            """Mock config entry."""
            def __init__(self, domain, data, title=None, unique_id=None):
                self.domain = domain
                self.data = data
                self.title = title or "Mock Entry"
                self.unique_id = unique_id
                self.options = {}
                self.entry_id = "test_entry_id"

            def add_to_hass(self, hass):
                """Add to hass."""
                pass


class MockLinkplayDevice:
    """Mock Linkplay device for testing."""

    def __init__(self, entity_id: str, hass: HomeAssistant):
        """Initialize mock device."""
        self.entity_id = entity_id
        self.hass = hass
        self._is_master = False
        self._slave_mode = False
        self._multiroom_group = []
        self._volume = 0
        self.async_set_volume_level = AsyncMock()
        self.async_set_group_volume = AsyncMock()

    @property
    def is_master(self):
        """Return if device is master."""
        return self._is_master


class TestLinkplaySetGroupVolumeService:
    """Test the set_group_volume service."""

    @pytest.fixture
    def mock_linkplay_data(self):
        """Create mock LinkPlay data structure."""
        from custom_components.linkplay import LinkPlayData
        return LinkPlayData()

    @pytest.mark.asyncio
    async def test_set_group_volume_without_offsets(self, hass: HomeAssistant, mock_linkplay_data):
        """Test setting group volume without offsets."""
        # Create mock devices
        master = MockLinkplayDevice("media_player.living_room", hass)
        master._is_master = True
        master._multiroom_group = [
            "media_player.living_room",
            "media_player.kitchen",
            "media_player.bedroom"
        ]

        slave1 = MockLinkplayDevice("media_player.kitchen", hass)
        slave1._slave_mode = True

        slave2 = MockLinkplayDevice("media_player.bedroom", hass)
        slave2._slave_mode = True

        # Setup the LinkPlay data
        mock_linkplay_data.entities = [master, slave1, slave2]
        hass.data[DOMAIN] = mock_linkplay_data

        # Mock the async_set_group_volume to track calls
        called_devices = []
        called_volumes = []
        called_offsets = []

        async def mock_set_group_volume(volume, volume_offsets=None):
            called_devices.append(master.entity_id)
            called_volumes.append(volume)
            called_offsets.append(volume_offsets)

            # Simulate setting volume on all devices
            for entity_id in master._multiroom_group:
                for device in hass.data[DOMAIN].entities:
                    if device.entity_id == entity_id:
                        offset = (volume_offsets or {}).get(entity_id, 0.0)
                        final_volume = max(0.0, min(1.0, volume + offset))
                        await device.async_set_volume_level(final_volume)

        master.async_set_group_volume = mock_set_group_volume

        # Register and call the service
        from custom_components.linkplay import async_setup_services
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

        # Verify the service was called correctly
        assert len(called_devices) == 1
        assert called_volumes[0] == 0.5
        assert called_offsets[0] == {}

        # Verify volume was set on all devices
        master.async_set_volume_level.assert_called_once_with(0.5)
        slave1.async_set_volume_level.assert_called_once_with(0.5)
        slave2.async_set_volume_level.assert_called_once_with(0.5)

    @pytest.mark.asyncio
    async def test_set_group_volume_with_offsets(self, hass: HomeAssistant, mock_linkplay_data):
        """Test setting group volume with individual speaker offsets."""
        # Create mock devices
        master = MockLinkplayDevice("media_player.living_room", hass)
        master._is_master = True
        master._multiroom_group = [
            "media_player.living_room",
            "media_player.kitchen",
            "media_player.bedroom"
        ]

        slave1 = MockLinkplayDevice("media_player.kitchen", hass)
        slave1._slave_mode = True

        slave2 = MockLinkplayDevice("media_player.bedroom", hass)
        slave2._slave_mode = True

        # Setup the LinkPlay data
        mock_linkplay_data.entities = [master, slave1, slave2]
        hass.data[DOMAIN] = mock_linkplay_data

        # Mock the async_set_group_volume to track calls
        called_volumes = []
        called_offsets = []

        async def mock_set_group_volume(volume, volume_offsets=None):
            called_volumes.append(volume)
            called_offsets.append(volume_offsets)

            # Simulate setting volume on all devices with offsets
            for entity_id in master._multiroom_group:
                for device in hass.data[DOMAIN].entities:
                    if device.entity_id == entity_id:
                        offset = (volume_offsets or {}).get(entity_id, 0.0)
                        final_volume = max(0.0, min(1.0, volume + offset))
                        await device.async_set_volume_level(final_volume)

        master.async_set_group_volume = mock_set_group_volume

        # Register and call the service
        from custom_components.linkplay import async_setup_services
        await async_setup_services(hass)

        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.5,
                ATTR_VOLUME_OFFSETS: {
                    "media_player.kitchen": -10,  # -10% offset
                    "media_player.bedroom": 20,   # +20% offset
                },
            },
            blocking=True,
        )

        # Verify the service was called correctly
        assert called_volumes[0] == 0.5
        # The percentage offsets (-10 and 20) must be normalized to fractional values (-0.1 and 0.2)
        assert called_offsets[0] == {
            "media_player.kitchen": -0.1,
            "media_player.bedroom": 0.2,
        }

        # Verify volume was set with offsets
        master.async_set_volume_level.assert_called_once_with(0.5)  # 0.5 + 0.0
        slave1.async_set_volume_level.assert_called_once_with(0.4)  # 0.5 - 0.1
        slave2.async_set_volume_level.assert_called_once_with(0.7)  # 0.5 + 0.2

    @pytest.mark.asyncio
    async def test_set_group_volume_with_boundary_check(self, hass: HomeAssistant, mock_linkplay_data):
        """Test that volume offsets respect 0.0-1.0 boundaries."""
        # Create mock devices
        master = MockLinkplayDevice("media_player.living_room", hass)
        master._is_master = True
        master._multiroom_group = [
            "media_player.living_room",
            "media_player.kitchen",
        ]

        slave1 = MockLinkplayDevice("media_player.kitchen", hass)
        slave1._slave_mode = True

        # Setup the LinkPlay data
        mock_linkplay_data.entities = [master, slave1]
        hass.data[DOMAIN] = mock_linkplay_data

        # Mock the async_set_group_volume
        async def mock_set_group_volume(volume, volume_offsets=None):
            # Simulate setting volume on all devices with boundary checks
            for entity_id in master._multiroom_group:
                for device in hass.data[DOMAIN].entities:
                    if device.entity_id == entity_id:
                        offset = (volume_offsets or {}).get(entity_id, 0.0)
                        final_volume = max(0.0, min(1.0, volume + offset))
                        await device.async_set_volume_level(final_volume)

        master.async_set_group_volume = mock_set_group_volume

        # Register and call the service
        from custom_components.linkplay import async_setup_services
        await async_setup_services(hass)

        # Test with offset that would exceed maximum
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.9,
                ATTR_VOLUME_OFFSETS: {
                    "media_player.kitchen": 50,  # Would be 1.4, should cap at 1.0
                },
            },
            blocking=True,
        )

        # Verify volume was capped at maximum
        master.async_set_volume_level.assert_called_with(0.9)
        slave1.async_set_volume_level.assert_called_with(1.0)  # Capped at 1.0

        # Reset mocks
        master.async_set_volume_level.reset_mock()
        slave1.async_set_volume_level.reset_mock()

        # Test with offset that would go below minimum
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.1,
                ATTR_VOLUME_OFFSETS: {
                    "media_player.kitchen": -50,  # Would be -0.4, should floor at 0.0
                },
            },
            blocking=True,
        )

        # Verify volume was floored at minimum
        master.async_set_volume_level.assert_called_with(0.1)
        slave1.async_set_volume_level.assert_called_with(0.0)  # Floored at 0.0

    @pytest.mark.asyncio
    async def test_set_group_volume_non_master_entity(self, hass: HomeAssistant, mock_linkplay_data):
        """Test calling service on a non-master entity."""
        # Create mock devices
        master = MockLinkplayDevice("media_player.living_room", hass)
        master._is_master = True
        master._multiroom_group = ["media_player.living_room", "media_player.kitchen"]

        slave1 = MockLinkplayDevice("media_player.kitchen", hass)
        slave1._slave_mode = True

        # Setup the LinkPlay data
        mock_linkplay_data.entities = [master, slave1]
        hass.data[DOMAIN] = mock_linkplay_data

        # Register the service
        from custom_components.linkplay import async_setup_services
        await async_setup_services(hass)

        # Call service on the slave - it should still work
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.kitchen",
                ATTR_VOLUME: 0.6,
            },
            blocking=True,
        )

        # Verify the service was called on the slave device
        slave1.async_set_group_volume.assert_called_once_with(0.6, {})

    @pytest.mark.asyncio
    async def test_set_group_volume_percentage_conversion(self, hass: HomeAssistant, mock_linkplay_data):
        """Test that percentage-style offsets are converted to fractional values."""
        # Create mock devices
        master = MockLinkplayDevice("media_player.living_room", hass)
        master._is_master = True
        master._multiroom_group = [
            "media_player.living_room",
            "media_player.kitchen",
        ]

        slave1 = MockLinkplayDevice("media_player.kitchen", hass)
        slave1._slave_mode = True

        # Setup the LinkPlay data
        mock_linkplay_data.entities = [master, slave1]
        hass.data[DOMAIN] = mock_linkplay_data

        # Mock the async_set_group_volume to track calls
        called_offsets = []

        async def mock_set_group_volume(volume, volume_offsets=None):
            called_offsets.append(volume_offsets)

            # Simulate setting volume on all devices with offsets
            for entity_id in master._multiroom_group:
                for device in hass.data[DOMAIN].entities:
                    if device.entity_id == entity_id:
                        offset = (volume_offsets or {}).get(entity_id, 0.0)
                        final_volume = max(0.0, min(1.0, volume + offset))
                        await device.async_set_volume_level(final_volume)

        master.async_set_group_volume = mock_set_group_volume

        # Register and call the service
        from custom_components.linkplay import async_setup_services
        await async_setup_services(hass)

        # Test with percentage-style offsets (integers)
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.5,
                ATTR_VOLUME_OFFSETS: {
                    "media_player.kitchen": 15,  # 15% = 0.15
                },
            },
            blocking=True,
        )

        # Verify percentage was converted to fractional
        assert called_offsets[0] == {"media_player.kitchen": 0.15}
        slave1.async_set_volume_level.assert_called_with(0.65)  # 0.5 + 0.15

        # Reset
        called_offsets.clear()
        master.async_set_volume_level.reset_mock()
        slave1.async_set_volume_level.reset_mock()

        # Test with fractional offsets (for backwards compatibility)
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.5,
                ATTR_VOLUME_OFFSETS: {
                    "media_player.kitchen": 0.15,  # Already fractional
                },
            },
            blocking=True,
        )

        # Verify fractional offset was preserved
        assert called_offsets[0] == {"media_player.kitchen": 0.15}
        slave1.async_set_volume_level.assert_called_with(0.65)  # 0.5 + 0.15

        # Reset
        called_offsets.clear()
        master.async_set_volume_level.reset_mock()
        slave1.async_set_volume_level.reset_mock()

        # Test edge case: 1.0 is now treated as fractional (maximum offset), not as 1%
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.5,
                ATTR_VOLUME_OFFSETS: {
                    "media_player.kitchen": 1.0,  # Fractional: full +100% offset
                },
            },
            blocking=True,
        )

        # Verify 1.0 was preserved as fractional (clamped to max volume 1.0 by device)
        assert called_offsets[0] == {"media_player.kitchen": 1.0}
        slave1.async_set_volume_level.assert_called_with(1.0)  # 0.5 + 1.0 clamped to 1.0

        # Reset
        called_offsets.clear()
        master.async_set_volume_level.reset_mock()
        slave1.async_set_volume_level.reset_mock()

        # Test edge case: -1.0 is also treated as fractional (minimum offset)
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_GROUP_VOLUME,
            {
                ATTR_ENTITY_ID: "media_player.living_room",
                ATTR_VOLUME: 0.5,
                ATTR_VOLUME_OFFSETS: {
                    "media_player.kitchen": -1.0,  # Fractional: full -100% offset
                },
            },
            blocking=True,
        )

        # Verify -1.0 was preserved as fractional (clamped to min volume 0.0 by device)
        assert called_offsets[0] == {"media_player.kitchen": -1.0}
        slave1.async_set_volume_level.assert_called_with(0.0)  # 0.5 - 1.0 clamped to 0.0

    @pytest.mark.asyncio
    async def test_set_group_volume_invalid_percentage_range(self, hass: HomeAssistant, mock_linkplay_data):
        """Test that out-of-range percentage values are rejected."""
        # Create mock devices
        master = MockLinkplayDevice("media_player.living_room", hass)
        master._is_master = True
        master._multiroom_group = ["media_player.living_room", "media_player.kitchen"]

        slave1 = MockLinkplayDevice("media_player.kitchen", hass)
        slave1._slave_mode = True

        # Setup the LinkPlay data
        mock_linkplay_data.entities = [master, slave1]
        hass.data[DOMAIN] = mock_linkplay_data

        # Register the service
        from custom_components.linkplay import async_setup_services
        await async_setup_services(hass)

        # Test with percentage value exceeding maximum (150 > 100)
        with pytest.raises(ValueError, match="expected value between -100 and 100"):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_SET_GROUP_VOLUME,
                {
                    ATTR_ENTITY_ID: "media_player.living_room",
                    ATTR_VOLUME: 0.5,
                    ATTR_VOLUME_OFFSETS: {
                        "media_player.kitchen": 150,  # Out of range
                    },
                },
                blocking=True,
            )

        # Test with percentage value below minimum (-200 < -100)
        with pytest.raises(ValueError, match="expected value between -100 and 100"):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_SET_GROUP_VOLUME,
                {
                    ATTR_ENTITY_ID: "media_player.living_room",
                    ATTR_VOLUME: 0.5,
                    ATTR_VOLUME_OFFSETS: {
                        "media_player.kitchen": -200,  # Out of range
                    },
                },
                blocking=True,
            )

    @pytest.mark.asyncio
    async def test_set_group_volume_invalid_fractional_range(self, hass: HomeAssistant, mock_linkplay_data):
        """Test that out-of-range fractional values are rejected."""
        # Create mock devices
        master = MockLinkplayDevice("media_player.living_room", hass)
        master._is_master = True
        master._multiroom_group = ["media_player.living_room", "media_player.kitchen"]

        slave1 = MockLinkplayDevice("media_player.kitchen", hass)
        slave1._slave_mode = True

        # Setup the LinkPlay data
        mock_linkplay_data.entities = [master, slave1]
        hass.data[DOMAIN] = mock_linkplay_data

        # Register the service
        from custom_components.linkplay import async_setup_services
        await async_setup_services(hass)

        # Test with fractional value exceeding maximum (1.5 > 1.0)
        with pytest.raises(ValueError, match="expected value between -1.0 and 1.0"):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_SET_GROUP_VOLUME,
                {
                    ATTR_ENTITY_ID: "media_player.living_room",
                    ATTR_VOLUME: 0.5,
                    ATTR_VOLUME_OFFSETS: {
                        "media_player.kitchen": 1.5,  # Out of range
                    },
                },
                blocking=True,
            )

        # Test with fractional value below minimum (-1.5 < -1.0)
        with pytest.raises(ValueError, match="expected value between -1.0 and 1.0"):
            await hass.services.async_call(
                DOMAIN,
                SERVICE_SET_GROUP_VOLUME,
                {
                    ATTR_ENTITY_ID: "media_player.living_room",
                    ATTR_VOLUME: 0.5,
                    ATTR_VOLUME_OFFSETS: {
                        "media_player.kitchen": -1.5,  # Out of range
                    },
                },
                blocking=True,
            )

