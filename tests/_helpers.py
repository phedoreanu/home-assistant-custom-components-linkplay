"""Shared builders for LinkPlayDevice test instances.

Replaces the ~13 near-identical ``_make_device`` copies that each test
module used to carry. Tests import ``make_device`` / ``make_group`` and
then apply any module-specific mocks (``call_linkplay_httpapi``, poll
caps, ``async_write_ha_state``, etc.) on the returned instance.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.const import STATE_IDLE


def make_device(
    name: str = "device",
    *,
    host: str = "1.2.3.4",
    protocol: str = "http",
    sources=None,
    common_sources=None,
    icecast_metadata: str = "StationName",
    multiroom_wifidirect: bool = False,
    led_off: bool = False,
    volume_step: int = 5,
    lastfm_api_key=None,
    uuid: str = "",
    state: str = STATE_IDLE,
    hass=None,
):
    """Build a real LinkPlayDevice with the UPnP/aiohttp factories patched out.

    Keyword args map straight onto the ``LinkPlayDevice`` constructor so a
    caller only overrides what it cares about (e.g. ``sources=...`` or
    ``uuid=...``). ``entity_id`` is set to ``media_player.<name>`` and a
    ``MagicMock`` hass with an empty linkplay entities list is attached
    unless one is supplied.
    """
    from custom_components.linkplay.media_player import LinkPlayDevice

    if hass is None:
        hass = MagicMock()
        hass.data = {"linkplay": MagicMock(entities=[])}

    with patch("custom_components.linkplay.media_player.AiohttpRequester"), patch(
        "custom_components.linkplay.media_player.UpnpFactory"
    ):
        dev = LinkPlayDevice(
            name=name,
            host=host,
            protocol=protocol,
            sources=sources,
            common_sources=common_sources,
            icecast_metadata=icecast_metadata,
            multiroom_wifidirect=multiroom_wifidirect,
            led_off=led_off,
            volume_step=volume_step,
            lastfm_api_key=lastfm_api_key,
            uuid=uuid,
            state=state,
        )
    dev.entity_id = f"media_player.{name}"
    dev.hass = hass
    return dev


def make_group(master_name: str, slave_names: list[str]):
    """A master plus N slaves sharing a single hass ``entities`` list."""
    master = make_device(master_name)
    slaves = [make_device(n) for n in slave_names]
    entities = [master, *slaves]
    for entity in entities:
        entity.hass.data["linkplay"].entities = entities
    return master, slaves
