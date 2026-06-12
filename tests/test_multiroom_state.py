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


class TestJoinPlayersSignature:
    """Regression: HA media_player.join passes group_members as kwarg.

    v4.5.6: the parameter was named ``slaves`` so HA core's call
    ``await async_join_players(group_members=[...])`` raised
    ``TypeError: got an unexpected keyword argument 'group_members'``.
    The fix renames the parameter to match HA's contract.
    """

    @pytest.mark.asyncio
    async def test_async_join_players_accepts_group_members_kwarg(self) -> None:
        from custom_components.linkplay.multiroom_mixin import (
            LinkPlayMultiroomMixin,
        )

        # Inspect signature directly: we only need to prove the kwarg name.
        import inspect

        sig = inspect.signature(LinkPlayMultiroomMixin.async_join_players)
        assert "group_members" in sig.parameters
        assert "slaves" not in sig.parameters

    @pytest.mark.asyncio
    async def test_async_join_players_routes_entities_to_async_join(
        self,
    ) -> None:
        master = _make_device("master")
        slave_a = _make_device("a")
        slave_b = _make_device("b")
        other = _make_device("other")
        master.hass.data["linkplay"].entities = [master, slave_a, slave_b, other]
        master.async_join = AsyncMock()

        await master.async_join_players(
            group_members=["media_player.a", "media_player.b"]
        )

        master.async_join.assert_awaited_once()
        passed = master.async_join.await_args.args[0]
        assert {e.entity_id for e in passed} == {
            "media_player.a",
            "media_player.b",
        }


class TestJoinGracePollWindow:
    """v4.5.9: ``multiroom:getSlaveList`` returns ``slaves=0`` for several
    seconds after a WiFi-direct ``ConnectMasterAp`` join on AudioPro
    firmware. The master-side poll must keep the locally-built
    ``_multiroom_group`` during that grace window, or
    ``linkplay.set_group_volume`` finds an empty group when it runs
    immediately after ``linkplay.join``.
    """

    @pytest.mark.asyncio
    async def test_poll_preserves_group_during_grace_when_firmware_says_zero(
        self,
    ) -> None:
        from datetime import timedelta
        from homeassistant.util.dt import utcnow

        master = _make_device("master")
        master.hass.data["linkplay"].entities = [master]
        master._is_master = True
        master._multiroom_group = [
            "media_player.master",
            "media_player.kitchen",
        ]
        master._multiroom_joinat = utcnow() - timedelta(seconds=2)
        master.call_linkplay_httpapi = AsyncMock(
            return_value={"slaves": 0, "slave_list": []}
        )

        await master._async_poll_multiroom_master_status()

        assert master._is_master is True
        assert master._multiroom_group == [
            "media_player.master",
            "media_player.kitchen",
        ]

    @pytest.mark.asyncio
    async def test_poll_clears_group_after_grace_when_firmware_says_zero(
        self,
    ) -> None:
        from datetime import timedelta
        from homeassistant.util.dt import utcnow

        master = _make_device("master")
        master.hass.data["linkplay"].entities = [master]
        master._is_master = True
        master._multiroom_group = [
            "media_player.master",
            "media_player.kitchen",
        ]
        master._multiroom_joinat = utcnow() - timedelta(seconds=30)
        master.call_linkplay_httpapi = AsyncMock(
            return_value={"slaves": 0, "slave_list": []}
        )

        await master._async_poll_multiroom_master_status()

        assert master._is_master is False
        assert master._multiroom_group == []

    @pytest.mark.asyncio
    async def test_poll_clears_grace_timestamp_when_firmware_confirms_slaves(
        self,
    ) -> None:
        from homeassistant.util.dt import utcnow

        master = _make_device("master")
        kitchen = _make_device("kitchen")
        master.hass.data["linkplay"].entities = [master, kitchen]
        master._is_master = True
        master._multiroom_group = [
            "media_player.master",
            "media_player.kitchen",
        ]
        master._multiroom_joinat = utcnow()
        master.call_linkplay_httpapi = AsyncMock(
            return_value={
                "slaves": 1,
                "slave_list": [
                    {"name": "kitchen", "ip": "1.2.3.4", "volume": 50},
                ],
            }
        )

        await master._async_poll_multiroom_master_status()

        assert master._multiroom_joinat is None
        assert master._is_master is True
        assert "media_player.kitchen" in master._multiroom_group

    @pytest.mark.asyncio
    async def test_poll_skips_slave_volume_within_grace(self) -> None:
        """v4.5.15: a ``multiroom:getSlaveList`` response in flight while
        the group volume changed reports each slave's pre-change volume;
        within VOLUME_CMD_GRACE the locally commanded value wins."""
        from homeassistant.util.dt import utcnow

        master = _make_device("master")
        kitchen = _make_device("kitchen")
        master.hass.data["linkplay"].entities = [master, kitchen]
        master._is_master = True
        master._multiroom_group = [
            "media_player.master",
            "media_player.kitchen",
        ]
        kitchen._volume = 8
        kitchen._volume_cmd_at = utcnow()
        master.call_linkplay_httpapi = AsyncMock(
            return_value={
                "slaves": 1,
                "slave_list": [
                    {"name": "kitchen", "ip": "1.2.3.4", "volume": 50},
                ],
            }
        )

        await master._async_poll_multiroom_master_status()

        assert kitchen._volume == 8

    @pytest.mark.asyncio
    async def test_poll_updates_slave_volume_after_grace(self) -> None:
        from datetime import timedelta

        from homeassistant.util.dt import utcnow

        master = _make_device("master")
        kitchen = _make_device("kitchen")
        master.hass.data["linkplay"].entities = [master, kitchen]
        master._is_master = True
        master._multiroom_group = [
            "media_player.master",
            "media_player.kitchen",
        ]
        kitchen._volume = 8
        kitchen._volume_cmd_at = utcnow() - timedelta(seconds=10)
        master.call_linkplay_httpapi = AsyncMock(
            return_value={
                "slaves": 1,
                "slave_list": [
                    {"name": "kitchen", "ip": "1.2.3.4", "volume": 50},
                ],
            }
        )

        await master._async_poll_multiroom_master_status()

        assert kitchen._volume == 50

    @pytest.mark.asyncio
    async def test_poll_no_response_preserves_group_during_grace(
        self,
    ) -> None:
        from datetime import timedelta
        from homeassistant.util.dt import utcnow

        master = _make_device("master")
        master.hass.data["linkplay"].entities = [master]
        master._is_master = True
        master._multiroom_group = [
            "media_player.master",
            "media_player.kitchen",
        ]
        master._multiroom_joinat = utcnow() - timedelta(seconds=2)
        master.call_linkplay_httpapi = AsyncMock(return_value=None)

        await master._async_poll_multiroom_master_status()

        assert master._is_master is True
        assert master._multiroom_group == [
            "media_player.master",
            "media_player.kitchen",
        ]


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
