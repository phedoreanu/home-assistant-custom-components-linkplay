"""Regression tests for the poll cycle (async_update).

Most of async_update is wrapped around the live device-status response,
so these tests target the discrete branches that can be exercised
without spinning up a full status-response fixture:

- multiroom master status polling (extracted method)
- slave-mode and master-ref recovery (already in test_multiroom_state)
- unjoin-wait window
- protocol auto-detect failure path
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.linkplay.media_player import LinkPlayDevice


def _make_device(name: str) -> LinkPlayDevice:
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
    dev.hass = hass
    dev.async_write_ha_state = MagicMock()
    return dev


def _share_entities(*devices: LinkPlayDevice) -> None:
    """Make all devices visible to each other via hass.data[DOMAIN].entities."""
    entities = list(devices)
    for d in entities:
        d.hass.data["linkplay"].entities = entities


class TestPollMultiroomMasterStatus:
    """Cover the extracted _async_poll_multiroom_master_status method."""

    @pytest.mark.asyncio
    async def test_slave_short_circuits_without_http(self) -> None:
        slave = _make_device("slave")
        slave._slave_mode = True
        slave.call_linkplay_httpapi = AsyncMock(
            side_effect=AssertionError("slaves must not query getSlaveList")
        )

        result = await slave._async_poll_multiroom_master_status()

        assert result is True

    @pytest.mark.asyncio
    async def test_api_failure_clears_master_state(self) -> None:
        master = _make_device("master")
        master._is_master = True
        master._slave_list = [{"name": "x"}]
        master._multiroom_group = ["media_player.master", "media_player.slave"]
        master.call_linkplay_httpapi = AsyncMock(return_value=None)

        await master._async_poll_multiroom_master_status()

        assert master._is_master is False
        assert master._slave_list is None
        assert master._multiroom_group == []

    @pytest.mark.asyncio
    async def test_zero_slaves_resets_group_and_drops_master_flag(self) -> None:
        master = _make_device("master")
        master._is_master = True
        master._multiroom_group = ["media_player.master"]
        master.call_linkplay_httpapi = AsyncMock(return_value={"slaves": 0, "slave_list": []})

        await master._async_poll_multiroom_master_status()

        assert master._is_master is False
        assert master._multiroom_group == []
        assert master._slave_list == []

    @pytest.mark.asyncio
    async def test_master_populates_group_and_pushes_to_slaves(self) -> None:
        master = _make_device("master")
        slave_kitchen = _make_device("kitchen")
        slave_office = _make_device("office")
        _share_entities(master, slave_kitchen, slave_office)

        # The integration matches slaves by their HA-side _name (the friendly
        # name HA was given), which is what the device firmware also reports
        # in the multiroom protocol.
        slave_kitchen._name = "kitchen"
        slave_office._name = "office"

        master.call_linkplay_httpapi = AsyncMock(
            return_value={
                "slaves": 2,
                "slave_list": [
                    {"name": "kitchen", "volume": 30, "ip": "10.0.0.2"},
                    {"name": "office", "volume": 50, "ip": "10.0.0.3"},
                ],
            }
        )

        await master._async_poll_multiroom_master_status()

        assert master._is_master is True
        assert master._multiroom_group == [
            "media_player.master",
            "media_player.kitchen",
            "media_player.office",
        ]
        assert slave_kitchen._slave_mode is True
        assert slave_office._slave_mode is True
        assert slave_kitchen._master is master
        assert slave_kitchen._multiroom_group == master._multiroom_group
        assert slave_office._multiroom_group == master._multiroom_group

    @pytest.mark.asyncio
    async def test_unmatched_slave_name_is_silently_skipped(self) -> None:
        """When the device reports a slave name that no HA entity matches,
        the master's group should only contain itself."""
        master = _make_device("master")
        stranger = _make_device("stranger")
        _share_entities(master, stranger)
        stranger._name = "actually_different_name"

        master.call_linkplay_httpapi = AsyncMock(
            return_value={
                "slaves": 1,
                "slave_list": [{"name": "kitchen", "volume": 30, "ip": "10.0.0.2"}],
            }
        )

        await master._async_poll_multiroom_master_status()

        assert master._multiroom_group == ["media_player.master"]
        assert stranger._slave_mode is False


