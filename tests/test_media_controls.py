"""Tests for the transport-control mixin (play/pause/stop/seek/next/prev)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.linkplay.media_controls_mixin import LinkPlayMediaControlsMixin


class _FakeDevice(LinkPlayMediaControlsMixin):
    def __init__(self) -> None:
        self.entity_id = "media_player.fake"
        self.name = "fake"
        self._state = "playing"
        self._slave_mode = False
        self._slave_list = None
        self._master = MagicMock()
        for attr in (
            "async_media_next_track",
            "async_media_previous_track",
            "async_media_play",
            "async_media_pause",
            "async_media_stop",
            "async_media_seek",
        ):
            setattr(self._master, attr, AsyncMock())
        self._prev_source = None
        self._source = None
        self._source_list = {"line-in": "Line In", "http://radio/": "Web Radio"}
        self._playing_stream = False
        self._playing_spotify = False
        self._playing_liveinput = False
        self._playing_mediabrowser = False
        self._spotify_paused_at = None
        self._playhead_position = 0
        self._duration = 100
        self._position_updated_at = None
        self._idletime_updated_at = None
        self._trackc = "x"
        self._wait_for_mcu = 0
        self._unav_throttle = True
        self._fw_ver = "4.2"
        self._media_title = "t"
        self._media_artist = "a"
        self._media_album = "a"
        self._media_image_url = "i"
        self._media_uri = "u"
        self._media_uri_final = "u"
        self._media_source_uri = "u"
        self._icecast_name = "n"
        self._nometa = True
        self.call_linkplay_httpapi = AsyncMock(return_value="OK")

    @staticmethod
    def _fwvercheck(v):
        return tuple(point.zfill(8) for point in v.split("."))

    @property
    def media_position_updated_at(self):
        return self._position_updated_at


class TestSkipTrack:
    @pytest.mark.asyncio
    async def test_next_routes_to_master_when_slave(self) -> None:
        dev = _FakeDevice()
        dev._slave_mode = True
        await dev.async_media_next_track()
        dev._master.async_media_next_track.assert_awaited_once()
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_previous_routes_to_master_when_slave(self) -> None:
        dev = _FakeDevice()
        dev._slave_mode = True
        await dev.async_media_previous_track()
        dev._master.async_media_previous_track.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_next_sends_command(self) -> None:
        dev = _FakeDevice()
        await dev.async_media_next_track()
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:next"
        assert dev._playhead_position == 0
        assert dev._duration == 0
        assert dev._trackc is None

    @pytest.mark.asyncio
    async def test_next_warns_on_non_ok(self) -> None:
        dev = _FakeDevice()
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev.async_media_next_track()  # no exception, just warning


class TestPlay:
    @pytest.mark.asyncio
    async def test_resume_from_paused(self) -> None:
        dev = _FakeDevice()
        dev._state = "paused"
        await dev.async_media_play()
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:resume"
        assert dev._state == "playing"

    @pytest.mark.asyncio
    async def test_play_with_no_prev_source(self) -> None:
        dev = _FakeDevice()
        dev._state = "idle"
        await dev.async_media_play()
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:play"

    @pytest.mark.asyncio
    async def test_slave_routes_to_master(self) -> None:
        dev = _FakeDevice()
        dev._slave_mode = True
        await dev.async_media_play()
        dev._master.async_media_play.assert_awaited_once()


class TestPause:
    @pytest.mark.asyncio
    async def test_paused_state_set_on_ok(self) -> None:
        dev = _FakeDevice()
        await dev.async_media_pause()
        assert dev._state == "paused"
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:pause"

    @pytest.mark.asyncio
    async def test_live_stream_pause_redirects_to_stop(self) -> None:
        dev = _FakeDevice()
        dev._playing_stream = True
        dev._playing_mediabrowser = False
        await dev.async_media_pause()
        cmds = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert "setPlayerCmd:stop" in cmds
        assert "setPlayerCmd:pause" not in cmds
        assert dev._state == "idle"

    @pytest.mark.asyncio
    async def test_slave_routes_to_master(self) -> None:
        dev = _FakeDevice()
        dev._slave_mode = True
        await dev.async_media_pause()
        dev._master.async_media_pause.assert_awaited_once()


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_clears_state(self) -> None:
        dev = _FakeDevice()
        await dev.async_media_stop()
        assert dev._state == "idle"
        assert dev._media_title is None
        assert dev._media_artist is None
        assert dev._media_uri is None
        assert dev._source is None
        assert dev._playing_stream is False

    @pytest.mark.asyncio
    async def test_stop_routes_via_master_when_slave(self) -> None:
        dev = _FakeDevice()
        dev._slave_mode = True
        await dev.async_media_stop()
        dev._master.async_media_stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_spotify_path_switches_to_wifi(self) -> None:
        dev = _FakeDevice()
        dev._playing_spotify = True
        await dev.async_media_stop()
        cmds = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert "setPlayerCmd:switchmode:wifi" in cmds


class TestPlayWithPrevSource:
    @pytest.mark.asyncio
    async def test_prev_source_unmapped_returns(self) -> None:
        dev = _FakeDevice()
        dev._state = "idle"
        dev._prev_source = "Garbage Source"
        await dev.async_media_play()
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prev_source_non_http_sends_play(self) -> None:
        dev = _FakeDevice()
        dev._state = "idle"
        dev._prev_source = "Line In"
        await dev.async_media_play()
        cmd = dev.call_linkplay_httpapi.await_args.args[0]
        assert cmd == "setPlayerCmd:play"

    @pytest.mark.asyncio
    async def test_play_non_ok_warns_and_keeps_state(self) -> None:
        dev = _FakeDevice()
        dev._state = "idle"
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev.async_media_play()
        assert dev._state == "idle"


class TestPauseFailure:
    @pytest.mark.asyncio
    async def test_pause_non_ok_keeps_state(self) -> None:
        dev = _FakeDevice()
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev.async_media_pause()
        assert dev._state == "playing"

    @pytest.mark.asyncio
    async def test_pause_during_spotify_records_paused_at(self) -> None:
        dev = _FakeDevice()
        dev._playing_spotify = True
        await dev.async_media_pause()
        assert dev._spotify_paused_at is not None


class TestStopFailure:
    @pytest.mark.asyncio
    async def test_stop_non_ok_does_not_clear_state(self) -> None:
        dev = _FakeDevice()
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev.async_media_stop()
        assert dev._state == "playing"

    @pytest.mark.asyncio
    async def test_stop_slow_fw_stream_pauses_first(self) -> None:
        dev = _FakeDevice()
        dev._fw_ver = "4.7"
        dev._playing_stream = True
        await dev.async_media_stop()
        cmds = [c.args[0] for c in dev.call_linkplay_httpapi.await_args_list]
        assert cmds[0] == "setPlayerCmd:pause"
        assert "setPlayerCmd:switchmode:wifi" in cmds


class TestSeek:
    @pytest.mark.asyncio
    async def test_seek_failure_does_not_crash(self) -> None:
        dev = _FakeDevice()
        dev.call_linkplay_httpapi = AsyncMock(return_value="FAIL")
        await dev.async_media_seek(10)  # warning logged, no exception

    @pytest.mark.asyncio
    async def test_in_range_position_sends_seek(self) -> None:
        dev = _FakeDevice()
        await dev.async_media_seek(42)
        assert dev.call_linkplay_httpapi.await_args.args[0] == "setPlayerCmd:seek:42"

    @pytest.mark.asyncio
    async def test_out_of_range_is_ignored(self) -> None:
        dev = _FakeDevice()
        await dev.async_media_seek(9999)
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_zero_duration_is_ignored(self) -> None:
        dev = _FakeDevice()
        dev._duration = 0
        await dev.async_media_seek(0)
        dev.call_linkplay_httpapi.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_slave_routes_to_master(self) -> None:
        dev = _FakeDevice()
        dev._slave_mode = True
        await dev.async_media_seek(10)
        dev._master.async_media_seek.assert_awaited_once_with(10)


class TestClearPlaylist:
    @pytest.mark.asyncio
    async def test_clear_is_noop(self) -> None:
        dev = _FakeDevice()
        await dev.async_clear_playlist()
        dev.call_linkplay_httpapi.assert_not_awaited()
