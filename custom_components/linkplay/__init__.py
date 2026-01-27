"""
Support for LinkPlay based devices.

For more details about this platform, please refer to the documentation at
https://github.com/phedoreanu/home-assistant-custom-components-linkplay
"""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

DOMAIN = 'linkplay'
PLATFORMS = [Platform.MEDIA_PLAYER]

SERVICE_JOIN = 'join'
SERVICE_UNJOIN = 'unjoin'
SERVICE_PRESET = 'play_preset'
SERVICE_CMD = 'command'
SERVICE_SNAP = 'snapshot'
SERVICE_REST = 'restore'
SERVICE_LIST = 'get_tracks'
SERVICE_PLAY = 'play_track'
SERVICE_SET_GROUP_VOLUME = 'set_group_volume'

ATTR_MASTER = 'master'
ATTR_PRESET = 'preset_number'
ATTR_CMD = 'command'
ATTR_NOTIF = 'notify'
ATTR_SNAP = 'switchinput'
ATTR_SELECT = 'input_select'
ATTR_SOURCE = 'source'
ATTR_TRACK = 'track'
ATTR_VOLUME = 'volume'
ATTR_VOLUME_OFFSETS = 'volume_offsets'

SERVICE_SCHEMA = vol.Schema({
    vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids
})

JOIN_SERVICE_SCHEMA = SERVICE_SCHEMA.extend({
    vol.Required(ATTR_MASTER): cv.entity_id
})

PRESET_BUTTON_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.comp_entity_ids,
    vol.Required(ATTR_PRESET): cv.positive_int
})

CMND_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.comp_entity_ids,
    vol.Required(ATTR_CMD): cv.string,
    vol.Optional(ATTR_NOTIF, default=True): cv.boolean
})

REST_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.comp_entity_ids
})

SNAP_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.comp_entity_ids,
    vol.Optional(ATTR_SNAP, default=True): cv.boolean
})

PLYTRK_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.entity_id,
    vol.Required(ATTR_TRACK): cv.template
})

SET_GROUP_VOLUME_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.entity_id,
    vol.Required(ATTR_VOLUME): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
    vol.Optional(ATTR_VOLUME_OFFSETS): dict,
})

_LOGGER = logging.getLogger(__name__)


