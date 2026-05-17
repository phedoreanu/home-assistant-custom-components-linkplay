"""Trivial attribute setters used by the master to push state onto slaves.

Kept as small async methods to match the existing call sites (every
caller awaits them, and async_join/_async_poll_multiroom_master_status
iterates slaves and awaits each setter).
"""

from __future__ import annotations


class LinkPlaySettersMixin:
    """Attribute-setter half of LinkPlayDevice.

    The mixin only mutates ``_underscored`` state already declared in
    LinkPlayDevice.__init__; it does not introduce any new attributes.
    """

    async def async_set_media_title(self, title):
        self._media_title = title

    async def async_set_media_artist(self, artist):
        self._media_artist = artist

    async def async_set_volume(self, volume):
        self._volume = volume

    async def async_set_muted(self, mute):
        self._muted = mute

    async def async_set_state(self, state):
        self._state = state

    async def async_set_playhead_position(self, position):
        self._playhead_position = position

    async def async_set_duration(self, duration):
        self._duration = duration

    async def async_set_position_updated_at(self, time):
        self._position_updated_at = time

    async def async_set_source(self, source):
        self._source = source

    async def async_set_sound_mode(self, mode):
        self._sound_mode = mode

    async def async_set_media_image_url(self, url):
        self._media_image_url = url

    async def async_set_media_uri(self, uri):
        self._media_uri = uri

    async def async_set_features(self, features):
        self._features = features

    async def async_set_wait_for_mcu(self, wait_for_mcu):
        self._wait_for_mcu = wait_for_mcu

    async def async_set_unav_throttle(self, unav_throttle):
        self._unav_throttle = unav_throttle
