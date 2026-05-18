"""Tests for the snapshot / restore mixin."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.linkplay.snapshot_mixin import LinkPlaySnapshotMixin


class _FakeDevice(LinkPlaySnapshotMixin):
    def __init__(self) -> None:
        # state
        self.entity_id = "media_player.fake"
        self.name = "fake"
        self._name = "fake"
        self._state = "playing"
        self._slave_mode = False
        self._source = "Webradio"
        self._nometa = False
        self._playing_localfile = False
        self._playing_spotify = False
        self._playing_webplaylist = False
        self._playing_stream = False
        self._playing_mediabrowser = False
        self._playing_tts = False
        self._media_source_uri = None
        self._media_uri = None
        self._media_uri_final = "http://example/stream"
        self._playhead_position = 30
        self._volume = 50
        self._fw_ver = "4.2"
        self._preset_key = 4
        self._player_statdata = {"vol": "60"}

        # snapshot fields populated by the mixin (init to defaults)
        self._snapshot_active = False
        self._snap_source = None
        self._snap_state = "unknown"
        self._snap_nometa = False
        self._snap_playing_mediabrowser = False
        self._snap_media_source_uri = None
        self._snap_playhead_position = 0
        self._snap_seek = False
        self._snap_uri = None
        self._snap_volume = 0
        self._snap_spotify = False
        self._snap_spotify_volumeonly = False

        # collaborators
        self.call_linkplay_httpapi = AsyncMock(return_value="OK")
        self.async_get_status = AsyncMock()
        self.async_preset_snap_via_upnp = AsyncMock()
        self.async_select_source = AsyncMock()
        self.async_play_media = AsyncMock()
        self.async_media_pause = AsyncMock()

    # snapshot_mixin compares fw versions via this helper from LinkPlayDevice.
    @staticmethod
    def _fwvercheck(v):
        return tuple(point.zfill(8) for point in v.split("."))


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """Skip the real sleeps in snapshot/restore so tests don't wait seconds."""
    async def _noop(*_args, **_kwargs):
        return None
    monkeypatch.setattr(
        "custom_components.linkplay.snapshot_mixin.asyncio.sleep", _noop
    )


class TestSnapshot:
    @pytest.mark.asyncio
    async def test_unavailable_short_circuits(self) -> None:
        dev = _FakeDevice()
        dev._state = "unavailable"
        await dev.async_snapshot(switchinput=True)
        assert dev._snapshot_active is False
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_slave_does_not_snapshot(self) -> None:
        dev = _FakeDevice()
        dev._slave_mode = True
        await dev.async_snapshot(switchinput=True)
        assert dev._snapshot_active is False

    @pytest.mark.asyncio
    async def test_idle_just_captures_volume(self) -> None:
        dev = _FakeDevice()
        dev._state = "idle"
        await dev.async_snapshot(switchinput=False)
        assert dev._snap_volume == 50
        assert dev._snapshot_active is True
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_spotify_with_switchinput_saves_only_volume(self) -> None:
        dev = _FakeDevice()
        dev._playing_spotify = True
        await dev.async_snapshot(switchinput=True)
        assert dev._snap_spotify is True
        assert dev._snap_spotify_volumeonly is True
        assert dev._snap_volume == 50
        dev.async_preset_snap_via_upnp.assert_not_called()

    @pytest.mark.asyncio
    async def test_spotify_without_switchinput_persists_preset(self) -> None:
        dev = _FakeDevice()
        dev._playing_spotify = True
        await dev.async_snapshot(switchinput=False)
        dev.async_preset_snap_via_upnp.assert_awaited_once_with("4")
        # setPlayerCmd:stop sent after preset capture
        sent = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert "setPlayerCmd:stop" in sent

    @pytest.mark.asyncio
    async def test_switchinput_on_non_stream_source_polls_volume(self) -> None:
        """Physical-source playback switches to wifi, waits, then re-reads
        the volume from getPlayerStatus."""
        dev = _FakeDevice()
        dev._source = "line-in"
        dev._playing_stream = False
        await dev.async_snapshot(switchinput=True)
        sent = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert sent[0] == "setPlayerCmd:switchmode:wifi"
        assert sent[1] == "setPlayerCmd:stop"
        dev.async_get_status.assert_awaited_once()
        assert dev._snap_volume == 60  # from player_statdata fixture

    @pytest.mark.asyncio
    async def test_switchinput_failed_switch_sets_snap_volume_zero(self) -> None:
        dev = _FakeDevice()
        dev._source = "line-in"
        dev._playing_stream = False
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev.async_snapshot(switchinput=True)
        assert dev._snap_volume == 0
        dev.async_get_status.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_streaming_path_stops_only(self) -> None:
        dev = _FakeDevice()
        dev._playing_stream = True
        await dev.async_snapshot(switchinput=False)
        sent = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert sent == ["setPlayerCmd:stop"]
        assert dev._snap_volume == 50

    @pytest.mark.asyncio
    async def test_network_source_records_uri_for_restore(self) -> None:
        dev = _FakeDevice()
        dev._source = "Network"
        dev._playing_stream = True
        await dev.async_snapshot(switchinput=False)
        assert dev._snap_uri == "http://example/stream"


