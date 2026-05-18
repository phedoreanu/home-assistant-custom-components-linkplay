"""Smoke tests for LinkPlayDevice property accessors.

Instantiating the real entity exercises a large chunk of media_player.py
that the per-mixin tests don't touch (constructor, properties, simple
setters, supported_features branches, extra_state_attributes).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.const import (
    STATE_IDLE,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
)


def _make_device(name: str = "device"):
    """Build a real LinkPlayDevice with UPnP factory mocked out."""
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
            icecast_metadata="StationName",
            multiroom_wifidirect=False,
            led_off=False,
            volume_step=5,
            lastfm_api_key=None,
            uuid="uuid-1234",
            state=STATE_IDLE,
        )
    dev.entity_id = f"media_player.{name}"
    dev.hass = hass
    return dev


class TestConstructorDefaults:
    def test_basic_init_state(self) -> None:
        dev = _make_device("kitchen")
        assert dev._name == "kitchen"
        assert dev._host == "1.2.3.4"
        assert dev._protocol == "http"
        assert dev._volume == 0
        assert dev._is_master is False
        assert dev._slave_mode is False
        assert dev._uuid == "uuid-1234"
        # crossfade default plumbed through:
        assert dev._crossfade_ms == 300


class TestNameAndIcon:
    def test_name_default(self) -> None:
        dev = _make_device()
        assert dev.name == "device"

    def test_slave_name_appends_master(self) -> None:
        master = _make_device("kitchen")
        master._is_master = True
        slave = _make_device("bath")
        slave._slave_mode = True
        slave.hass.data["linkplay"].entities = [master, slave]
        assert slave.name == "bath [kitchen]"

    def test_icon_states(self) -> None:
        dev = _make_device()
        from custom_components.linkplay.media_player import (
            ICON_BLUETOOTH,
            ICON_DEFAULT,
            ICON_MULTIROOM,
            ICON_MUTED,
            ICON_PLAYING,
            ICON_PUSHSTREAM,
            ICON_TTS,
        )

        dev._state = STATE_IDLE
        assert dev.icon == ICON_DEFAULT

        dev._state = STATE_PAUSED
        assert dev.icon == ICON_DEFAULT

        dev._state = STATE_UNAVAILABLE
        assert dev.icon == ICON_DEFAULT

        dev._state = STATE_PLAYING
        dev._playing_tts = True
        assert dev.icon == ICON_TTS

        dev._playing_tts = False
        dev._muted = True
        assert dev.icon == ICON_MUTED

        dev._muted = False
        dev._is_master = True
        assert dev.icon == ICON_MULTIROOM

        dev._is_master = False
        dev._source = "Bluetooth"
        assert dev.icon == ICON_BLUETOOTH

        dev._source = "Spotify"
        assert dev.icon == ICON_PUSHSTREAM

        dev._source = "Other"
        assert dev.icon == ICON_PLAYING


class TestBasicAccessors:
    def test_volume_level_scales_to_unit(self) -> None:
        dev = _make_device()
        dev._volume = 73
        assert abs(dev.volume_level - 0.73) < 1e-9

    def test_state_returns_attribute(self) -> None:
        dev = _make_device()
        dev._state = STATE_PLAYING
        assert dev.state == STATE_PLAYING

    def test_is_volume_muted(self) -> None:
        dev = _make_device()
        assert dev.is_volume_muted is False
        dev._muted = True
        assert dev.is_volume_muted is True

    def test_source_returns_none_for_internal_values(self) -> None:
        dev = _make_device()
        for val in ("Idle", "Network"):
            dev._source = val
            assert dev.source is None
        dev._source = "Spotify"
        assert dev.source == "Spotify"

    def test_source_list_strips_wifi(self) -> None:
        dev = _make_device()
        dev._source_list = {"wifi": "WiFi", "bluetooth": "Bluetooth"}
        assert "WiFi" not in dev.source_list
        assert "Bluetooth" in dev.source_list

    def test_sound_mode_list_sorted(self) -> None:
        dev = _make_device()
        modes = dev.sound_mode_list
        assert modes == sorted(modes)

    def test_media_title_artist_album_image(self) -> None:
        dev = _make_device()
        dev._media_title = "T"
        dev._media_artist = "A"
        dev._media_album = "B"
        dev._media_image_url = "u"
        assert dev.media_title == "T"
        assert dev.media_artist == "A"
        assert dev.media_album_name == "B"
        assert dev.media_image_url == "u"

    def test_host_and_unique_id(self) -> None:
        dev = _make_device()
        assert dev.host == "1.2.3.4"
        assert dev.unique_id == "linkplay_media_uuid-1234"

    def test_unique_id_none_without_uuid(self) -> None:
        dev = _make_device()
        dev._uuid = ""
        assert dev.unique_id is None

    def test_track_count_zero_when_no_queue(self) -> None:
        dev = _make_device()
        assert dev.track_count == 0


class TestPlayheadProperties:
    def test_media_position_none_when_unavailable(self) -> None:
        dev = _make_device()
        dev._state = STATE_UNAVAILABLE
        dev._playing_localfile = True
        assert dev.media_position is None
        assert dev.media_duration is None

    def test_media_position_returned_for_localfile(self) -> None:
        dev = _make_device()
        dev._playing_localfile = True
        dev._state = STATE_PLAYING
        dev._playhead_position = 42
        dev._duration = 200
        assert dev.media_position == 42
        assert dev.media_duration == 200

    def test_media_position_updated_at_only_when_playing(self) -> None:
        dev = _make_device()
        from datetime import datetime, timezone
        dev._position_updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        dev._state = STATE_PLAYING
        assert dev.media_position_updated_at is not None

        dev._playing_liveinput = True
        assert dev.media_position_updated_at is None


class TestSupportedFeatures:
    def test_default_state_returns_some_features(self) -> None:
        dev = _make_device()
        dev._state = STATE_PLAYING
        dev._playing_localfile = True
        feats = dev.supported_features
        assert feats & MediaPlayerEntityFeature.VOLUME_SET
        assert feats & MediaPlayerEntityFeature.VOLUME_STEP
        assert feats & MediaPlayerEntityFeature.PLAY

    def test_slave_returns_cached_features(self) -> None:
        dev = _make_device()
        dev._slave_mode = True
        cached = MediaPlayerEntityFeature.VOLUME_SET
        dev._features = cached
        assert dev.supported_features == cached


class TestExtraStateAttributes:
    def test_minimum_attrs_present(self) -> None:
        dev = _make_device()
        attrs = dev.extra_state_attributes
        # master + snapshot_active always present; uuid + firmware added
        # based on state. Don't pin to exact key names beyond the ones
        # we know are stable.
        assert "master" in attrs
        assert attrs["master"] is False

    def test_uuid_surfaces_when_set(self) -> None:
        dev = _make_device()
        dev._uuid = "abc"
        attrs = dev.extra_state_attributes
        assert attrs.get("uuid") == "abc"

    def test_firmware_attr_when_not_unavailable(self) -> None:
        dev = _make_device()
        dev._fw_ver = "4.6.1"
        dev._mcu_ver = "12"
        dev._state = STATE_PLAYING
        assert dev.extra_state_attributes.get("firmware") == "4.6.1.12"

    def test_firmware_attr_hidden_when_unavailable(self) -> None:
        dev = _make_device()
        dev._state = STATE_UNAVAILABLE
        assert "firmware" not in dev.extra_state_attributes
