"""Tests for top-level integration setup/teardown in __init__.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.linkplay import (
    DOMAIN,
    LinkPlayData,
    async_reload_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)


class TestAsyncSetup:
    @pytest.mark.asyncio
    async def test_seeds_data_and_registers_services(self) -> None:
        hass = MagicMock()
        hass.data = {}
        hass.services = MagicMock()
        hass.services.async_register = MagicMock()
        result = await async_setup(hass, {})
        assert result is True
        assert isinstance(hass.data[DOMAIN], LinkPlayData)
        # Services registered (join, unjoin, etc.)
        assert hass.services.async_register.call_count >= 5


class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_forwards_to_platforms_and_attaches_listener(self) -> None:
        hass = MagicMock()
        hass.data = {}
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        hass.services = MagicMock()
        hass.services.has_service = MagicMock(return_value=True)
        entry = MagicMock()
        entry.title = "Living Room"
        entry.async_on_unload = MagicMock()
        entry.add_update_listener = MagicMock(return_value=MagicMock())
        result = await async_setup_entry(hass, entry)
        assert result is True
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()
        entry.async_on_unload.assert_called_once()

    @pytest.mark.asyncio
    async def test_registers_services_when_missing(self) -> None:
        hass = MagicMock()
        hass.data = {}
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        hass.services = MagicMock()
        # First call returns False -> triggers async_setup_services
        hass.services.has_service = MagicMock(return_value=False)
        hass.services.async_register = MagicMock()
        entry = MagicMock()
        entry.title = "X"
        await async_setup_entry(hass, entry)
        assert hass.services.async_register.call_count >= 5


class TestReloadAndUnload:
    @pytest.mark.asyncio
    async def test_async_reload_entry_calls_reload(self) -> None:
        hass = MagicMock()
        hass.config_entries.async_reload = AsyncMock()
        entry = MagicMock()
        entry.entry_id = "abc"
        await async_reload_entry(hass, entry)
        hass.config_entries.async_reload.assert_awaited_once_with("abc")

    @pytest.mark.asyncio
    async def test_unload_last_entry_removes_services(self) -> None:
        hass = MagicMock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        hass.config_entries.async_entries = MagicMock(return_value=[])
        hass.services = MagicMock()
        hass.services.has_service = MagicMock(return_value=True)
        hass.services.async_remove = MagicMock()
        entry = MagicMock()
        result = await async_unload_entry(hass, entry)
        assert result is True
        # All eight services attempted for removal
        assert hass.services.async_remove.call_count == 8

    @pytest.mark.asyncio
    async def test_unload_with_remaining_entries_keeps_services(self) -> None:
        hass = MagicMock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        # Still other entries left -> services NOT removed
        hass.config_entries.async_entries = MagicMock(return_value=[MagicMock()])
        hass.services = MagicMock()
        hass.services.async_remove = MagicMock()
        entry = MagicMock()
        await async_unload_entry(hass, entry)
        hass.services.async_remove.assert_not_called()
