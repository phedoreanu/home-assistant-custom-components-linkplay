"""Tests for the volume / mute controls mixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.linkplay.volume_controls_mixin import LinkPlayVolumeControlsMixin


class _FakeDevice(LinkPlayVolumeControlsMixin):
    def __init__(
        self,
        *,
        volume: int = 50,
        step: int = 5,
        is_master: bool = False,
        slave_mode: bool = False,
        wifidirect: bool = False,
        snapshot: bool = False,
    ) -> None:
        self.entity_id = "media_player.fake"
        self._volume = volume
        self._volume_step = step
        self._is_master = is_master
        self._slave_mode = slave_mode
        self._multiroom_wifidirect = wifidirect
        self._snapshot_active = snapshot
        self._muted = False
        self._slave_ip = "5.6.7.8"
        self._master = MagicMock()
        self._master.call_linkplay_httpapi = AsyncMock(return_value="OK")
        self.call_linkplay_httpapi = AsyncMock(return_value="OK")


class TestSetVolume:
    @pytest.mark.asyncio
    async def test_master_sends_vol_not_slave_vol(self) -> None:
        """Master must use ``vol:N`` for its own HW volume.

        Regression for v4.5.5: master previously sent ``slave_vol:N``,
        which only broadcasts to slaves and leaves the master's hardware
        volume unchanged. The next poll would then revert the cached
        ``_volume`` back to the stale firmware value, and any group-wide
        re-sync (e.g. a preset switch) would push that stale master
        volume onto every slave.
        """
        dev = _FakeDevice(is_master=True)
        await dev.async_set_volume_level(0.30)
        dev.call_linkplay_httpapi.assert_awaited_once()
        cmd = dev.call_linkplay_httpapi.await_args.args[0]
        assert cmd == "setPlayerCmd:vol:30"
        assert "slave_vol" not in cmd
        assert dev._volume == 30

    @pytest.mark.asyncio
    async def test_standalone_sends_vol(self) -> None:
        dev = _FakeDevice()
        await dev.async_set_volume_level(0.42)
        assert "setPlayerCmd:vol:42" in dev.call_linkplay_httpapi.await_args.args[0]
        assert dev._volume == 42

    @pytest.mark.asyncio
    async def test_wifidirect_slave_goes_via_master(self) -> None:
        dev = _FakeDevice(slave_mode=True, wifidirect=True)
        await dev.async_set_volume_level(0.20)
        dev._master.call_linkplay_httpapi.assert_awaited_once()
        cmd = dev._master.call_linkplay_httpapi.await_args.args[0]
        assert cmd == "multiroom:SlaveVolume:5.6.7.8:20"

    @pytest.mark.asyncio
    async def test_snapshot_active_skips_wifidirect_call(self) -> None:
        """During a snapshot the wifidirect slave path no-ops to avoid
        clobbering the saved volume."""
        dev = _FakeDevice(slave_mode=True, wifidirect=True, snapshot=True)
        await dev.async_set_volume_level(0.20)
        dev._master.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_ok_response_warns_but_keeps_old_volume(self) -> None:
        dev = _FakeDevice()
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev.async_set_volume_level(0.99)
        assert dev._volume == 50  # untouched


class TestVolumeUpDown:
    @pytest.mark.asyncio
    async def test_volume_up_clamps_at_100(self) -> None:
        dev = _FakeDevice(volume=98, step=5)
        await dev.async_volume_up()
        assert dev._volume == 100

    @pytest.mark.asyncio
    async def test_volume_up_noop_at_max_when_not_muted(self) -> None:
        dev = _FakeDevice(volume=100)
        await dev.async_volume_up()
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_volume_up_at_max_runs_when_muted(self) -> None:
        dev = _FakeDevice(volume=100)
        dev._muted = True
        await dev.async_volume_up()
        dev.call_linkplay_httpapi.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_volume_down_clamps_at_zero(self) -> None:
        dev = _FakeDevice(volume=2, step=10)
        await dev.async_volume_down()
        assert dev._volume == 0

    @pytest.mark.asyncio
    async def test_volume_down_noop_at_zero(self) -> None:
        dev = _FakeDevice(volume=0)
        await dev.async_volume_down()
        dev.call_linkplay_httpapi.assert_not_awaited()


class TestMute:
    @pytest.mark.asyncio
    async def test_mute_master(self) -> None:
        dev = _FakeDevice(is_master=True)
        await dev.async_mute_volume(True)
        assert "slave_mute:1" in dev.call_linkplay_httpapi.await_args.args[0]
        assert dev._muted is True

    @pytest.mark.asyncio
    async def test_unmute_standalone(self) -> None:
        dev = _FakeDevice()
        dev._muted = True
        await dev.async_mute_volume(False)
        assert "setPlayerCmd:mute:0" in dev.call_linkplay_httpapi.await_args.args[0]
        assert dev._muted is False

    @pytest.mark.asyncio
    async def test_mute_wifidirect_slave_via_master(self) -> None:
        dev = _FakeDevice(slave_mode=True, wifidirect=True)
        await dev.async_mute_volume(True)
        cmd = dev._master.call_linkplay_httpapi.await_args.args[0]
        assert cmd == "multiroom:SlaveVolume:5.6.7.8:1"

    @pytest.mark.asyncio
    async def test_mute_non_ok_leaves_state(self) -> None:
        dev = _FakeDevice()
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev.async_mute_volume(True)
        assert dev._muted is False
