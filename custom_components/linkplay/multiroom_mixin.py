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

import asyncio
import logging
from datetime import timedelta

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.util.dt import utcnow

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Window during which we trust the locally-built ``_multiroom_group``
# over a poll response that says ``slaves=0``. On AudioPro A28 firmware
# (and others) the ``multiroom:getSlaveList`` response lags the
# ``ConnectMasterAp`` success by several seconds; without this grace
# the master's group is cleared between ``async_join`` and the very
# next user-script action (e.g. ``linkplay.set_group_volume``), and
# the service iterates an empty list.
_JOIN_GRACE = timedelta(seconds=10)



class LinkPlayMultiroomMixin:
    """Multiroom half of LinkPlayDevice."""

    # How long ``async_join`` waits for the firmware to populate each
    # new slave's WiFi-direct IP (visible via ``multiroom:getSlaveList``)
    # before returning. Class attributes so tests can override them on
    # the instance without monkeypatching the module.
    _slave_ip_poll_interval = 0.5  # seconds between getSlaveList polls
    _slave_ip_poll_max = 10        # attempts -> up to ~5 s total

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

    def _within_join_grace(self) -> bool:
        """True while ``async_join`` is still propagating to firmware.

        WiFi-direct slaves take several seconds to appear in
        ``multiroom:getSlaveList`` after ``ConnectMasterAp`` returns OK.
        During that window we keep the locally-built ``_multiroom_group``
        even if the firmware claims zero slaves, so user scripts that
        run ``linkplay.join`` immediately followed by
        ``linkplay.set_group_volume`` see a populated group.
        """
        return (
            self._multiroom_joinat is not None
            and (utcnow() - self._multiroom_joinat) < _JOIN_GRACE
        )

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
            if not self._within_join_grace():
                self._is_master = False
                self._slave_list = None
                self._multiroom_group = []
            return True

        if isinstance(slave_list, dict):
            if int(slave_list['slaves']) > 0:
                # Firmware confirms group; rebuild from the authoritative
                # slave list (and clear the grace timestamp, since the
                # group is now reflected in firmware).
                self._multiroom_joinat = None
                self._slave_list = []
                self._multiroom_group = []
                self._is_master = True
                self._multiroom_group.append(self.entity_id)
                for slave in slave_list['slave_list']:
                    for device in self.hass.data[DOMAIN].entities:
                        if device._name == slave['name']:
                            self._multiroom_group.append(device.entity_id)
                            await device.async_set_master(self)
                            await device.async_set_is_master(False)
                            await device.async_set_slave_mode(True)
                            await device.async_set_media_title(self._media_title)
                            await device.async_set_media_artist(self._media_artist)
                            # Same stale-poll guard as the master's own
                            # getPlayerStatus handler: a slave-list
                            # response in flight while the group volume
                            # changed would write the old value back.
                            if not device._within_volume_grace():
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

            elif not self._within_join_grace():
                # Firmware says no slaves and we're outside the
                # post-join grace window, so the player really is
                # standalone again. Clear the group.
                self._slave_list = []
                self._multiroom_group = []
                self._is_master = False
            # else: still in grace, leave _multiroom_group / _is_master
            # alone so the locally-built post-join state survives the
            # firmware's transient zero-slaves report.

        else:
            _LOGGER.debug("Erroneous JSON during slave list parsing and processing: %s, %s", self.entity_id, self._name)

        return True

    # ---- join / unjoin ----

    async def async_join_players(self, group_members):
        """Join ``group_members`` as a player group (standard HA service).

        Home Assistant's media_player.join service calls this with the
        keyword name ``group_members``; the parameter is a list of
        entity_ids to add as slaves to this device.
        """
        entities = self.hass.data[DOMAIN].entities
        entities = [e for e in entities if e.entity_id in group_members]
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
                    # Leave _slave_ip as-is until the firmware reveals
                    # the WiFi-direct address via multiroom:getSlaveList.
                    # The previous code wrote self._host here, which made
                    # multiroom:SlaveVolume:<master-ip>:<N> commands
                    # silently no-op (wrong target). The retry-poll loop
                    # at the end of async_join populates the real IP
                    # before returning.
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

        # Mark the moment the group was built locally. The master-side
        # poll uses this to ignore a transient ``slaves=0`` response
        # from ``multiroom:getSlaveList`` for the next few seconds,
        # which would otherwise wipe the group we just constructed.
        if len(self._multiroom_group) > 1:
            self._multiroom_joinat = utcnow()

        self._position_updated_at = utcnow()
        self.async_write_ha_state()

        # Block until the firmware has reflected the new slaves in its
        # multiroom:getSlaveList. The response carries each slave's
        # WiFi-direct IP, which multiroom:SlaveVolume needs to address
        # the slave instead of the master. Without this wait, a script
        # that does ``linkplay.join`` immediately followed by
        # ``linkplay.set_group_volume`` would send SlaveVolume commands
        # to the master's own host and silently fail.
        await self._await_slave_ips(slaves)

    async def _await_slave_ips(self, slaves) -> None:
        """Poll the master for each new slave's WiFi-direct IP + volume.

        Returns once every joined slave has a non-master ``_slave_ip``
        or after ``_slave_ip_poll_max`` attempts. Safe to call with an
        empty join (returns immediately).

        Also copies each slave's reported ``volume`` (0-100) into its
        local ``_volume`` so callers like ``async_set_group_volume``
        have an accurate base for the delta-preserving group shift.
        Without this, slaves keep the pre-join cached value and the
        delta shift lands them at the wrong target.
        """
        new_slaves = [
            s for s in slaves if s.entity_id in self._multiroom_group
        ]
        if not new_slaves:
            return

        for _ in range(self._slave_ip_poll_max):
            await asyncio.sleep(self._slave_ip_poll_interval)
            slave_list = await self.call_linkplay_httpapi(
                "multiroom:getSlaveList", True,
            )
            if not isinstance(slave_list, dict):
                continue
            if int(slave_list.get('slaves', 0)) <= 0:
                continue
            by_name = {
                entry.get('name'): entry
                for entry in slave_list.get('slave_list', [])
                if entry.get('name')
            }
            for slave in new_slaves:
                entry = by_name.get(slave._name)
                if not entry:
                    continue
                if entry.get('ip'):
                    await slave.async_set_slave_ip(entry['ip'])
                if entry.get('volume') is not None:
                    await slave.async_set_volume(entry['volume'])
            if all(
                getattr(s, '_slave_ip', None)
                and s._slave_ip != self._host
                for s in new_slaves
            ):
                return
        _LOGGER.debug(
            "async_join: timed out waiting for slave IPs from firmware "
            "(master=%s, slaves=%s)",
            self.entity_id,
            [s.entity_id for s in new_slaves],
        )

    async def async_unjoin_all(self):
        """Master disconnects everybody in the group."""
        if self._state == STATE_UNAVAILABLE:
            return

        cmd = "multiroom:Ungroup"
        value = await self.call_linkplay_httpapi(cmd, None)
        if value == "OK":
            self._is_master = False
            self._multiroom_joinat = None
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
            self._multiroom_joinat = None
            self._master = None
            self._is_master = False
            self._slave_mode = False
            self._slave_ip = None
            self._multiroom_group = []
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Failed to unjoin_me from multiroom. Device: %s, Got response: %s", self.entity_id, value)

    async def async_set_group_volume(self, volume: float):
        """Set the master volume and apply each slave's configured offset.

        Mirrors mini-media-player's per-entity ``volume_offset``
        behaviour: every member's target is anchored to the new master
        volume, and each slave shifts that target by its own configured
        offset (signed percentage points stored in ``_volume_offset``).

        Example with offsets ``kitchen=-10``, ``office=-15`` and
        ``volume=0.18``:

        * master -> 0.18
        * kitchen -> 0.18 + (-10/100) = 0.08
        * office -> 0.18 + (-15/100) = 0.03

        All final values are clamped to ``[0.0, 1.0]``.

        Earlier versions derived the delta from the master's *current*
        volume, which depended on every slave's cached ``volume_level``
        being accurate at call time. That broke after Bluetooth /
        standalone sessions where the master had been driven loud
        independently of the group: a subsequent
        ``linkplay.set_group_volume 0.18`` would compute a large
        negative delta and clamp slaves to silence even when the
        intent was simply "set the group to 0.18 with per-slave
        offsets".

        Args:
            volume: new master volume (0.0 to 1.0). Each slave ends at
                ``volume + slave._volume_offset / 100``, clamped.
        """
        master_target = max(0.0, min(1.0, volume))

        _LOGGER.debug(
            "Group volume: master=%s -> %.2f (offsets per slave), group=%s",
            self.entity_id, master_target, self._multiroom_group,
        )

        by_eid = {d.entity_id: d for d in self.hass.data[DOMAIN].entities}
        # Always include the caller (the master) in the iteration even
        # if the cached group list is empty - the poll cycle on some
        # AudioPro firmwares briefly returns ``slaves=0`` and the
        # join-grace window is not always enough to cover every race.
        # Without this guard, a poll-cleared group would make
        # set_group_volume a no-op on the master too.
        group_entities: list = []
        seen: set[str] = set()
        if self.entity_id in by_eid:
            group_entities.append(by_eid[self.entity_id])
            seen.add(self.entity_id)
        for eid in self._multiroom_group:
            if eid in by_eid and eid not in seen:
                group_entities.append(by_eid[eid])
                seen.add(eid)

        for device in group_entities:
            if device.entity_id == self.entity_id:
                target = master_target
            else:
                offset = getattr(device, "_volume_offset", 0) or 0
                target = master_target + (offset / 100.0)
            final_volume = max(0.0, min(1.0, target))
            current = device.volume_level if device.volume_level is not None else "n/a"
            _LOGGER.debug(
                "  %s: %s -> %.2f (offset=%+d)",
                device.entity_id, current, final_volume,
                getattr(device, "_volume_offset", 0) or 0,
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
