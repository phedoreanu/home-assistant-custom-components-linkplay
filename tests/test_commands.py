"""Tests for the raw-command dispatcher mixin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.linkplay.commands_mixin import LinkPlayCommandsMixin


class _FakeDevice(LinkPlayCommandsMixin):
    def __init__(self) -> None:
        self.entity_id = "media_player.fake"
        self._name = "fake"
        self._unav_throttle = True
        self._first_update = False
        self.call_linkplay_httpapi = AsyncMock(return_value="OK")
        self.call_linkplay_tcpuart = AsyncMock(return_value="MCU+OK")
        self.hass = MagicMock()


class TestCommandDispatch:
    @pytest.mark.asyncio
    async def test_mcu_routes_to_tcpuart(self) -> None:
        dev = _FakeDevice()
        await dev.async_execute_command("MCU+PAS+RAKOIT:LED:1&", notif=False)
        dev.call_linkplay_tcpuart.assert_awaited_once_with("MCU+PAS+RAKOIT:LED:1&")
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prompt_enable_disable(self) -> None:
        dev = _FakeDevice()
        await dev.async_execute_command("PromptEnable", notif=False)
        await dev.async_execute_command("PromptDisable", notif=False)
        cmds = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert cmds == ["PromptEnable", "PromptDisable"]

    @pytest.mark.asyncio
    async def test_router_multiroom_enable(self) -> None:
        dev = _FakeDevice()
        await dev.async_execute_command("RouterMultiroomEnable", notif=False)
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setMultiroomLogic:1"

    @pytest.mark.asyncio
    async def test_random_wifi_key_generates_and_sends(self) -> None:
        dev = _FakeDevice()
        await dev.async_execute_command("SetRandomWifiKey", notif=False)
        cmd = dev.call_linkplay_httpapi.await_args.args[0]
        assert cmd.startswith("setNetwork:1:")
        assert len(cmd.removeprefix("setNetwork:1:")) == 16

    @pytest.mark.asyncio
    async def test_set_ap_ssid_with_name(self) -> None:
        dev = _FakeDevice()
        await dev.async_execute_command("SetApSSIDName: NewWifi", notif=False)
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setSSID:NewWifi"

    @pytest.mark.asyncio
    async def test_set_ap_ssid_empty_returns_help_text(self) -> None:
        dev = _FakeDevice()
        with patch(
            "custom_components.linkplay.commands_mixin.persistent_notification.async_create"
        ) as notify:
            await dev.async_execute_command("SetApSSIDName: ", notif=True)
        dev.call_linkplay_httpapi.assert_not_awaited()
        notif_body = notify.call_args.args[1]
        assert "SSID not specified" in notif_body

    @pytest.mark.asyncio
    async def test_write_device_name_updates_self_name(self) -> None:
        dev = _FakeDevice()
        await dev.async_execute_command("WriteDeviceNameToUnit: Kitchen Speaker", notif=False)
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setDeviceName:Kitchen Speaker"
        assert dev._name == "Kitchen Speaker"

    @pytest.mark.asyncio
    async def test_write_device_name_empty_does_not_call_api(self) -> None:
        dev = _FakeDevice()
        await dev.async_execute_command("WriteDeviceNameToUnit:", notif=False)
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_time_sync_sends_current_time(self) -> None:
        dev = _FakeDevice()
        await dev.async_execute_command("TimeSync", notif=False)
        cmd = dev.call_linkplay_httpapi.await_args.args[0]
        assert cmd.startswith("timeSync:") and len(cmd) > len("timeSync:")

    @pytest.mark.asyncio
    async def test_rescan_resets_flags_only(self) -> None:
        dev = _FakeDevice()
        dev._first_update = False
        dev._unav_throttle = True
        await dev.async_execute_command("Rescan", notif=False)
        assert dev._unav_throttle is False
        assert dev._first_update is True
        dev.call_linkplay_httpapi.assert_not_awaited()
        dev.call_linkplay_tcpuart.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_command_only_schedules(self) -> None:
        dev = _FakeDevice()
        await dev.async_execute_command("Update", notif=False)
        dev.call_linkplay_httpapi.assert_not_awaited()
        dev.call_linkplay_tcpuart.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reboot_and_restore_to_default(self) -> None:
        dev = _FakeDevice()
        await dev.async_execute_command("reboot", notif=False)
        await dev.async_execute_command("restoreToDefault", notif=False)
        cmds = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert cmds == ["reboot;", "restoreToDefault"]

    @pytest.mark.asyncio
    async def test_unknown_command_warns(self) -> None:
        dev = _FakeDevice()
        with patch(
            "custom_components.linkplay.commands_mixin.persistent_notification.async_create"
        ) as notify:
            await dev.async_execute_command("DanceParty", notif=True)
        dev.call_linkplay_httpapi.assert_not_awaited()
        notif_body = notify.call_args.args[1]
        assert "No such command" in notif_body

    @pytest.mark.asyncio
    async def test_notify_false_skips_persistent_notification(self) -> None:
        dev = _FakeDevice()
        with patch(
            "custom_components.linkplay.commands_mixin.persistent_notification.async_create"
        ) as notify:
            await dev.async_execute_command("PromptEnable", notif=False)
        notify.assert_not_called()