class LinkPlayData:
    """Storage class for platform global data."""
    def __init__(self):
        """Initialize the data."""
        self.entities = []


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Linkplay component from YAML configuration."""
    hass.data.setdefault(DOMAIN, LinkPlayData())

    # Register services
    await async_setup_services(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Linkplay from a config entry."""
    hass.data.setdefault(DOMAIN, LinkPlayData())

    # Forward the setup to the media_player platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services if not already registered
    if not hass.services.has_service(DOMAIN, SERVICE_JOIN):
        await async_setup_services(hass)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    return unload_ok


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Linkplay integration."""

    async def async_service_handle(service):
        """Handle services."""
        _LOGGER.debug("DOMAIN: %s, entities: %s", DOMAIN, str(hass.data[DOMAIN].entities))
        _LOGGER.debug("Service_handle from id: %s", service.data.get(ATTR_ENTITY_ID))
        entity_ids = service.data.get(ATTR_ENTITY_ID)
        entities = hass.data[DOMAIN].entities

        if entity_ids:
            if entity_ids == 'all':
                entity_ids = [e.entity_id for e in entities]
            entities = [e for e in entities if e.entity_id in entity_ids]

        if service.service == SERVICE_JOIN:
            master = [e for e in hass.data[DOMAIN].entities
                      if e.entity_id == service.data[ATTR_MASTER]]
            if master:
                client_entities = [e for e in entities
                                   if e.entity_id != master[0].entity_id]
                _LOGGER.debug("**JOIN** set clients %s for master %s",
                              [e.entity_id for e in client_entities],
                              master[0].entity_id)
                await master[0].async_join(client_entities)

        elif service.service == SERVICE_UNJOIN:
            _LOGGER.debug("**UNJOIN** entities: %s", entities)
            masters = [entities for entities in entities
                       if entities.is_master]
            if masters:
                for master in masters:
                    await master.async_unjoin_all()
            else:
                for entity in entities:
                    await entity.async_unjoin_me()

        elif service.service == SERVICE_PRESET:
            preset = service.data.get(ATTR_PRESET)
            for device in entities:
                if device.entity_id in entity_ids:
                    _LOGGER.debug("**PRESET** entity: %s; preset: %s", device.entity_id, preset)
                    await device.async_preset_button(preset)

        elif service.service == SERVICE_CMD:
            command = service.data.get(ATTR_CMD)
            notify = service.data.get(ATTR_NOTIF)
            for device in entities:
                if device.entity_id in entity_ids:
                    _LOGGER.debug("**COMMAND** entity: %s; command: %s", device.entity_id, command)
                    await device.async_execute_command(command, notify)

        elif service.service == SERVICE_SNAP:
            switchinput = service.data.get(ATTR_SNAP)
            for device in entities:
                if device.entity_id in entity_ids:
                    _LOGGER.debug("**SNAPSHOT** entity: %s;", device.entity_id)
                    await device.async_snapshot(switchinput)

        elif service.service == SERVICE_REST:
            for device in entities:
                if device.entity_id in entity_ids:
                    _LOGGER.debug("**RESTORE** entity: %s;", device.entity_id)
                    await device.async_restore()

        elif service.service == SERVICE_PLAY:
            track = service.data.get(ATTR_TRACK)
            for device in entities:
                if device.entity_id in entity_ids:
                    _LOGGER.debug("**PLAY TRACK** entity: %s; track: %s", device.entity_id, track)
                    await device.async_play_track(track)

        elif service.service == SERVICE_SET_GROUP_VOLUME:
            volume = service.data.get(ATTR_VOLUME)
            volume_offsets = service.data.get(ATTR_VOLUME_OFFSETS, {})

            # Convert percentage-style offsets (integers) to fractional offsets (floats)
            # Percentages are in range -100 to 100 and are given as integers.
            # Fractional offsets are in range -1.0 to 1.0 and are given as floats.
            # Note: Percentages represent percentage points (e.g., 10 = +0.10), not multipliers.
            converted_offsets = {}
            for entity_id, offset in volume_offsets.items():
                # If offset is an integer, interpret it as a percentage and convert to fractional
                if isinstance(offset, int):
                    # Validate percentage range
                    if offset < -100 or offset > 100:
                        _LOGGER.error(
                            "Invalid volume offset percentage %s for entity %s; expected -100 to 100",
                            offset,
                            entity_id,
                        )
                        raise ValueError(
                            f"Invalid volume offset percentage {offset} for entity {entity_id}; "
                            "expected value between -100 and 100."
                        )
                    converted_offsets[entity_id] = offset / 100.0
                elif isinstance(offset, float):
                    # Already in fractional format; validate expected range -1.0 to 1.0
                    if offset < -1.0 or offset > 1.0:
                        _LOGGER.error(
                            "Invalid fractional volume offset %s for entity %s; expected -1.0 to 1.0",
                            offset,
                            entity_id,
                        )
                        raise ValueError(
                            f"Invalid fractional volume offset {offset} for entity {entity_id}; "
                            "expected value between -1.0 and 1.0."
                        )
                    converted_offsets[entity_id] = offset
                else:
                    # Preserve any other types as-is
                    converted_offsets[entity_id] = offset

            # Find the master device from the entity_ids
            master_device = None
            for device in entities:
                if device.entity_id in entity_ids:
                    master_device = device
                    break

            if master_device:
                _LOGGER.debug(
                    "**SET GROUP VOLUME** master: %s; volume: %s; offsets: %s (converted: %s)",
                    master_device.entity_id,
                    volume,
                    volume_offsets,
                    converted_offsets
                )
                await master_device.async_set_group_volume(volume, converted_offsets)

    # Register all services
    hass.services.async_register(
        DOMAIN, SERVICE_JOIN, async_service_handle, schema=JOIN_SERVICE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_UNJOIN, async_service_handle, schema=SERVICE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_PRESET, async_service_handle, schema=PRESET_BUTTON_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_CMD, async_service_handle, schema=CMND_SERVICE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SNAP, async_service_handle, schema=SNAP_SERVICE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_REST, async_service_handle, schema=REST_SERVICE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_PLAY, async_service_handle, schema=PLYTRK_SERVICE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_GROUP_VOLUME, async_service_handle, schema=SET_GROUP_VOLUME_SCHEMA)
