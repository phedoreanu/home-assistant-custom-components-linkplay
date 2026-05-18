"""Multiroom group management for LinkPlayDevice.

Concentrates the join/unjoin/group_volume + master/slave state setters
and properties in one place. All methods expect to be mixed into
LinkPlayDevice, which provides:

* ``self.hass`` and ``self.hass.data[DOMAIN].entities``
* ``self.call_linkplay_httpapi``
* ``self.async_write_ha_state``
* the ``_multiroom_group`` / ``_master`` / ``_is_master`` / ``_slave_mode``
  / ``_multiroom_wifidirect`` / ``_slave_ip`` / ``_multiroom_unjoinat``
  / ``_multiroom_prevsrc`` / ``_position_updated_at`` / ``_wait_for_mcu``
  / ``_state`` / ``_slave_list`` / ``_features`` state attributes
"""

from __future__ import annotations

import logging

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.util.dt import utcnow

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class LinkPlayMultiroomMixin:
    """Multiroom half of LinkPlayDevice."""

    # ---- properties ----

    @property
    def slave(self):
        """Return true if it is a slave."""
        return self._slave_mode

    @property
    def master(self):
        """Master entity used in multiroom configuration."""
        return self._master

    @property
    def is_master(self):
        """Return true if it is a master."""
        return self._is_master

    @property
    def group_members(self):
        """Entity-ids in the current multiroom group (HA standard)."""
        return list(self._multiroom_group) if self._multiroom_group else []

    # ---- setters used by the master to push state onto slaves ----

    async def async_set_multiroom_group(self, multiroom_group):
        self._multiroom_group = multiroom_group

    async def async_set_master(self, master):
        self._master = master

    async def async_set_is_master(self, is_master):
        self._is_master = is_master

    async def async_set_multiroom_unjoinat(self, tme):
        self._multiroom_unjoinat = tme

    async def async_set_slave_mode(self, slave_mode):
        self._slave_mode = slave_mode

    async def async_set_slave_ip(self, slave_ip):
        self._slave_ip = slave_ip

    async def async_set_previous_source(self, srcbool):
        """Remember the source before entering multiroom, for restore."""
        if srcbool:
            self._multiroom_prevsrc = self._source
        else:
            self._multiroom_prevsrc = None

    async def async_restore_previous_source(self):
        """Restore the source remembered before joining a group."""
        self.select_source(self._multiroom_prevsrc)
        self._multiroom_prevsrc = None

    # ---- master-side polling ----

    async def _async_poll_multiroom_master_status(self):
        """Fetch the master multiroom slave list and propagate state to slaves.

        Slaves do not expose a slave list; the master pushes their state via
        async_set_multiroom_group. Skipping the query for slaves prevents
        clobbering the master-pushed list every poll cycle.
        """
        if self._slave_mode:
            return True

        slave_list = await self.call_linkplay_httpapi("multiroom:getSlaveList", True)
        if slave_list is None:
            self._is_master = False
            self._slave_list = None
            self._multiroom_group = []
            return True

        self._slave_list = []
        self._multiroom_group = []
        self._is_master = False
        if isinstance(slave_list, dict):
            if int(slave_list['slaves']) > 0:
                self._multiroom_group.append(self.entity_id)
                self._is_master = True
                for slave in slave_list['slave_list']:
                    for device in self.hass.data[DOMAIN].entities:
                        if device._name == slave['name']:
                            self._multiroom_group.append(device.entity_id)
                            await device.async_set_master(self)
                            await device.async_set_is_master(False)
                            await device.async_set_slave_mode(True)
                            await device.async_set_media_title(self._media_title)
                            await device.async_set_media_artist(self._media_artist)
                            await device.async_set_volume(slave['volume'])
                            await device.async_set_state(self.state)
                            await device.async_set_slave_ip(slave['ip'])
                            await device.async_set_media_image_url(self._media_image_url)
                            await device.async_set_playhead_position(self.media_position)
                            await device.async_set_duration(self.media_duration)
                            await device.async_set_position_updated_at(self.media_position_updated_at)
                            await device.async_set_source(self._source)
                            await device.async_set_sound_mode(self._sound_mode)
                            await device.async_set_features(self._features)

                    # Push the freshly-built group list once to every
                    # entity already in the group. (The original code
                    # nested this inside `for slave in slaves`, so it
                    # ran N times with identical work.)
                    for device in self.hass.data[DOMAIN].entities:
                        if device.entity_id in self._multiroom_group:
                            await device.async_set_multiroom_group(self._multiroom_group)

        else:
            _LOGGER.debug("Erroneous JSON during slave list parsing and processing: %s, %s", self.entity_id, self._name)

        return True

    # ---- join / unjoin ----

    async def async_join_players(self, slaves):
        """Join `group_members` as a player group (standard HA service)."""
        entities = self.hass.data[DOMAIN].entities
        entities = [e for e in entities if e.entity_id in slaves]
        await self.async_join(entities)

    async def async_join(self, slaves):
        """Add selected slaves to the multiroom group."""
        _LOGGER.debug("Multiroom JOIN request: Master: %s, Slaves: %s", self.entity_id, slaves)
        if self._state == STATE_UNAVAILABLE:
            return

        if self.entity_id not in self._multiroom_group:
            self._multiroom_group.append(self.entity_id)
            self._is_master = True
            self._wait_for_mcu = 2

        for slave in slaves:
            if slave._is_master:
                _LOGGER.debug("Multiroom: slave has master flag set. Unjoining it from where it is. Master: %s, Slave: %s", self.entity_id, slave.entity_id)
                await slave.async_unjoin_all()

            if slave.entity_id not in self._multiroom_group:
                if slave._slave_mode:
                    _LOGGER.debug("Multiroom: slave already has slave flag set. Unjoining it from where it is. Master: %s, Slave: %s", self.entity_id, slave.entity_id)
                    await slave.async_unjoin_me()

                await slave.async_set_previous_source(True)
                if self._multiroom_wifidirect:
                    _LOGGER.debug("Multiroom: Join in WiFi direct mode. Master: %s, Slave: %s", self.entity_id, slave.entity_id)
                    cmd = f"ConnectMasterAp:ssid={self._ssid}:ch={self._wifi_channel}:auth=OPEN:" + "encry=NONE:pwd=:chext=0"
                else:
                    _LOGGER.debug("Multiroom: Join in multiroom mode. Master: %s, Slave: %s", self.entity_id, slave.entity_id)
                    cmd = f'ConnectMasterAp:JoinGroupMaster:eth{self._host}:wifi0.0.0.0'

                value = await slave.call_linkplay_httpapi(cmd, None)
                _LOGGER.debug("Multiroom: command result: %s Master: %s, Slave: %s", value, self.entity_id, slave.entity_id)
                if value == "OK":
                    await slave.async_set_master(self)
                    await slave.async_set_is_master(False)
                    await slave.async_set_slave_mode(True)
                    await slave.async_set_media_title(self._media_title)
                    await slave.async_set_media_artist(self._media_artist)
                    await slave.async_set_state(self.state)
                    await slave.async_set_slave_ip(self._host)
                    await slave.async_set_media_image_url(self._media_image_url)
                    await slave.async_set_playhead_position(self.media_position)
                    await slave.async_set_duration(self.media_duration)
                    await slave.async_set_source(self._source)
                    await slave.async_set_sound_mode(self._sound_mode)
                    await slave.async_set_features(self._features)
                    self._multiroom_group.append(slave.entity_id)
                else:
                    await slave.async_set_previous_source(False)
                    _LOGGER.warning("Failed to join multiroom. command result: %s Master: %s, Slave: %s", value, self.entity_id, slave.entity_id)

        for slave in slaves:
            if slave.entity_id in self._multiroom_group:
                await slave.async_set_multiroom_group(self._multiroom_group)
                slave.async_write_ha_state()

        self._position_updated_at = utcnow()
        self.async_write_ha_state()

    async def async_unjoin_all(self):
        """Master disconnects everybody in the group."""
        if self._state == STATE_UNAVAILABLE:
            return

        cmd = "multiroom:Ungroup"
        value = await self.call_linkplay_httpapi(cmd, None)
        if value == "OK":
            self._is_master = False
            for slave_id in self._multiroom_group:
                for device in self.hass.data[DOMAIN].entities:
                    if device.entity_id == slave_id and device.entity_id != self.entity_id:
                        await device.async_set_slave_mode(False)
                        await device.async_set_is_master(False)
                        await device.async_set_slave_ip(None)
                        await device.async_set_master(None)
                        await device.async_set_multiroom_unjoinat(utcnow())
                        await device.async_set_multiroom_group([])
                        device.async_write_ha_state()
            self._multiroom_group = []
            self._position_updated_at = utcnow()
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Failed to unjoin_all multiroom. Device: %s, Got response: %s", self.entity_id, value)

    async def async_unjoin_player(self):
        """Remove this player from any group (standard HA service)."""
        if self._is_master:
            await self.async_unjoin_all()
        if self._slave_mode:
            await self.async_unjoin_me()

    async def async_unjoin_me(self):
        """Slave leaves the multiroom group."""
        value = None
        if self._multiroom_wifidirect:
            # Kick this slave from the master's Wi-Fi-direct group.
            # Walk the registered entities and ask whichever one is
            # the current master to evict our IP.
            for device in self.hass.data[DOMAIN].entities:
                if device.is_master:
                    cmd = f"multiroom:SlaveKickout:{self._slave_ip}"
                    value = await self._master.call_linkplay_httpapi(cmd, None)
                    self._master._position_updated_at = utcnow()
                    break
        else:
            cmd = "multiroom:Ungroup"
            value = await self.call_linkplay_httpapi(cmd, None)

        if value == "OK":
            if self._master is not None:
                await self._master.async_remove_from_group(self)
                self._master._wait_for_mcu = 1
                self._master.async_write_ha_state()
            self._multiroom_unjoinat = utcnow()
            self._master = None
            self._is_master = False
            self._slave_mode = False
            self._slave_ip = None
            self._multiroom_group = []
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Failed to unjoin_me from multiroom. Device: %s, Got response: %s", self.entity_id, value)

    async def async_set_group_volume(self, volume: float):
        """Set the master volume and shift every slave by the same delta.

        Mirrors mini-media-player's group-volume behaviour: each slave
        preserves its current offset relative to the master. Move the
        master from 0.40 to 0.50 and every slave goes up by 0.10,
        clamped to [0.0, 1.0]. A slave that's already at 1.0 stays at
        1.0 (its offset shrinks); when the master comes back down the
        slave drops normally from there.

        Args:
            volume: new master volume (0.0 to 1.0).
        """
        # First call after restart has no prior master volume to diff
        # against. Treat the call as an absolute set (delta=0) so every
        # member lands on `volume` instead of drifting from stale state.
        current_master = self.volume_level if self.volume_level is not None else volume
        delta = volume - current_master

        _LOGGER.debug(
            "Group volume: master=%s, %.2f -> %.2f (delta=%+.2f), group=%s",
            self.entity_id, current_master, volume, delta,
            self._multiroom_group,
        )

        by_eid = {d.entity_id: d for d in self.hass.data[DOMAIN].entities}
        group_entities = [by_eid[eid] for eid in self._multiroom_group if eid in by_eid]

        for device in group_entities:
            if device.entity_id == self.entity_id:
                target = volume
            else:
                base = device.volume_level if device.volume_level is not None else current_master
                target = base + delta
            final_volume = max(0.0, min(1.0, target))
            current = device.volume_level if device.volume_level is not None else "n/a"
            _LOGGER.debug(
                "  %s: %s -> %.2f", device.entity_id, current, final_volume
            )
            await device.async_set_volume_level(final_volume)

    async def async_remove_from_group(self, device):
        """Master removes a single member from its group."""
        if device.entity_id in self._multiroom_group:
            self._multiroom_group.remove(device.entity_id)

        if len(self._multiroom_group) <= 1:
            self._multiroom_group = []
            self._is_master = False
            self._slave_list = None

        for member in self._multiroom_group:
            for player in self.hass.data[DOMAIN].entities:
                if player.entity_id == member and player.entity_id != self.entity_id:
                    await player.async_set_multiroom_group(self._multiroom_group)
                    player.async_write_ha_state()

        self.async_write_ha_state()
