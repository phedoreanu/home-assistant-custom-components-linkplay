"""Regression tests for multiroom group state on the media_player entity.

These tests protect the fixes in v4.0.4 (group_members property + state
push after join/unjoin) and v4.0.5 (slave poll cycle must not wipe the
group pushed by the master).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from custom_components.linkplay.media_player import LinkPlayDevice


def _make_device(name: str = "device") -> LinkPlayDevice:
    """Construct a minimal LinkPlayDevice without doing any I/O."""
    from custom_components.linkplay.media_player import LinkPlayDevice

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
    # MediaPlayerEntity.hass is normally set by HA during async_added_to_hass;
    # set it manually here so async_update can reach hass.data[DOMAIN].
    dev.hass = hass
    return dev


class TestGroupMembersProperty:
    """group_members must reflect _multiroom_group for HA / mini-media-player."""

    def test_empty_group_returns_empty_list(self) -> None:
        dev = _make_device()
        assert dev.group_members == []

    def test_returns_current_group(self) -> None:
        dev = _make_device()
        dev._multiroom_group = ["media_player.a", "media_player.b"]
        assert dev.group_members == ["media_player.a", "media_player.b"]

    def test_returned_list_is_isolated_copy(self) -> None:
        """Mutating the returned list must not corrupt internal state."""
        dev = _make_device()
        dev._multiroom_group = ["media_player.a"]
        got = dev.group_members
        got.append("media_player.b")
        assert dev._multiroom_group == ["media_player.a"]


class TestMultiroomGroupSetter:
    """Master pushes group to slaves via async_set_multiroom_group."""

    @pytest.mark.asyncio
    async def test_setter_updates_state(self) -> None:
        dev = _make_device()
        await dev.async_set_multiroom_group(
            ["media_player.master", "media_player.slave"]
        )
        assert dev._multiroom_group == [
            "media_player.master",
            "media_player.slave",
        ]
        assert dev.group_members == [
            "media_player.master",
            "media_player.slave",
        ]


class TestSlavePollPreservesGroup:
    """Regression for v4.0.5: slave's async_update must not wipe its group.

    When _slave_mode is True and _master is set, async_update must early
    return at the slave-mode guard, leaving _multiroom_group intact.
    Without this, cards see group_members go empty every poll cycle (3 s).
    """

    @pytest.mark.asyncio
    async def test_slave_with_valid_master_preserves_group(self) -> None:
        master = _make_device("master")
        master._is_master = True
        master.entity_id = "media_player.master"

        slave = _make_device("slave")
        slave._slave_mode = True
        slave._master = master
        slave._multiroom_group = [
            "media_player.master",
            "media_player.slave",
        ]

        # async_update should short-circuit on slaves; no HTTP calls.
        slave.call_linkplay_httpapi = AsyncMock(
            side_effect=AssertionError(
                "slave must not call the device API in slave_mode"
            )
        )

        result = await slave.async_update()

        assert result is True
        assert slave._slave_mode is True
        assert slave._multiroom_group == [
            "media_player.master",
            "media_player.slave",
        ]
        assert slave.group_members == [
            "media_player.master",
            "media_player.slave",
        ]

    @pytest.mark.asyncio
    async def test_slave_with_lost_master_ref_recovers_from_entities(self) -> None:
        """Slave whose python _master ref was lost should re-resolve the
        master from the registered entities by the entity_id stored in
        _multiroom_group[0], rather than dropping slave_mode and wiping
        the group on the next poll.
        """
        master = _make_device("master")
        master._is_master = True
        master.entity_id = "media_player.master"

        slave = _make_device("slave")
        slave._slave_mode = True
        slave._master = None  # ref lost (e.g. master entity reloaded)
        slave._multiroom_group = [
            "media_player.master",
            "media_player.slave",
        ]
        slave.hass.data["linkplay"].entities = [master, slave]

        await slave.async_update()

        assert slave._slave_mode is True
        assert slave._master is master
        assert slave._multiroom_group == [
            "media_player.master",
            "media_player.slave",
        ]

    @pytest.mark.asyncio
    async def test_slave_without_master_and_without_group_drops_slave_mode(
        self,
    ) -> None:
        """Edge case: nothing to recover from -> slave_mode falls back to
        False, but only when there's truly no group to anchor on."""
        slave = _make_device("orphan")
        slave._slave_mode = True
        slave._master = None
        slave._multiroom_group = []
        slave.hass.data["linkplay"].entities = [slave]

        slave.async_get_status = AsyncMock()
        slave._player_statdata = None
        slave.call_linkplay_httpapi = AsyncMock(return_value=None)

        await slave.async_update()

        assert slave._slave_mode is False