class TestRestore:
    @pytest.mark.asyncio
    async def test_unavailable_short_circuits(self) -> None:
        dev = _FakeDevice()
        dev._state = "unavailable"
        await dev.async_restore()
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_slave_does_not_restore(self) -> None:
        dev = _FakeDevice()
        dev._slave_mode = True
        await dev.async_restore()
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_volume_restored_and_cleared(self) -> None:
        dev = _FakeDevice()
        dev._snap_volume = 35
        dev._snap_source = "Webradio"
        dev._snap_state = "idle"
        await dev.async_restore()
        first = dev.call_linkplay_httpapi.await_args_list[0].args[0]
        assert first == "setPlayerCmd:vol:35"
        # snap_volume reset after use
        assert dev._snap_volume == 0

    @pytest.mark.asyncio
    async def test_spotify_full_restore_pushes_preset_key(self) -> None:
        dev = _FakeDevice()
        dev._snap_spotify = True
        dev._snap_spotify_volumeonly = False
        dev._snap_source = "Spotify"
        dev._snap_state = "idle"
        await dev.async_restore()
        cmds = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert "MCUKeyShortClick:4" in cmds
        assert dev._snapshot_active is False
        assert dev._snap_spotify is False

    @pytest.mark.asyncio
    async def test_spotify_volume_only_skips_preset(self) -> None:
        dev = _FakeDevice()
        dev._snap_spotify = True
        dev._snap_spotify_volumeonly = True
        dev._snap_source = "Spotify"
        dev._snap_state = "idle"
        await dev.async_restore()
        cmds = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert not any("MCUKeyShortClick" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_non_network_source_calls_select_source(self) -> None:
        dev = _FakeDevice()
        dev._snap_source = "line-in"
        dev._snap_state = "idle"
        await dev.async_restore()
        dev.async_select_source.assert_awaited_once_with("line-in")
        assert dev._snap_source is None
        assert dev._snapshot_active is False

    @pytest.mark.asyncio
    async def test_network_with_uri_replays_via_play_media(self) -> None:
        dev = _FakeDevice()
        dev._snap_source = "Network"
        dev._snap_uri = "http://example/stream.mp3"
        dev._snap_state = "playing"
        await dev.async_restore()
        dev.async_play_media.assert_awaited_once()
        assert dev._snap_uri is None

    @pytest.mark.asyncio
    async def test_seek_after_restore_when_position_known(self) -> None:
        dev = _FakeDevice()
        dev._snap_source = "Network"
        dev._snap_uri = "http://example/stream.mp3"
        dev._snap_state = "paused"
        dev._snap_seek = True
        dev._snap_playhead_position = 42
        await dev.async_restore()
        cmds = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert "setPlayerCmd:seek:42" in cmds
        # Paused restores also call media_pause to finish in the right state
        dev.async_media_pause.assert_awaited_once()
