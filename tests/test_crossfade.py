"""Tests for the source/preset/play_media volume crossfade helper."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.linkplay.crossfade_mixin import LinkPlayCrossfadeMixin


class _FakeDevice(LinkPlayCrossfadeMixin):
    """Bare-bones host for the mixin so the fade logic can be exercised
    without spinning up a full LinkPlayDevice."""

    def __init__(self, *, volume: int = 50, ms: int = 300) -> None:
        self.entity_id = "media_player.test"
        self._volume = volume
        self._crossfade_ms = ms
        self._muted = False
        self._slave_mode = False
        self._snapshot_active = False
        self._playing_tts = False
        self._volume_calls: list[tuple[int, str]] = []

    async def _set_volume_on_device(self, volume: int, *, action: str) -> None:
        self._volume_calls.append((volume, action))
        self._volume = volume


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Skip the inter-step sleeps so the test suite stays fast."""
    async def _noop(*_args, **_kwargs):
        return None
    monkeypatch.setattr("custom_components.linkplay.crossfade_mixin.asyncio.sleep", _noop)


class TestShortCircuit:
    @pytest.mark.asyncio
    async def test_disabled_when_ms_zero(self) -> None:
        dev = _FakeDevice(ms=0)
        switch = AsyncMock(return_value="ok")
        result = await dev._async_crossfade_switch(switch())
        assert result == "ok"
        assert dev._volume_calls == []
        assert dev._volume == 50

    @pytest.mark.asyncio
    async def test_disabled_when_volume_zero(self) -> None:
        dev = _FakeDevice(volume=0)
        switch = AsyncMock(return_value=None)
        await dev._async_crossfade_switch(switch())
        assert dev._volume_calls == []

    @pytest.mark.asyncio
    async def test_disabled_when_muted(self) -> None:
        dev = _FakeDevice()
        dev._muted = True
        switch = AsyncMock(return_value=None)
        await dev._async_crossfade_switch(switch())
        assert dev._volume_calls == []

    @pytest.mark.asyncio
    async def test_disabled_for_slave(self) -> None:
        dev = _FakeDevice()
        dev._slave_mode = True
        switch = AsyncMock(return_value=None)
        await dev._async_crossfade_switch(switch())
        assert dev._volume_calls == []

    @pytest.mark.asyncio
    async def test_disabled_during_snapshot_or_tts(self) -> None:
        dev = _FakeDevice()
        dev._snapshot_active = True
        switch = AsyncMock(return_value=None)
        await dev._async_crossfade_switch(switch())
        assert dev._volume_calls == []

        dev2 = _FakeDevice()
        dev2._playing_tts = True
        await dev2._async_crossfade_switch(switch())
        assert dev2._volume_calls == []


class TestFade:
    @pytest.mark.asyncio
    async def test_fade_down_switch_fade_up_restores_volume(self) -> None:
        dev = _FakeDevice(volume=80, ms=300)
        called_at_volume: list[int] = []

        async def _switch() -> str:
            called_at_volume.append(dev._volume)
            return "switched"

        result = await dev._async_crossfade_switch(_switch())

        assert result == "switched"
        # Switch fires only after the down-ramp lands at zero.
        assert called_at_volume == [0]
        # Final volume is restored to the original.
        assert dev._volume == 80
        # 4 down + 4 up + (optional) restore: assert direction not exact count.
        down = [v for v, a in dev._volume_calls if a == "crossfade_down"]
        up = [v for v, a in dev._volume_calls if a == "crossfade_up"]
        assert down == sorted(down, reverse=True)
        assert down[-1] == 0
        assert up == sorted(up)
        assert up[-1] == 80

    @pytest.mark.asyncio
    async def test_switch_raises_volume_still_restored(self) -> None:
        dev = _FakeDevice(volume=60, ms=300)

        async def _switch() -> None:
            raise RuntimeError("network blip")

        with pytest.raises(RuntimeError, match="network blip"):
            await dev._async_crossfade_switch(_switch())

        # Even though the switch raised mid-cycle, the finally clause
        # restored the original volume rather than leaving the speaker
        # silent.
        assert dev._volume == 60
