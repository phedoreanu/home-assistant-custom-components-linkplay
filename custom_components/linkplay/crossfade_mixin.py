"""Volume crossfade around source/preset/URL switches.

Linkplay firmware has no native crossfade; switching source kills the
current stream and starts the new one with an audible cut, especially
when the new stream takes a moment to buffer. This mixin softens the
transition by ramping the volume down before the switch and back up
after, all on the master entity. Slaves keep playing because they
receive their audio from the master, so the master's volume ramp
naturally affects the whole group.

Total wall time added per switch is roughly
``fade_out_ms + settle_ms + fade_in_ms`` (default ~900 ms). The user
can shorten or disable the effect via the ``crossfade_ms`` option;
a value of ``0`` short-circuits and runs the switch immediately.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable

_LOGGER = logging.getLogger(__name__)

_FADE_STEPS = 4
_SETTLE_MS = 200


class LinkPlayCrossfadeMixin:
    """Fade-out / switch / fade-in helper used by source/preset/play_media."""

    async def _async_crossfade_switch(self, switch_awaitable: Awaitable[Any]) -> Any:
        """Ramp volume to 0, await ``switch_awaitable``, ramp back up.

        Returns whatever ``switch_awaitable`` resolves to so callers like
        ``async_play_media`` (which may signal failure with ``False``) keep
        the original contract. Short-circuits the fade and just awaits the
        switch when ``_crossfade_ms`` is 0, the device is muted, the
        volume is already 0, the entity is a slave (the master drives
        audio), or the call is part of a snapshot/TTS sequence (those
        already manage their own volume choreography).
        """
        ms = int(getattr(self, "_crossfade_ms", 0) or 0)
        original = int(self._volume)
        if (
            ms <= 0
            or original <= 0
            or self._muted
            or self._slave_mode
            or getattr(self, "_snapshot_active", False)
            or getattr(self, "_playing_tts", False)
        ):
            return await switch_awaitable

        fade_out_ms = ms // 3
        fade_in_ms = ms - fade_out_ms
        step_out = (fade_out_ms / 1000) / _FADE_STEPS
        step_in = (fade_in_ms / 1000) / _FADE_STEPS

        _LOGGER.debug(
            "[%s] crossfade: %d -> 0 (%dms) ; switch ; 0 -> %d (%dms)",
            self.entity_id, original, fade_out_ms, original, fade_in_ms,
        )

        result: Any = None
        try:
            for i in range(1, _FADE_STEPS + 1):
                target = int(round(original * (1 - i / _FADE_STEPS)))
                await self._set_volume_on_device(target, action="crossfade_down")
                if step_out > 0:
                    await asyncio.sleep(step_out)

            result = await switch_awaitable

            if _SETTLE_MS > 0:
                await asyncio.sleep(_SETTLE_MS / 1000)

            for i in range(1, _FADE_STEPS + 1):
                target = int(round(original * (i / _FADE_STEPS)))
                await self._set_volume_on_device(target, action="crossfade_up")
                if step_in > 0:
                    await asyncio.sleep(step_in)
        finally:
            # Ensure the original level is restored exactly even if a
            # step rounded down or the switch raised mid-fade.
            if int(self._volume) != original:
                await self._set_volume_on_device(original, action="crossfade_restore")
        return result
