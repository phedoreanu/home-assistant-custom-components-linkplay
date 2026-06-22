"""Smoke tests for the setters_mixin attribute pushers."""

from __future__ import annotations

import pytest

from custom_components.linkplay.setters_mixin import LinkPlaySettersMixin


class _Stub(LinkPlaySettersMixin):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "attr", "value"),
    [
        ("async_set_media_title", "_media_title", "T"),
        ("async_set_media_artist", "_media_artist", "A"),
        ("async_set_volume", "_volume", 42),
        ("async_set_muted", "_muted", True),
        ("async_set_state", "_state", "playing"),
        ("async_set_playhead_position", "_playhead_position", 30),
        ("async_set_duration", "_duration", 240),
        ("async_set_position_updated_at", "_position_updated_at", "ts"),
        ("async_set_source", "_source", "Spotify"),
        ("async_set_sound_mode", "_sound_mode", "Jazz"),
        ("async_set_media_image_url", "_media_image_url", "u"),
        ("async_set_media_uri", "_media_uri", "u"),
        ("async_set_features", "_features", 0b101),
        ("async_set_wait_for_mcu", "_wait_for_mcu", 1.5),
        ("async_set_unav_throttle", "_unav_throttle", True),
    ],
)
async def test_setter_writes_attribute(method: str, attr: str, value) -> None:
    stub = _Stub()
    await getattr(stub, method)(value)
    assert getattr(stub, attr) == value
