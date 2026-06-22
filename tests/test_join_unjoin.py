"""Integration tests for the multiroom join / unjoin paths.

Uses real LinkPlayDevice instances (no I/O — call_linkplay_httpapi is
mocked, and async_write_ha_state is replaced with a noop because the
entity is not attached to a running HA instance).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests._helpers import make_device


def _make_device(name: str, host: str = "1.2.3.4"):
    # icecast_metadata="Off" is this module's only real constructor override;
    # everything else matches make_device's defaults.
    dev = make_device(name, host=host, icecast_metadata="Off")
    dev.async_write_ha_state = MagicMock()
    # Tests that exercise async_join don't need to wait 5 s for the
    # post-join slave-IP poll; cap it at one fast attempt unless the
    # individual test re-enables it.
    dev._slave_ip_poll_interval = 0
    dev._slave_ip_poll_max = 0
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


class TestJoinAwaitsSlaveIps:
    """v4.5.10: ``async_join`` blocks until the firmware reflects each
    new slave's WiFi-direct IP via ``multiroom:getSlaveList``. Without
    those IPs, ``multiroom:SlaveVolume`` is misaddressed to the master's
    own host and silently no-ops, so scripts that chained
    ``linkplay.join`` -> ``linkplay.set_group_volume`` left the slaves
    at their firmware-inherited join volume.
    """

    @pytest.mark.asyncio
    async def test_join_does_not_set_slave_ip_to_master_host(self) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        master.call_linkplay_httpapi = AsyncMock(return_value="OK")
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")

        await master.async_join([slave])

        # Regression: the previous code wrote master._host into the
        # slave's _slave_ip, which made multiroom:SlaveVolume target
        # the master and silently fail.
        assert slave._slave_ip != master._host

    @pytest.mark.asyncio
    async def test_join_populates_slave_ip_from_getslavelist(self) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")
        # Master returns OK to the ConnectMasterAp on the slave (slave's
        # mock above), then the next call - which is getSlaveList -
        # returns the populated list with the slave's WiFi-direct IP.
        master.call_linkplay_httpapi = AsyncMock(side_effect=[
            {
                "slaves": 1,
                "slave_list": [
                    {"name": "slave", "ip": "10.10.10.93", "volume": 50},
                ],
            },
        ])
        master._slave_ip_poll_max = 5
        master._slave_ip_poll_interval = 0

        await master.async_join([slave])

        assert slave._slave_ip == "10.10.10.93"

    @pytest.mark.asyncio
    async def test_join_syncs_slave_volume_for_delta_base(self) -> None:
        """v4.5.12: ``set_group_volume`` is delta-preserving; for the
        shift to land correctly each slave's cached ``_volume`` must
        reflect the post-join firmware value, not the stale pre-join
        cache. ``_await_slave_ips`` now copies ``volume`` from the
        ``multiroom:getSlaveList`` entry."""
        master, (slave,) = _make_group("master", ["slave"])
        slave._volume = 9  # stale pre-join cache
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")
        master.call_linkplay_httpapi = AsyncMock(side_effect=[
            {
                "slaves": 1,
                "slave_list": [
                    {"name": "slave", "ip": "10.10.10.93", "volume": 34},
                ],
            },
        ])
        master._slave_ip_poll_max = 5
        master._slave_ip_poll_interval = 0

        await master.async_join([slave])

        assert slave._volume == 34

    @pytest.mark.asyncio
    async def test_join_retries_until_firmware_reports_slaves(
        self,
    ) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")
        # First two polls return slaves=0 (firmware still settling);
        # third poll returns the real entry.
        master.call_linkplay_httpapi = AsyncMock(side_effect=[
            {"slaves": 0, "slave_list": []},
            {"slaves": 0, "slave_list": []},
            {
                "slaves": 1,
                "slave_list": [
                    {"name": "slave", "ip": "10.10.10.93", "volume": 50},
                ],
            },
        ])
        master._slave_ip_poll_max = 5
        master._slave_ip_poll_interval = 0

        await master.async_join([slave])

        assert slave._slave_ip == "10.10.10.93"
        assert master.call_linkplay_httpapi.await_count == 3

    @pytest.mark.asyncio
    async def test_join_gives_up_after_max_attempts(self) -> None:
        """Master should not block forever if the firmware never reports
        the slave in its multiroom list."""
        master, (slave,) = _make_group("master", ["slave"])
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")
        master.call_linkplay_httpapi = AsyncMock(
            return_value={"slaves": 0, "slave_list": []}
        )
        master._slave_ip_poll_max = 3
        master._slave_ip_poll_interval = 0

        await master.async_join([slave])

        assert master.call_linkplay_httpapi.await_count == 3


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


class TestJoinGraceArmedAtStart:
    """The grace window must cover the ENTIRE in-progress join, including a
    slow/offline slave's blocking ConnectMasterAp, so an interleaved master
    poll cannot tear the freshly-built group down (the 12:36 field bug)."""

    @pytest.mark.asyncio
    async def test_join_arms_grace_and_resets_stale_counter(self) -> None:
        master, (slave,) = _make_group("master", ["slave"])
        master.call_linkplay_httpapi = AsyncMock(return_value="OK")
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")
        master._slave_zero_polls = 9  # saturated from a prior standalone period

        await master.async_join([slave])

        assert master._multiroom_joinat is not None
        assert master._slave_zero_polls == 0

    @pytest.mark.asyncio
    async def test_groupless_poll_right_after_join_does_not_tear_down(self) -> None:
        """With grace armed at join start, a transient ``slaves==0`` poll
        immediately after the join keeps the group intact and does not even
        increment the zero-poll counter (grace short-circuits the AND)."""
        master, (slave,) = _make_group("master", ["slave"])
        master.call_linkplay_httpapi = AsyncMock(return_value="OK")
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")
        master._slave_zero_polls = 5  # pre-saturated, would tear down in one poll

        await master.async_join([slave])
        assert master._is_master is True
        group_after_join = list(master._multiroom_group)
        assert slave.entity_id in group_after_join

        # Firmware lags: getSlaveList reports zero slaves on the next poll.
        master.call_linkplay_httpapi = AsyncMock(
            return_value={"slaves": 0, "slave_list": []}
        )
        await master._async_poll_multiroom_master_status()

        assert master._is_master is True
        assert master._multiroom_group == group_after_join
        assert master._slave_zero_polls == 0  # grace short-circuited the counter

    @pytest.mark.asyncio
    async def test_all_slaves_fail_clears_grace(self) -> None:
        """Patch B self-heal: if every slave fails to join, don't leave a
        phantom master armed in the grace window."""
        master, (slave,) = _make_group("master", ["slave"])
        master.call_linkplay_httpapi = AsyncMock(return_value="OK")
        slave.call_linkplay_httpapi = AsyncMock(return_value="NOK")  # offline

        await master.async_join([slave])

        assert slave.entity_id not in master._multiroom_group
        assert master._multiroom_joinat is None


class TestAwaitSlaveIpsPolling:
    @pytest.mark.asyncio
    async def test_skips_non_dict_and_zero_slaves_then_succeeds(self) -> None:
        """``_await_slave_ips`` ignores a non-dict reply and a transient
        ``slaves==0`` reply, retrying until the firmware reports the slave
        with its WiFi-direct IP + volume."""
        master, (slave,) = _make_group("master", ["slave"])
        slave.call_linkplay_httpapi = AsyncMock(return_value="OK")
        master._slave_ip_poll_max = 5
        master._slave_ip_poll_interval = 0
        master.call_linkplay_httpapi = AsyncMock(side_effect=[
            "not-a-dict",                       # ignored (continue)
            {"slaves": 0, "slave_list": []},    # transient zero (continue)
            {
                "slaves": 1,
                "slave_list": [
                    {"name": "slave", "ip": "10.10.10.99", "volume": 40},
                ],
            },
        ])

        await master.async_join([slave])

        assert slave._slave_ip == "10.10.10.99"
        assert slave._volume == 40