class TestUnjoinWaitWindow:
    """async_update returns early while _multiroom_unjoinat is within the
    wait window — the device firmware needs time after Ungroup before its
    status response is reliable again.
    """

    @pytest.mark.asyncio
    async def test_within_wait_window_returns_idle_state(self) -> None:
        from homeassistant.util.dt import utcnow

        dev = _make_device("device")
        dev._multiroom_unjoinat = utcnow()  # just now
        dev._multiroom_wifidirect = False  # router mode -> 3s wait window
        dev.call_linkplay_httpapi = AsyncMock(
            side_effect=AssertionError("update should short-circuit in wait window")
        )

        result = await dev.async_update()

        assert result is True
        assert dev._source is None
        assert dev._media_title is None
        assert dev._media_artist is None
        assert dev._state == "idle"

    @pytest.mark.asyncio
    async def test_outside_wait_window_restores_previous_source(self) -> None:
        from homeassistant.util.dt import utcnow

        dev = _make_device("device")
        dev._multiroom_unjoinat = utcnow() - timedelta(minutes=5)  # long ago
        dev._multiroom_wifidirect = False
        dev._multiroom_prevsrc = "Line-in"
        dev.async_select_source = AsyncMock()

        result = await dev.async_update()

        assert result is True
        assert dev._multiroom_unjoinat is None
        assert dev._multiroom_prevsrc is None
        dev.async_select_source.assert_awaited_once_with("Line-in")


def _idle_payload():
    return {
        "type": "0", "mode": "0", "status": "stop",
        "vol": "30", "mute": "0", "eq": "0", "loop": "4",
        "totlen": "0", "curpos": "0", "uri": "",
        "Title": "", "Artist": "", "Album": "",
    }


def _stream_payload(**overrides):
    base = {
        "type": "0", "mode": "10", "status": "play",
        "vol": "55", "mute": "0", "eq": "2", "loop": "0",
        "totlen": "0", "curpos": "0",
        # hex("http://stream/mp3")
        "uri": "687474703a2f2f73747265616d2f6d7033",
        "Title": "Stream Title", "Artist": "", "Album": "",
    }
    base.update(overrides)
    return base


def _localfile_payload():
    return {
        "type": "0", "mode": "11", "status": "play",
        "vol": "50", "mute": "0", "eq": "1", "loop": "2",
        "totlen": "180000", "curpos": "30000", "uri": "",
        "Title": "", "Artist": "", "Album": "",
    }


def _spotify_payload():
    return {
        "type": "0", "mode": "31", "status": "play",
        "vol": "70", "mute": "0", "eq": "0", "loop": "0",
        "totlen": "240000", "curpos": "12000", "uri": "",
        "Title": "", "Artist": "", "Album": "",
    }


def _device_status_payload(**overrides):
    base = {
        "WifiChannel": "6", "ssid": "my-net", "uuid": "DEVICE-UUID",
        "DeviceName": "Renamed", "firmware": "4.6.328",
        "mcu_ver": "1.2", "preset_key": "10",
    }
    base.update(overrides)
    return base


class TestPlayerStatusBranches:
    """End-to-end ``async_update`` with seeded ``_player_statdata`` payloads."""

    def _prep(self, dev, payload):
        async def _stub(*a, **kw):
            dev._player_statdata = payload
        dev.async_get_status = AsyncMock(side_effect=_stub)
        dev.async_update_from_somafm = AsyncMock(return_value=False)
        dev.async_get_playerstatus_metadata = AsyncMock(return_value=True)
        dev.async_update_via_upnp = AsyncMock()
        dev.async_get_icecast_meta = AsyncMock(return_value=False)
        dev.async_update_lastfm = AsyncMock(return_value=False)
        dev.async_get_local_mediasource_metadata_from_path = AsyncMock(
            return_value=False
        )
        dev.async_is_playing_new_track = AsyncMock(return_value=False)
        dev._factory = MagicMock()
        dev._factory.async_create_device = AsyncMock(return_value=MagicMock())
        dev.call_linkplay_httpapi = AsyncMock(return_value="OK")

    @pytest.mark.asyncio
    async def test_idle_payload_sets_state_idle(self, monkeypatch) -> None:
        from homeassistant.util.dt import utcnow

        dev = _make_device("dev")
        monkeypatch.setattr(
            "custom_components.linkplay.media_player.AUTOIDLE_STATE_TIMEOUT",
            timedelta(seconds=0),
        )
        dev._first_update = False
        dev._idletime_updated_at = utcnow() - timedelta(minutes=1)
        self._prep(dev, _idle_payload())
        await dev.async_update()
        assert dev._state == "idle"
        assert dev._volume == "30"

    @pytest.mark.asyncio
    async def test_playing_stream_payload(self) -> None:
        dev = _make_device("dev")
        dev._first_update = False
        self._prep(dev, _stream_payload())
        await dev.async_update()
        assert dev._state == "playing"
        assert dev._playing_stream is True
        assert dev._media_uri_final.startswith("http://stream/")

    @pytest.mark.asyncio
    async def test_poll_within_volume_grace_keeps_commanded_volume(self) -> None:
        """v4.5.15: a poll response in flight while the user changed the
        volume carries the pre-change value; within VOLUME_CMD_GRACE the
        locally commanded volume wins, so a preset switch that snapshots
        ``_volume`` right then doesn't re-apply the OLD group volume."""
        from homeassistant.util.dt import utcnow

        dev = _make_device("dev")
        dev._first_update = False
        self._prep(dev, _stream_payload())  # payload reports vol "55"
        dev._volume = 20
        dev._volume_cmd_at = utcnow()
        await dev.async_update()
        assert dev._volume == 20

    @pytest.mark.asyncio
    async def test_poll_after_volume_grace_updates_volume(self) -> None:
        from homeassistant.util.dt import utcnow

        dev = _make_device("dev")
        dev._first_update = False
        self._prep(dev, _stream_payload())
        dev._volume = 20
        dev._volume_cmd_at = utcnow() - timedelta(seconds=10)
        await dev.async_update()
        assert dev._volume == "55"

    @pytest.mark.asyncio
    async def test_localfile_paused_payload(self) -> None:
        dev = _make_device("dev")
        dev._first_update = False
        payload = _localfile_payload()
        payload["status"] = "pause"
        self._prep(dev, payload)
        await dev.async_update()
        assert dev._state == "paused"
        assert dev._duration == 180
        assert dev._playhead_position == 30

    @pytest.mark.asyncio
    async def test_spotify_payload_marks_playing_spotify(self) -> None:
        dev = _make_device("dev")
        dev._first_update = False
        self._prep(dev, _spotify_payload())
        await dev.async_update()
        assert dev._playing_spotify is True
        assert dev._state == "playing"

    @pytest.mark.asyncio
    async def test_first_update_populates_device_info(self) -> None:
        dev = _make_device("dev")
        device_status = _device_status_payload()

        async def _httpapi(cmd, *a, **kw):
            if "getStatus" in cmd:
                return device_status
            return "OK"

        self._prep(dev, _idle_payload())
        dev.call_linkplay_httpapi = AsyncMock(side_effect=_httpapi)
        await dev.async_update()
        assert dev._uuid == "DEVICE-UUID"
        assert dev._fw_ver == "4.6.328"
        assert dev._preset_key == 10
        assert dev._first_update is False

    @pytest.mark.asyncio
    async def test_first_update_with_missing_preset_key_defaults_to_4(
        self,
    ) -> None:
        dev = _make_device("dev")
        ds = _device_status_payload()
        ds.pop("preset_key")

        async def _httpapi(cmd, *a, **kw):
            if "getStatus" in cmd:
                return ds
            return "OK"

        self._prep(dev, _idle_payload())
        dev.call_linkplay_httpapi = AsyncMock(side_effect=_httpapi)
        await dev.async_update()
        assert dev._preset_key == 4

    @pytest.mark.asyncio
    async def test_no_status_returns_true_without_state_change(self) -> None:
        dev = _make_device("dev")

        async def _stub(*a, **kw):
            dev._player_statdata = None

        dev.async_get_status = AsyncMock(side_effect=_stub)
        result = await dev.async_update()
        assert result is True


class TestProtocolAutoDetectFailure:
    """If _protocol is None and both https and http probes fail, async_update
    must return False without raising."""

    @pytest.mark.asyncio
    async def test_both_protocols_fail(self) -> None:
        dev = _make_device("device")
        dev._protocol = None
        dev.call_linkplay_httpapi = AsyncMock(return_value=None)

        result = await dev.async_update()

        assert result is False
        assert dev._protocol is None

    @pytest.mark.asyncio
    async def test_https_succeeds(self) -> None:
        dev = _make_device("device")
        dev._protocol = None

        async def fake_call(cmd, jsn, protocol=None):
            if protocol == "https":
                return {"ok": True}
            return None

        dev.call_linkplay_httpapi = AsyncMock(side_effect=fake_call)
        # Short-circuit the rest of async_update by leaving _player_statdata
        # at its sentinel; the function will fall through quickly.
        dev.async_get_status = AsyncMock()
        dev._player_statdata = None

        await dev.async_update()

        assert dev._protocol == "https"
