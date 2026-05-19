"""
Support for Linkplay based devices.

For more details about this platform, please refer to the documentation at
https://github.com/phedoreanu/home-assistant-custom-components-linkplay
"""

import asyncio
import contextlib
import voluptuous as vol

from datetime import timedelta
import logging
from json import loads, dumps
import binascii
import string
import aiohttp

from http import HTTPStatus

from async_upnp_client.client_factory import UpnpFactory
from async_upnp_client.aiohttp import AiohttpRequester


from homeassistant.util.dt import utcnow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from homeassistant.components.media_player import (
    PLATFORM_SCHEMA,
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerDeviceClass,
)

from homeassistant.components import media_source
from homeassistant.components.media_player.browse_media import (
    async_process_play_media_url,
)

from homeassistant.components.media_player.const import (
    MediaType,
    RepeatMode,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PROTOCOL,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)

from . import ATTR_MASTER
from .metadata import (
    decode_hex_utf8,
    parse_player_status_field,
)
from .api_client_mixin import LinkPlayAPIClientMixin
from .commands_mixin import LinkPlayCommandsMixin
from .icecast_fetcher_mixin import LinkPlayIcecastFetcherMixin
from .itunes_artwork_mixin import LinkPlayItunesArtworkMixin
from .lastfm_mixin import LinkPlayLastFmMixin
from .media_controls_mixin import LinkPlayMediaControlsMixin
from .multiroom_mixin import LinkPlayMultiroomMixin
from .setters_mixin import LinkPlaySettersMixin
from .snapshot_mixin import LinkPlaySnapshotMixin
from .somafm_fetcher_mixin import LinkPlaySomaFmFetcherMixin, somafm_channel_slug
from .stream_resolver_mixin import LinkPlayStreamResolverMixin
from .upnp_mixin import LinkPlayUPnPMixin
from .volume_controls_mixin import LinkPlayVolumeControlsMixin
from .const import (
    DOMAIN,
    CONF_ICECAST_METADATA,
    CONF_MULTIROOM_WIFIDIRECT,
    CONF_LEDOFF,
    CONF_VOLUME_STEP,
    CONF_VOLUME_OFFSET,
    CONF_SOURCES,
    DEFAULT_ICECAST_UPDATE,
    DEFAULT_MULTIROOM_WIFIDIRECT,
    DEFAULT_LEDOFF,
    DEFAULT_VOLUME_STEP,
    DEFAULT_VOLUME_OFFSET,
)

_LOGGER = logging.getLogger(__name__)

ICON_DEFAULT = 'mdi:speaker'
ICON_PLAYING = 'mdi:speaker-wireless'
ICON_MUTED = 'mdi:speaker-off'
ICON_MULTIROOM = 'mdi:speaker-multiple'
ICON_BLUETOOTH = 'mdi:speaker-bluetooth'
ICON_PUSHSTREAM = 'mdi:cast-audio'
ICON_TTS = 'mdi:speaker-message'

ATTR_SLAVE = 'slave'
ATTR_LINKPLAY_GROUP = 'linkplay_group'
ATTR_FWVER = 'firmware'
ATTR_TRCNT = 'tracks_local'
ATTR_TRCRT = 'track_current'
ATTR_STURI = 'stream_uri'
ATTR_UUID = 'uuid'
ATTR_TTS = 'tts_active'
ATTR_SNAPSHOT = 'snapshot_active'
ATTR_SNAPSPOT = 'snapshot_spotify'
ATTR_DEBUG = 'debug_info'

CONF_LASTFM_API_KEY = 'lastfm_api_key'
CONF_COMMONSOURCES = 'common_sources'
CONF_UUID = 'uuid'

DEBUGSTR_ATTR = False
LASTFM_API_BASE = 'http://ws.audioscrobbler.com/2.0/?method='
MAX_VOL = 100
FW_MROOM_RTR_MIN = '4.2.8020'
FW_RAKOIT_UART_MIN = '4.2.9326'
FW_SLOW_STREAMS = '4.6'
ROOTDIR_USB = '/media/sda1/'
UUID_ARYLIC = 'FF31F09E'
TCPPORT = 8899
UPNP_TIMEOUT = 2
API_TIMEOUT = 2
SCAN_INTERVAL = timedelta(seconds=3)
ICE_THROTTLE = timedelta(seconds=45)
LFM_THROTTLE = timedelta(seconds=4)
UNA_THROTTLE = timedelta(seconds=20)
MROOM_UJWDIR = timedelta(seconds=20)
MROOM_UJWROU = timedelta(seconds=3)
SPOTIFY_PAUSED_TIMEOUT = timedelta(seconds=300)
AUTOIDLE_STATE_TIMEOUT = timedelta(seconds=1)
#PARALLEL_UPDATES = 0

CUT_EXTENSIONS = ['mp3', 'mp2', 'm2a', 'mpg', 'wav', 'aac', 'flac', 'flc', 'm4a', 'ape', 'wma', 'ac3', 'ogg']

SOUND_MODES = {'0': 'Normal', '1': 'Classic', '2': 'Pop', '3': 'Jazz', '4': 'Vocal'}

SOURCES = {'bluetooth': 'Bluetooth',
           'line-in': 'Line-in',
           'line-in2': 'Line-in 2',
           'optical': 'Optical',
           'co-axial': 'Coaxial',
           'HDMI': 'HDMI',
           'udisk': 'USB disk',
           'TFcard': 'SD card',
           'RCA': 'RCA',
           'XLR': 'XLR',
           'FM': 'FM',
           'cd': 'CD',
           'PCUSB': 'USB DAC'}

SOURCES_MAP = {'-1': 'Idle',
               '0': 'Idle',
               '1': 'Airplay',
               '2': 'DLNA',
               '3': 'QPlay',
               '10': 'Network',
               '11': 'udisk',
               '16': 'TFcard',
               '20': 'API',
               '21': 'udisk',
               '30': 'Alarm',
               '31': 'Spotify',
               '40': 'line-in',
               '41': 'bluetooth',
               '43': 'optical',
               '44': 'RCA',
               '45': 'co-axial',
               '46': 'FM',
               '47': 'line-in2',
               '48': 'XLR',
               '49': 'HDMI',
               '50': 'cd',
               '51': 'USB DAC',
               '52': 'TFcard',
               '60': 'Talk',
               '99': 'Idle'}

SOURCES_LIVEIN = ['-1', '0', '40', '41', '43', '44', '45', '46', '47', '48', '49', '50', '51', '99']
SOURCES_STREAM = ['1', '2', '3', '10', '30']
SOURCES_LOCALF = ['11', '16', '20', '21', '52', '60']

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_PROTOCOL): vol.In(['http', 'https']),
        vol.Optional(CONF_ICECAST_METADATA, default=DEFAULT_ICECAST_UPDATE): vol.In(['Off', 'StationName', 'StationNameSongTitle']),
        vol.Optional(CONF_MULTIROOM_WIFIDIRECT, default=DEFAULT_MULTIROOM_WIFIDIRECT): cv.boolean,
        vol.Optional(CONF_LEDOFF, default=DEFAULT_LEDOFF): cv.boolean,
        vol.Optional(CONF_SOURCES): cv.ensure_list,
        vol.Optional(CONF_COMMONSOURCES): cv.ensure_list,
        vol.Optional(CONF_LASTFM_API_KEY): cv.string,
        vol.Optional(CONF_UUID, default=''): cv.string,
        vol.Optional(CONF_VOLUME_STEP, default=DEFAULT_VOLUME_STEP): vol.All(int, vol.Range(min=1, max=25)),
        vol.Optional(CONF_VOLUME_OFFSET, default=DEFAULT_VOLUME_OFFSET): vol.All(int, vol.Range(min=-100, max=100)),
    }
)

class LinkPlayData:
    """Storage class for platform global data."""
    def __init__(self):
        """Initialize the data."""
        self.entities = []

async def async_setup_platform(hass, config, async_add_entities, _discovery_info=None):
    """Set up the LinkPlayDevice platform.

    ``_discovery_info`` is part of the HA platform-setup signature for
    legacy YAML discovery, intentionally unused: SSDP / Zeroconf go
    through the config flow instead.
    """

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = LinkPlayData()

    name = config.get(CONF_NAME)
    host = config.get(CONF_HOST)
    protocol = config.get(CONF_PROTOCOL)
    sources = config.get(CONF_SOURCES)
    common_sources = config.get(CONF_COMMONSOURCES)
    icecast_metadata = config.get(CONF_ICECAST_METADATA)
    multiroom_wifidirect = config.get(CONF_MULTIROOM_WIFIDIRECT)
    led_off = config.get(CONF_LEDOFF)
    volume_step = config.get(CONF_VOLUME_STEP)
    volume_offset = config.get(CONF_VOLUME_OFFSET, DEFAULT_VOLUME_OFFSET)
    lastfm_api_key = config.get(CONF_LASTFM_API_KEY)
    uuid = config.get(CONF_UUID)

    default_protocol = False
    if protocol is None:
        protocol = "http"
        default_protocol = True

    state = STATE_IDLE

    websession = async_get_clientsession(hass)
    response = None

    try:
        initurl = "{}://{}/httpapi.asp?command=getStatus"
        response = await websession.get(initurl.format(protocol, host), timeout=aiohttp.ClientTimeout(total=API_TIMEOUT))

    except (TimeoutError, aiohttp.ClientError) as error:
        if default_protocol:
            try:
                protocol = "https"
                initurl = "{}://{}/httpapi.asp?command=getStatusEx"
                response = await websession.get(initurl.format(protocol, host), ssl=False, timeout=aiohttp.ClientTimeout(total=API_TIMEOUT))

            except (TimeoutError, aiohttp.ClientError) as error:
                _LOGGER.warning(
                    "Failed communicating with LinkPlayDevice (start) '%s': uuid: %s %s", host, uuid, type(error)
                )
                state = STATE_UNAVAILABLE
        else:
            _LOGGER.warning(
                "Failed communicating with LinkPlayDevice (start) '%s': uuid: %s %s", host, uuid, type(error)
            )
            state = STATE_UNAVAILABLE

    if response and response.status == HTTPStatus.OK:
        data = await response.json(content_type=None)
        _LOGGER.debug("HOST: %s DATA response: %s", host, data)

        if 'uuid' in data:
            uuid = data['uuid']

        if 'DeviceName' in data and name is None:
            name = data['DeviceName']

    else:
        _LOGGER.warning(
            "Get Status UUID failed, response code: %s Full message: %s",
            response.status if response is not None else "Unknown",
            response,
        )
        state = STATE_UNAVAILABLE

    linkplay = LinkPlayDevice(name,
                            host,
                            protocol,
                            sources,
                            common_sources,
                            icecast_metadata,
                            multiroom_wifidirect,
                            led_off,
                            volume_step,
                            lastfm_api_key,
                            uuid,
                            state,
                            volume_offset=volume_offset)

    _LOGGER.info("[%s @ %s] adding media_player entity (YAML)", name, host)
    async_add_entities([linkplay])


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Linkplay media player from a config entry."""
    from . import LinkPlayData as InitLinkPlayData

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = InitLinkPlayData()

    # Get configuration from config entry
    host = entry.data.get(CONF_HOST)
    name = entry.data.get(CONF_NAME, f"Linkplay Device ({host})")
    protocol = entry.data.get(CONF_PROTOCOL, "http")

    # Get options from config entry
    sources = entry.data.get(CONF_SOURCES)
    common_sources = entry.data.get(CONF_COMMONSOURCES)
    icecast_metadata = entry.options.get(
        CONF_ICECAST_METADATA,
        entry.data.get(CONF_ICECAST_METADATA, DEFAULT_ICECAST_UPDATE)
    )
    multiroom_wifidirect = entry.options.get(
        CONF_MULTIROOM_WIFIDIRECT,
        entry.data.get(CONF_MULTIROOM_WIFIDIRECT, DEFAULT_MULTIROOM_WIFIDIRECT)
    )
    led_off = entry.options.get(
        CONF_LEDOFF,
        entry.data.get(CONF_LEDOFF, DEFAULT_LEDOFF)
    )
    volume_step = entry.options.get(
        CONF_VOLUME_STEP,
        entry.data.get(CONF_VOLUME_STEP, DEFAULT_VOLUME_STEP)
    )
    volume_offset = entry.options.get(
        CONF_VOLUME_OFFSET,
        entry.data.get(CONF_VOLUME_OFFSET, DEFAULT_VOLUME_OFFSET)
    )
    lastfm_api_key = entry.data.get(CONF_LASTFM_API_KEY)
    uuid = entry.unique_id or ""

    state = STATE_IDLE

    websession = async_get_clientsession(hass)
    response = None

    try:
        initurl = f"{protocol}://{host}/httpapi.asp?command=getStatus"
        response = await websession.get(initurl, timeout=aiohttp.ClientTimeout(total=API_TIMEOUT))

    except (TimeoutError, aiohttp.ClientError) as error:
        _LOGGER.warning(
            "[%s @ %s] startup probe failed: %s",
            name, host, type(error).__name__,
        )
        state = STATE_UNAVAILABLE

    if response and response.status == HTTPStatus.OK:
        data = await response.json(content_type=None)

        if 'uuid' in data and not uuid:
            uuid = data['uuid']

        if 'DeviceName' in data and data['DeviceName']:
            name = data['DeviceName']

        _LOGGER.info(
            "[%s @ %s] discovered: fw=%s hw=%s uuid=%s",
            name, host,
            data.get('firmware', 'unknown'),
            data.get('hardware', 'unknown'),
            uuid or 'unknown',
        )
        _LOGGER.debug("[%s] full getStatus payload: %s", name, data)
    else:
        _LOGGER.warning(
            "[%s @ %s] getStatus failed, response code: %s",
            name, host,
            response.status if response is not None else "Unknown",
        )
        state = STATE_UNAVAILABLE

    linkplay = LinkPlayDevice(
        name,
        host,
        protocol,
        sources,
        common_sources,
        icecast_metadata,
        multiroom_wifidirect,
        led_off,
        volume_step,
        lastfm_api_key,
        uuid,
        state,
        volume_offset=volume_offset,
    )

    _LOGGER.info("[%s @ %s] adding media_player entity", name, host)
    async_add_entities([linkplay])


class LinkPlayDevice(
    LinkPlayAPIClientMixin,
    LinkPlayMultiroomMixin,
    LinkPlaySettersMixin,
    LinkPlayCommandsMixin,
    LinkPlaySnapshotMixin,
    LinkPlayUPnPMixin,
    LinkPlayStreamResolverMixin,
    LinkPlayIcecastFetcherMixin,
    LinkPlaySomaFmFetcherMixin,
    LinkPlayItunesArtworkMixin,
    LinkPlayLastFmMixin,
    LinkPlayVolumeControlsMixin,
    LinkPlayMediaControlsMixin,
    MediaPlayerEntity,
):
    """LinkPlayDevice Player Object."""

    def __init__(self,
                 name,
                 host,
                 protocol,
                 sources,
                 common_sources,
                 icecast_metadata,
                 multiroom_wifidirect,
                 led_off,
                 volume_step,
                 lastfm_api_key,
                 uuid,
                 state,
                 volume_offset: int = DEFAULT_VOLUME_OFFSET):
        """Initialize the media player.

        ``self.hass`` is populated by Home Assistant when the entity is
        added; the constructor no longer takes it as a parameter.
        """
        self._uuid = uuid
        self._fw_ver = '1.0.0'
        self._mcu_ver = ''
        requester = AiohttpRequester(UPNP_TIMEOUT)
        self._factory = UpnpFactory(requester)
        self._upnp_device = None
        self._service = None
        self._features = None
        self._preset_key = 4
        self._name = name
        self._host = host
        self._protocol = protocol
        self._icon = ICON_DEFAULT
        self._state = state
        self._volume = 0
        self._volume_step = volume_step
        # Per-device volume offset (signed percentage points, -100..+100)
        # applied on top of the master target by linkplay.set_group_volume.
        # Mirrors mini-media-player's ``volume_offset`` config option.
        self._volume_offset = volume_offset
        self._led_off = led_off
        self._fadevol = False
        self._source = None
        self._prev_source = None
        if sources is not None and sources != {}:
            self._source_list = loads(dumps(sources).strip('[]'))
        else:
            self._source_list = SOURCES.copy()
        if common_sources is not None and common_sources != {}:
            commonsources = loads(dumps(common_sources).strip('[]'))
            localsources = self._source_list
            self._source_list = {**localsources, **commonsources}
        self._sound_mode = None
        self._muted = False
        self._playhead_position = 0
        self._duration = 0
        self._position_updated_at = None
        self._spotify_paused_at = None
        self._idletime_updated_at = None
        self._shuffle = False
        self._repeat = RepeatMode.OFF
        self._media_album = None
        self._media_artist = None
        self._media_prev_artist = None
        self._media_title = None
        self._media_prev_title = None
        self._media_image_url = None
        self._media_uri = None
        self._media_uri_final = None
        self._media_source_uri = None
        self._nometa = False
        self._player_statdata = {}
        self._lastfm_api_key = lastfm_api_key
        self._first_update = True
        self._slave_mode = False
        self._slave_ip = None
        self._trackq = []
        self._trackc = None
        self._master = None
        self._is_master = False
        self._wifi_channel = None
        self._ssid = None
        self._playing_localfile = True
        self._playing_stream = False
        self._playing_liveinput = False
        self._playing_spotify = False
        self._playing_webplaylist = False
        self._playing_tts = False
        self._playing_mediabrowser = False
        self._slave_list = None
        self._multiroom_wifidirect = multiroom_wifidirect
        self._multiroom_group = []
        self._multiroom_prevsrc = None
        self._multiroom_unjoinat = None
        # Timestamp of the last successful ``async_join`` that
        # populated ``_multiroom_group``. The master-side poll uses
        # this to keep the just-built group through a brief grace
        # window when ``multiroom:getSlaveList`` still reports zero
        # slaves (WiFi-direct propagates slowly on AudioPro firmware).
        self._multiroom_joinat = None
        self._wait_for_mcu = 0
        self._new_song = True
        self._unav_throttle = False
        self._icecast_name = None
        self._icecast_meta = icecast_metadata
        self._ice_skip_throt = False
        # Last SomaFM station name we fetched track info for; used to
        # bypass the SomaFM @Throttle when the user switches stations.
        self._somafm_cached_station: str | None = None
        # Most-recent (mode, status, totlen, Title, Artist, Album) tuple
        # we logged; used to suppress repeating per-poll debug lines.
        self._last_poll_snapshot: tuple | None = None
        self._snapshot_active = False
        self._snap_source = None
        self._snap_uri = None
        self._snap_state = STATE_UNKNOWN
        self._snap_volume = 0
        self._snap_spotify = False
        self._snap_spotify_volumeonly = False
        self._snap_nometa = False
        self._snap_playing_mediabrowser = False
        self._snap_media_source_uri = None
        self._snap_seek = False
        self._snap_playhead_position = 0

    async def async_added_to_hass(self):
        """Record entity."""
        if self not in self.hass.data[DOMAIN].entities:
            self.hass.data[DOMAIN].entities.append(self)

    async def async_will_remove_from_hass(self):
        """Drop entity reference on unload."""
        with contextlib.suppress(ValueError):
            self.hass.data[DOMAIN].entities.remove(self)

    async def async_update(self):
        """Update state."""

        # If we couldn't determine our protocol on startup, then attempt to do it now as our speaker might be available
        if self._protocol is None:
            device_status = await self.call_linkplay_httpapi("getStatusEx", True, "https")
            if device_status is not None and device_status:
                self._protocol = "https"
            else:
                device_status = await self.call_linkplay_httpapi("getStatus", True, "http")
                if device_status is not None and device_status:
                    self._protocol = "http"
                else:
                    return False
        # If we believe we are a slave but the python ref to the master has
        # been lost (e.g. master entity reloaded), try to re-resolve it from
        # the registered entities before assuming we're no longer in a group.
        # Only clear slave_mode as a last resort: status['type']!=0 below
        # will correct it on the next poll if the device disagrees.
        if self._slave_mode and self._master is None and self._multiroom_group:
            master_eid = self._multiroom_group[0]
            for entity in self.hass.data[DOMAIN].entities:
                if entity.entity_id == master_eid and entity is not self:
                    self._master = entity
                    break

        if self._slave_mode and self._master is None and not self._multiroom_group:
            # No way to recover: not a slave anymore.
            self._slave_mode = False

        if self._slave_mode: # or self._snapshot_active:
            return True

        if self._multiroom_unjoinat is not None:
            waittim = MROOM_UJWDIR if self._multiroom_wifidirect else MROOM_UJWROU

            if utcnow() <= (self._multiroom_unjoinat + waittim):
                self._source = None
                self._media_title = None
                self._media_artist = None
                self._media_uri = None
                self._media_uri_final = None
                self._media_image_url = None
                self._state = STATE_IDLE
                return True
            else:
                self._multiroom_unjoinat = None
                self._playhead_position = 0
                self._duration = 0
                self._position_updated_at = utcnow()
                self._idletime_updated_at = self._position_updated_at
#                await self.async_restore_previous_source()
                await self.async_select_source(self._multiroom_prevsrc)
                self._multiroom_prevsrc = None
                return True

        # if self._wait_for_mcu > 0:  # have waited for the hardware unit to finish processing command, otherwise some reported status values will be incorrect
            # await asyncio.sleep(self._wait_for_mcu)

        if self._unav_throttle:
            await self.async_get_status()
        else:
            await self.async_get_status(no_throttle=True)

        if self._player_statdata is None:
            _LOGGER.debug("First update/No response from api: %s, %s", self.entity_id, self._player_statdata)
            return True

        if isinstance(self._player_statdata, dict):
            self._unav_throttle = False
            if self._first_update or (self._state == STATE_UNAVAILABLE or self._multiroom_wifidirect):
                if self._protocol == "https":
                    device_status = await self.call_linkplay_httpapi("getStatusEx", True)
                else:
                    device_status = await self.call_linkplay_httpapi("getStatus", True)
                if device_status is not None and isinstance(device_status, dict):
                    if self._state == STATE_UNAVAILABLE:
                        self._state = STATE_IDLE
                    self._wifi_channel = device_status['WifiChannel']
                    self._ssid = binascii.hexlify(device_status['ssid'].encode('utf-8'))
                    self._ssid = self._ssid.decode()

                    with contextlib.suppress(KeyError):
                        self._uuid = device_status['uuid']
                    with contextlib.suppress(KeyError):
                        self._name = device_status['DeviceName']
                    self._fw_ver = device_status.get('firmware', '1.0.0')
                    self._mcu_ver = device_status.get('mcu_ver', '')
                    try:
                        self._preset_key = int(device_status['preset_key'])
                    except KeyError:
                        self._preset_key = 4

                    if (
                        self._led_off
                        and self._uuid
                        and self._uuid.startswith(UUID_ARYLIC)
                        and self._fwvercheck(self._fw_ver) >= self._fwvercheck(FW_RAKOIT_UART_MIN)
                    ):
                        value = await self.call_linkplay_tcpuart('MCU+PAS+RAKOIT:LED:0&')
                        _LOGGER.debug("LED turn off: %s, %s, response: %s", self.entity_id, self._name, value)

                    if (
                        not self._multiroom_wifidirect
                        and self._fw_ver
                        and self._fwvercheck(self._fw_ver) < self._fwvercheck(FW_MROOM_RTR_MIN)
                    ):
                        self._multiroom_wifidirect = True

                    # UPnP / first-update init runs for *every* device,
                    # not just the old-firmware force-wifidirect path.
                    # Previously these blocks were nested under the
                    # condition above and silently no-op'd on modern
                    # firmware, so _upnp_device stayed None forever and
                    # async_update_via_upnp short-circuited (taking
                    # Spotify / TuneIn metadata with it).
                    if self._upnp_device is None:
                        url = f"http://{self._host}:49152/description.xml"
                        try:
                            self._upnp_device = await self._factory.async_create_device(url)
                        except Exception as error:
                            _LOGGER.warning(
                                "Failed communicating with LinkPlayDevice (UPnP) '%s': %s",
                                self._name, type(error),
                            )

                    if self._first_update:
                        self._duration = 0
                        self._playhead_position = 0
                        self._idletime_updated_at = utcnow()
                        if "udisk" in self._source_list:
                            await self.async_tracklist_via_upnp("USB")
                        self._first_update = False

            self._position_updated_at = utcnow()

            if self._player_statdata['type'] == '0':
                self._slave_mode = False

            if self._multiroom_group == [] and not self._slave_mode:
                self._is_master = False
                self._master = None

            # TODO: https://github.com/phedoreanu/home-assistant-custom-components-linkplay/compare/master...akloeckner:home-assistant-custom-components-linkplay:dev
            # Only clear group state on standalone devices. Slaves keep the
            # group pushed by their master; masters keep what they polled.
            if not self._is_master and not self._slave_mode:
                self._master = None
                self._multiroom_group = []
            self._volume = self._player_statdata['vol']
            self._muted = bool(int(self._player_statdata['mute']))
            self._sound_mode = SOUND_MODES.get(self._player_statdata['eq'])

            self._shuffle = {
                '2': True,
                '3': True,
                '5': True,
            }.get(self._player_statdata['loop'], False)

            self._repeat = {
                '0': RepeatMode.ALL,
                '1': RepeatMode.ONE,
                '2': RepeatMode.ALL,
                '5': RepeatMode.ONE,
            }.get(self._player_statdata['loop'], RepeatMode.OFF)

            if self._player_statdata['mode'] in ['-1', '0', '99'] or self._player_statdata['status'] == 'stop':
                if utcnow() >= (self._idletime_updated_at + AUTOIDLE_STATE_TIMEOUT):
                    self._state = STATE_IDLE
            elif self._player_statdata['status'] in ['play', 'load']:
                self._state = STATE_PLAYING
            elif self._player_statdata['status'] == 'pause':
                self._state = STATE_PAUSED

            if self._state in [STATE_PLAYING, STATE_PAUSED]:
                self._duration = int(int(self._player_statdata['totlen']) / 1000)
                self._playhead_position = int(int(self._player_statdata['curpos']) / 1000)
            else:
                self._duration = 0
                self._playhead_position = 0

            # Per-poll debug is rate-limited to actual state changes so the
            # 3s scan interval doesn't fill the log with identical lines.
            poll_snapshot = (
                self._player_statdata.get('mode'),
                self._player_statdata.get('status'),
                self._player_statdata.get('totlen'),
                self._player_statdata.get('Title'),
                self._player_statdata.get('Artist'),
                self._player_statdata.get('Album'),
            )
            if poll_snapshot != self._last_poll_snapshot:
                _LOGGER.debug(
                    "[%s @ %s] poll mode=%s status=%s totlen=%s uri=%r "
                    "Title=%r Artist=%r Album=%r",
                    self._name, self._host,
                    *poll_snapshot[:3],
                    self._player_statdata.get('uri'),
                    *poll_snapshot[3:],
                )
                self._last_poll_snapshot = poll_snapshot
            self._playing_spotify = bool(self._player_statdata['mode'] == '31')
            self._playing_liveinput = self._player_statdata['mode'] in SOURCES_LIVEIN
            self._playing_stream = self._player_statdata['mode'] in SOURCES_STREAM
            self._playing_localfile = self._player_statdata['mode'] in SOURCES_LOCALF

            if bool(self._player_statdata['mode'] != '10'):
                self._playing_mediabrowser = False

            if not (self._playing_liveinput or self._playing_stream or self._playing_spotify):
                self._playing_localfile = True

            try:
                if self._playing_stream and self._player_statdata['uri'] != "":
                    _LOGGER.debug("06 Update URI final detect %s, %s", self.entity_id, self._name)
                    try:
                        self._media_uri_final = str(bytearray.fromhex(self._player_statdata['uri']).decode('utf-8'))
                    except ValueError:
                        self._media_uri_final = self._player_statdata['uri']
                    if not self._media_uri:
                        self._media_uri = self._media_uri_final
            except KeyError:
                pass

            if self._media_uri:
                # Detect web music service by their CDN subdomains in the URL
                # Tidal, Deezer
                self._playing_webplaylist = \
                    bool(self._media_uri.find('audio.tidal.') != -1) or \
                    bool(self._media_uri.find('.dzcdn.') != -1) or \
                    bool(self._media_uri.find('.deezer.') != -1)

            if not self._playing_webplaylist:
                source_t = SOURCES_MAP.get(self._player_statdata['mode'], 'Network')
                source_n = None
                if source_t == 'Network':
                    if self._media_uri:
                        source_n = self._source_list.get(self._media_uri, 'Network')
                else:
                    source_n = self._source_list.get(source_t, None)

                if source_n is not None:
                    self._source = source_n
                else:
                    self._source = source_t
            else:
                self._source = 'Web playlist'

            if self._source != 'Network' and not (self._playing_stream or self._playing_localfile or self._playing_spotify):
                if self._source == 'Idle':
                    self._state = STATE_IDLE
                    self._media_title = None
                else:
                    self._state = STATE_PLAYING
                    self._media_title = self._source

                self._media_artist = None
                self._media_album = None
                self._media_image_url = None
                self._icecast_name = None

            if self._player_statdata['mode'] in ['1', '2', '3']:
                self._state = STATE_PLAYING
                self._media_title = self._source

            if self._playing_spotify and self._state == STATE_IDLE:
                self._source = None

            if (
                self._spotify_paused_at is not None
                and utcnow() >= (self._spotify_paused_at + SPOTIFY_PAUSED_TIMEOUT)
            ):
                # Prevent sticking in Pause mode for a long time (Spotify doesn't have a stop button on the app)
                await self.async_media_stop()
                return True

            if self._player_statdata['mode'] in ['11', '16'] and len(self._trackq) <= 0:
                if int(self._player_statdata['curpos']) > 6000 and self._state == STATE_PLAYING:
                    await self.async_tracklist_via_upnp("USB")

            if self._playing_spotify:
                if self._state != STATE_IDLE:
                    await self.async_update_via_upnp()
                if self._state == STATE_PAUSED:
                    if self._spotify_paused_at is None:
                        self._spotify_paused_at = utcnow()
                else:
                    self._spotify_paused_at = None
            # else:
            elif self._playing_webplaylist:
                if self._state != STATE_IDLE:
                    await self.async_update_via_upnp()

            else:
                self._spotify_paused_at = None
                if self._state not in [STATE_PLAYING, STATE_PAUSED]:
                    self._media_title = None
                    self._media_artist = None
                    self._media_album = None
                    self._media_image_url = None
                    self._icecast_name = None
                    self._playing_tts = False
                    self._somafm_cached_station = None

                if self._playing_localfile and self._state in [STATE_PLAYING, STATE_PAUSED] and not self._playing_tts:
                    await self.async_get_playerstatus_metadata(self._player_statdata)

                    if self._media_title is not None and self._media_artist is None:
                        querywords = self._media_title.split('.')
                        resultwords  = [word for word in querywords if word.lower() not in CUT_EXTENSIONS]
                        title = ' '.join(resultwords)
                        title = title.replace('_', ' ')
                        if title.find(' - ') != -1:
                            titles = title.split(' - ')
                            self._media_artist = string.capwords(titles[0].strip().strip('-'))
                            self._media_title = string.capwords(titles[1].strip().strip('-'))
                        else:
                            self._media_title = string.capwords(title.strip().strip('-'))
                    else:
                        self._media_title = self._source

                elif self._state == STATE_PLAYING and self._media_uri and int(self._player_statdata['totlen']) > 0 and not self._snapshot_active and not self._playing_tts and not self._playing_mediabrowser:
                    if not self._nometa:
                        await self.async_get_playerstatus_metadata(self._player_statdata)

                elif self._state == STATE_PLAYING and self._playing_stream and int(self._player_statdata['totlen']) <= 0 and not self._snapshot_active and not self._playing_tts:
                    # Live stream. Detect SomaFM-via-TuneIn first
                    # because the device only exposes the station name
                    # in playerstatus and the icecast / UPnP DIDL
                    # paths also fail on that firmware. If we let
                    # playerstatus run, it wipes the artist/title that
                    # SomaFM populated on a previous poll - so for
                    # SomaFM stations we go straight to async_update_from_somafm
                    # and rely on the @Throttle cache between fetches.
                    raw_title = self._player_statdata.get('Title', '')
                    decoded_title = decode_hex_utf8(raw_title) if raw_title else ''
                    # Detection priority:
                    #   1. raw playerstatus Title (most authoritative,
                    #      populated after a station change),
                    #   2. previously-detected cached station name
                    #      (sticky: survives _media_title being
                    #      overwritten with the track title by a
                    #      successful SomaFM JSON fetch),
                    #   3. current _media_title (bootstraps detection
                    #      from UPnP DIDL on the first poll after
                    #      pressing play, when raw Title is still empty).
                    somafm_title = (
                        decoded_title
                        or self._somafm_cached_station
                        or self._media_title
                        or ''
                    )
                    is_somafm = somafm_channel_slug(somafm_title) is not None

                    if is_somafm:
                        # Compare case-insensitively: firmware sometimes
                        # alternates casing of the same station name
                        # between polls ("Beat Blender" vs "beat blender"),
                        # which would otherwise trigger a "station changed"
                        # storm and wipe the artist on every cycle.
                        cached_norm = (self._somafm_cached_station or "").lower()
                        station_changed = somafm_title.lower() != cached_norm
                        if station_changed:
                            # Drop the now-stale track info from the
                            # previous station so the card doesn't show
                            # "Drone Zone" with "Kodomo / Spira
                            # Mirabilis" while Beat Blender is loading.
                            self._media_title = string.capwords(somafm_title)
                            self._media_artist = None
                            self._media_album = None
                            self._media_image_url = None
                            self._somafm_cached_station = somafm_title
                            # Bypass @Throttle so the new station's
                            # track shows up on the next render.
                            result = await self.async_update_from_somafm(no_throttle=True)
                        else:
                            result = await self.async_update_from_somafm()

                        if result is None:
                            # Throttled: previous artist + title still
                            # in place. No log here - per-poll trace
                            # is suppressed via the poll-snapshot dedupe.
                            got_meta = self._media_artist is not None
                        else:
                            got_meta = bool(result)
                            _LOGGER.debug(
                                "[%s @ %s] SomaFM JSON -> title=%r artist=%r ok=%s "
                                "(station_changed=%s)",
                                self._name, self._host,
                                self._media_title, self._media_artist, got_meta,
                                station_changed,
                            )
                    else:
                        # Non-SomaFM live stream: cheapest-first chain.
                        # Run silently; result is captured by the next
                        # per-poll snapshot. Detailed trace fires only
                        # once per metadata change.
                        prev = (self._media_title, self._media_artist)
                        got_meta = await self.async_get_playerstatus_metadata(self._player_statdata)
                        if not got_meta and self._upnp_device is not None:
                            try:
                                await self.async_update_via_upnp()
                            except Exception as error:
                                _LOGGER.debug(
                                    "[%s @ %s] UPnP DIDL exception: %s",
                                    self._name, self._host, error,
                                )
                            got_meta = self._media_title is not None and self._media_artist is not None
                        if not got_meta and self._media_uri_final:
                            if self._ice_skip_throt:
                                await self.async_update_from_icecast(no_throttle=True)
                                self._ice_skip_throt = False
                            else:
                                await self.async_update_from_icecast()
                        new = (self._media_title, self._media_artist)
                        if new != prev:
                            _LOGGER.debug(
                                "[%s @ %s] live-stream metadata changed: %r -> %r",
                                self._name, self._host, prev, new,
                            )

                elif self._state == STATE_PLAYING and self._playing_mediabrowser and self._media_source_uri is not None:
                    if not self._nometa:
                        await self.async_get_local_mediasource_metadata_from_path()

                self._new_song = await self.async_is_playing_new_track()
                if self._lastfm_api_key is not None and self._new_song:
                    await self.async_get_lastfm_coverart()
                # iTunes Search artwork: fire on every track change, not
                # only the SomaFM-fetcher path - non-SomaFM streams with
                # firmware-supplied title/artist also benefit from a
                # real album cover instead of the station logo.
                if self._new_song:
                    itunes = getattr(self, "async_get_itunes_artwork", None)
                    if itunes is not None:
                        try:
                            await itunes()
                        except Exception as error:
                            _LOGGER.debug(
                                "[%s @ %s] iTunes art lookup raised: %s",
                                self._name, self._host, error,
                            )

            self._media_prev_artist = self._media_artist
            self._media_prev_title = self._media_title

        else:
            _LOGGER.error("Erroneous JSON during update and process self._player_statdata: %s, %s", self.entity_id, self._name)


        return await self._async_poll_multiroom_master_status()

    @property
    def name(self):
        """Return the name of the device, decorated with the master's name when this is a slave."""
        if self._slave_mode:
            for device in self.hass.data[DOMAIN].entities:
                if device.is_master:
                    return f"{self._name} [{device.name}]"
        return self._name

    @property
    def icon(self):
        """Return the icon of the device."""

        if self._playing_tts:
            return ICON_TTS

        if self._state in [STATE_PAUSED, STATE_UNAVAILABLE, STATE_IDLE, STATE_UNKNOWN]:
            return ICON_DEFAULT

        if self._muted:
            return ICON_MUTED

        if self._slave_mode or self._is_master:
            return ICON_MULTIROOM

        if self._source == "Bluetooth":
            return ICON_BLUETOOTH

        if self._source == "DLNA" or self._source == "Airplay" or self._source == "Spotify":
            return ICON_PUSHSTREAM

        if self._state == STATE_PLAYING:
            return ICON_PLAYING

        return ICON_DEFAULT

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return int(self._volume) / MAX_VOL

    @property
    def is_volume_muted(self):
        """Return boolean if volume is currently muted."""
        return self._muted

    @property
    def source(self):
        """Return the current input source."""
        if self._source not in ['Idle', 'Network']:
            return self._source
        else:
            return None

    @property
    def source_list(self):
        """Return the list of available input sources. Wi-Fi is the implicit source and is omitted."""
        source_list = self._source_list.copy()
        if 'wifi' in source_list:
            del source_list['wifi']

        if len(self._source_list) > 0:
            return list(source_list.values())
        else:
            return None

    @property
    def sound_mode(self):
        """Return the current sound mode."""
        return self._sound_mode

    @property
    def sound_mode_list(self):
        """Return the available sound modes."""
        return sorted(list(SOUND_MODES.values()))

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        if self._slave_mode and self._features:
            return self._features

        if self._playing_localfile or self._playing_spotify or self._playing_webplaylist:
            if self._state in [STATE_PLAYING, STATE_PAUSED]:
                self._features = (
                    MediaPlayerEntityFeature.SELECT_SOURCE
                    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
                    | MediaPlayerEntityFeature.PLAY_MEDIA
                    | MediaPlayerEntityFeature.GROUPING
                    | MediaPlayerEntityFeature.BROWSE_MEDIA
                    | MediaPlayerEntityFeature.VOLUME_SET
                    | MediaPlayerEntityFeature.VOLUME_STEP
                    | MediaPlayerEntityFeature.VOLUME_MUTE
                    | MediaPlayerEntityFeature.STOP
                    | MediaPlayerEntityFeature.PLAY
                    | MediaPlayerEntityFeature.PAUSE
                    | MediaPlayerEntityFeature.NEXT_TRACK
                    | MediaPlayerEntityFeature.PREVIOUS_TRACK
                    | MediaPlayerEntityFeature.SHUFFLE_SET
                    | MediaPlayerEntityFeature.REPEAT_SET
                    | MediaPlayerEntityFeature.SEEK
                )
            else:
                self._features = (
                    MediaPlayerEntityFeature.SELECT_SOURCE
                    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
                    | MediaPlayerEntityFeature.PLAY_MEDIA
                    | MediaPlayerEntityFeature.GROUPING
                    | MediaPlayerEntityFeature.BROWSE_MEDIA
                    | MediaPlayerEntityFeature.VOLUME_SET
                    | MediaPlayerEntityFeature.VOLUME_STEP
                    | MediaPlayerEntityFeature.VOLUME_MUTE
                    | MediaPlayerEntityFeature.STOP
                    | MediaPlayerEntityFeature.PLAY
                    | MediaPlayerEntityFeature.PAUSE
                    | MediaPlayerEntityFeature.NEXT_TRACK
                    | MediaPlayerEntityFeature.PREVIOUS_TRACK
                    | MediaPlayerEntityFeature.SHUFFLE_SET
                    | MediaPlayerEntityFeature.REPEAT_SET
                )

        elif self._playing_stream or self._playing_mediabrowser:
            self._features = (
                MediaPlayerEntityFeature.SELECT_SOURCE
                | MediaPlayerEntityFeature.SELECT_SOUND_MODE
                | MediaPlayerEntityFeature.PLAY_MEDIA
                | MediaPlayerEntityFeature.GROUPING
                | MediaPlayerEntityFeature.BROWSE_MEDIA
                | MediaPlayerEntityFeature.VOLUME_SET
                | MediaPlayerEntityFeature.VOLUME_STEP
                | MediaPlayerEntityFeature.VOLUME_MUTE
                | MediaPlayerEntityFeature.STOP
                | MediaPlayerEntityFeature.PLAY
                | MediaPlayerEntityFeature.PAUSE
                | MediaPlayerEntityFeature.SEEK
                )

        elif self._playing_liveinput:
            self._features = (
                MediaPlayerEntityFeature.SELECT_SOURCE
                | MediaPlayerEntityFeature.SELECT_SOUND_MODE
                | MediaPlayerEntityFeature.PLAY_MEDIA
                | MediaPlayerEntityFeature.GROUPING
                | MediaPlayerEntityFeature.BROWSE_MEDIA
                | MediaPlayerEntityFeature.VOLUME_SET
                | MediaPlayerEntityFeature.VOLUME_STEP
                | MediaPlayerEntityFeature.VOLUME_MUTE
                | MediaPlayerEntityFeature.STOP
                )

        return self._features

    @property
    def media_position(self):
        """Time in seconds of current playback head position."""
        if (self._playing_localfile or self._playing_spotify or self._slave_mode or self._playing_mediabrowser) and self._state != STATE_UNAVAILABLE:
            return self._playhead_position
        else:
            return None

    @property
    def media_duration(self):
        """Time in seconds of current song duration."""
        if (self._playing_localfile or self._playing_spotify or self._slave_mode or self._playing_mediabrowser) and self._state != STATE_UNAVAILABLE:
            return self._duration
        else:
            return None

    @property
    def media_position_updated_at(self):
        """When the seek position was last updated."""
        if not self._playing_liveinput and self._state == STATE_PLAYING:
            return self._position_updated_at
        else:
            return None

    @property
    def shuffle(self):
        """Return True if shuffle mode is enabled."""
        return self._shuffle

    @property
    def repeat(self):
        """Return repeat mode."""
        return self._repeat

    @property
    def media_title(self):
        """Return title of the current track."""
        return self._media_title

    @property
    def media_artist(self):
        """Return name of the current track artist."""
        return self._media_artist

    @property
    def media_album_name(self):
        """Return name of the current track album."""
        return self._media_album

    @property
    def media_image_url(self):
        """Return name the image for the current track."""
        return self._media_image_url

    @property
    def media_content_type(self):
        """Content type of current playing media. Has to be MediaType.MUSIC in order for Lovelace to show both artist and title."""
        return MediaType.MUSIC

    @property
    def ssid(self):
        """SSID to use for multiroom configuration."""
        return self._ssid

    @property
    def wifi_channel(self):
        """Wi-Fi channel used for multiroom configuration."""
        return self._wifi_channel

    @property
    def slave_ip(self):
        """Ip used in multiroom configuration."""
        return self._slave_ip

    @property
    def device_class(self) -> MediaPlayerDeviceClass:
        return MediaPlayerDeviceClass.SPEAKER

    @property
    def extra_state_attributes(self):
        """List members in group and set master and slave state."""
        attributes = {}
        if self._multiroom_group:
            attributes[ATTR_LINKPLAY_GROUP] = self._multiroom_group

        attributes[ATTR_MASTER] = self._is_master
        if self._slave_mode:
            attributes[ATTR_SLAVE] = self._slave_mode
        if self._media_uri_final:
            attributes[ATTR_STURI] = self._media_uri_final
        if len(self._trackq) > 0:
            attributes[ATTR_TRCNT] = len(self._trackq) - 1
        if self._trackc:
            attributes[ATTR_TRCRT] = self._trackc
        if self._uuid != '':
            attributes[ATTR_UUID] = self._uuid

        attributes[ATTR_TTS] = self._playing_tts
        attributes[ATTR_SNAPSHOT] = self._snapshot_active
        attributes[ATTR_SNAPSPOT] = self._snap_spotify

        if DEBUGSTR_ATTR:
            atrdbg = ""
            if self._playing_localfile:
                atrdbg = atrdbg + " _playing_localfile"

            if self._playing_spotify:
                atrdbg = atrdbg + " _playing_spotify"

            if self._playing_webplaylist:
                atrdbg = atrdbg + " _playing_webplaylist"

            if self._playing_stream:
                atrdbg = atrdbg + " _playing_stream"

            if self._playing_liveinput:
                atrdbg = atrdbg + " _playing_liveinput"

            if self._playing_tts:
                atrdbg = atrdbg + " _playing_tts"

            if self._playing_mediabrowser:
                atrdbg = atrdbg + " _playing_mediabrowser"

            attributes[ATTR_DEBUG] = atrdbg

        if self._state != STATE_UNAVAILABLE:
            attributes[ATTR_FWVER] = self._fw_ver + "." + self._mcu_ver

        return attributes

    @property
    def host(self):
        """Self ip."""
        return self._host

    @property
    def track_count(self):
        """List of tracks present on the device."""
        if len(self._trackq) > 0:
            return len(self._trackq) - 1
        else:
            return 0

    @property
    def unique_id(self):
        """Return the unique id, or None when no UUID has been discovered yet."""
        return f"linkplay_media_{self._uuid}" if self._uuid else None

    @property
    def fw_ver(self):
        """Return the firmware version number of the device."""
        return self._fw_ver

    async def async_play_media(self, media_type, media_id, **kwargs):
        """Play media from a URL or localfile."""
        return await self._async_play_media_impl(media_type, media_id, **kwargs)

    async def _async_play_media_impl(self, media_type, media_id, **kwargs):
        _LOGGER.debug("Trying to play media. Device: %s, Media_type: %s, Media_id: %s", self.entity_id, media_type, media_id)
        if not self._slave_mode:

            if not (media_type in [MediaType.MUSIC, MediaType.URL, MediaType.TRACK] or media_source.is_media_source_id(media_id)):
                _LOGGER.warning("For: %s Invalid media type %s. Only %s and %s is supported", self._name, media_type, MediaType.MUSIC, MediaType.URL)
                await self.async_media_stop()
                return False

            if not self._snapshot_active:
                self._playing_mediabrowser = False
                self._nometa = False

            if media_source.is_media_source_id(media_id):
                play_item = await media_source.async_resolve_media(self.hass, media_id, self.entity_id)
                if media_id.find('radio_browser') != -1:  # radios are an exception, be treated by server redirect checker and icecast metadata parser
                    self._playing_mediabrowser = False
                else:
                    self._playing_mediabrowser = True

                if media_id.find('media_source/local') != -1:
                    self._media_source_uri = media_id
                else:
                    self._media_source_uri = None

                media_id = play_item.url
                if play_item.mime_type not in ['audio/basic',
                                               'audio/mpeg',
                                               'audio/mp3',
                                               'audio/mpeg3',
                                               'audio/x-mpeg-3',
                                               'audio/x-mpegurl',
                                               'audio/mp4',
                                               'audio/aac',
                                               'audio/x-aac',
                                               'audio/x-hx-aac-adts',
                                               'audio/x-aiff',
                                               'audio/ogg',
                                               'audio/vorbis',
                                               'application/ogg',
                                               'audio/opus',
                                               'audio/webm',
                                               'audio/wav',
                                               'audio/x-wav',
                                               'audio/vnd.wav',
                                               'audio/flac',
                                               'audio/x-flac',
                                               'audio/x-ms-wma']:
                    _LOGGER.warning("For: %s Invalid media type, %s is not supported", self._name, play_item.mime_type)
                    self._playing_mediabrowser = False
                    return False

                media_id = async_process_play_media_url(self.hass, media_id)
                _LOGGER.debug("Trying to play HA media. Device: %s, Play_Item: %s, Media_id: %s", self._name, play_item, media_id)

            media_id_check = media_id.lower()

            if media_id_check.startswith('http'):
                media_type = MediaType.URL

            if media_id_check.endswith('.m3u') or media_id_check.endswith('.m3u8'):
                _LOGGER.debug("For: %s, Detected M3U list, Media_id: %s", self._name, media_id)
                media_id = await self.async_parse_m3u_url(media_id)

            if media_id_check.endswith('.pls'):
                _LOGGER.debug("For: %s, Detected PLS list, Media_id: %s", self._name, media_id)
                media_id = await self.async_parse_pls_url(media_id)

            media_id_final = media_id
            if media_type == MediaType.URL:
                if not self._playing_mediabrowser:
                    media_id_final = await self.async_detect_stream_url_redirection(media_id)

                if self._fwvercheck(self._fw_ver) >= self._fwvercheck(FW_SLOW_STREAMS) and self._state == STATE_PLAYING:
                    await self.call_linkplay_httpapi("setPlayerCmd:pause", None)

                if self._playing_spotify:  # disconnect from Spotify before playing new http source
                    await self.call_linkplay_httpapi("setPlayerCmd:switchmode:wifi", None)

                value = await self.call_linkplay_httpapi(f"setPlayerCmd:play:{media_id_final}", None)
                if value != "OK":
                    _LOGGER.warning("Failed to play media type URL. Device: %s, Got response: %s, Media_Id: %s", self.entity_id, value, media_id)
                    return False

            elif media_type in [MediaType.MUSIC, MediaType.TRACK]:
                value = await self.call_linkplay_httpapi(f"setPlayerCmd:playLocalList:{media_id}", None)
                if value != "OK":
                    _LOGGER.warning("Failed to play media type music. Device: %s, Got response: %s, Media_Id: %s", self.entity_id, value, media_id)
                    return False

            self._state = STATE_PLAYING
            if media_id.find('tts_proxy') != -1:
                self._playing_tts = True
                self._playing_mediabrowser = False
                self._playing_stream = False
            else:
                self._playing_tts = False
            self._media_title = None
            self._media_artist = None
            self._media_album = None
            self._icecast_name = None
            self._somafm_cached_station = None
            self._playhead_position = 0
            self._duration = 0
            self._trackc = None
            self._position_updated_at = utcnow()
            self._idletime_updated_at = self._position_updated_at
            self._media_image_url = None
            self._ice_skip_throt = True
            self._unav_throttle = False
            if media_type == MediaType.URL:
                self._media_uri = media_id
                self._media_uri_final = media_id_final
            elif media_type == MediaType.MUSIC:
                self._media_uri = None
                self._media_uri_final = None
                self._wait_for_mcu = 0.4
            return True

        if not self._snapshot_active:
            await self._master.async_play_media(media_type, media_id)
        return True

    async def async_select_source(self, source):
        """Select input source."""
        await self._async_select_source_impl(source)

    async def _async_select_source_impl(self, source):
        if not self._slave_mode:
            self._nometa = False
            temp_source = next((k for k in self._source_list if self._source_list[k] == source), None)
            if temp_source is None:
                return

            if self._playing_spotify:  # disconnect from Spotify before selecting new source
                if self._fwvercheck(self._fw_ver) >= self._fwvercheck(FW_SLOW_STREAMS):
                    await self.call_linkplay_httpapi("setPlayerCmd:pause", None)
                await self.call_linkplay_httpapi("setPlayerCmd:switchmode:wifi", None)

            if temp_source == "udisk":
                await self.async_tracklist_via_upnp("USB")

            prev_source = None
            if len(self._source_list) > 0:
                prev_source = next((k for k in self._source_list if self._source_list[k] == self._source), None)

            if prev_source and prev_source.startswith('http') and temp_source in ['line-in', 'line-in2', 'optical', 'bluetooth', 'co-axial', 'HDMI', 'cd', 'udisk', 'RCA']:
                self._wait_for_mcu = 1

            self._unav_throttle = False
            if temp_source.startswith('http'):
                temp_source_final = await self.async_detect_stream_url_redirection(temp_source)

                if self._fwvercheck(self._fw_ver) >= self._fwvercheck(FW_SLOW_STREAMS) and self._state == STATE_PLAYING:
                    await self.call_linkplay_httpapi("setPlayerCmd:pause", None)  #recent firmwares don't stop the previous stream while loading the new one, can take several seconds

                value = await self.call_linkplay_httpapi(f"setPlayerCmd:play:{temp_source_final}", None)
                if value == "OK":
                    self._state = STATE_PLAYING
                    if prev_source and prev_source.find('http') == -1:
                        self._wait_for_mcu = 2  # switching from live to stream input -> time to report correct volume value at update
                    else:
                        self._wait_for_mcu = 0.5
                    self._playing_tts = False
                    self._source = source
                    self._media_uri = temp_source
                    self._media_uri_final = temp_source_final
                    self._playhead_position = 0
                    self._duration = 0
                    self._trackc = None
                    self._position_updated_at = utcnow()
                    self._idletime_updated_at = self._position_updated_at
                    self._media_title = None
                    self._media_artist = None
                    self._media_album = None
                    self._icecast_name = None
                    self._media_image_url = None
                    self._ice_skip_throt = True
                    if self._slave_list is not None:
                        for slave in self._slave_list:
                            await slave.async_set_source(source)
                else:
                    _LOGGER.warning("Failed to select http source and play. Device: %s, Got response: %s", self.entity_id, value)
            else:
                value = await self.call_linkplay_httpapi(f"setPlayerCmd:switchmode:{temp_source}", None)
                if value == "OK":
                    self._state = STATE_PLAYING
                    # if temp_source and temp_source in ['udisk', 'TFcard']:
                    # else:
                    self._source = source
                    self._media_uri = None
                    self._media_uri_final = None
                    self._playhead_position = 0
                    self._duration = 0
                    self._trackc = None
                    self._position_updated_at = utcnow()
                    self._idletime_updated_at = self._position_updated_at
                    if self._slave_list is not None:
                        for slave in self._slave_list:
                            await slave.async_set_source(source)
                else:
                    _LOGGER.warning("Failed to select source. Device: %s, Got response: %s", self.entity_id, value)
        else:
            await self._master.async_select_source(source)

    async def async_select_sound_mode(self, sound_mode):
        """Set Sound Mode for device."""
        if not self._slave_mode:
            mode = list(SOUND_MODES.keys())[list(
                SOUND_MODES.values()).index(sound_mode)]
            value = await self.call_linkplay_httpapi(f"setPlayerCmd:equalizer:{mode}", None)
            if value == "OK":
                self._sound_mode = sound_mode
                if self._slave_list is not None:
                    for slave in self._slave_list:
                        await slave.async_set_sound_mode(sound_mode)
            else:
                _LOGGER.warning("Failed to set sound mode. Device: %s, Got response: %s", self.entity_id, value)
        else:
            await self._master.async_select_sound_mode(sound_mode)

    async def async_set_shuffle(self, shuffle):
        """Change the shuffle mode."""
        if not self._slave_mode:
            mode = '0'
            if shuffle:
                self._shuffle = shuffle
                mode = '2'
            elif self._repeat == RepeatMode.ALL:
                mode = '3'
            elif self._repeat == RepeatMode.ONE:
                mode = '1'
            value = await self.call_linkplay_httpapi(f"setPlayerCmd:loopmode:{mode}", None)
            if value != "OK":
                _LOGGER.warning("Failed to change shuffle mode. Device: %s, Got response: %s", self.entity_id, value)
        else:
            await self._master.async_set_shuffle(shuffle)

    async def async_set_repeat(self, repeat):
        """Change the repeat mode."""
        if not self._slave_mode:
            self._repeat = repeat
            mode = '0'
            if repeat == RepeatMode.ALL:
                mode = '2' if self._shuffle else '3'
            elif repeat == RepeatMode.ONE:
                mode = '1'
            value = await self.call_linkplay_httpapi(f"setPlayerCmd:loopmode:{mode}", None)
            if value != "OK":
                _LOGGER.warning("Failed to change repeat mode. Device: %s, Got response: %s", self.entity_id, value)
        else:
            await self._master.async_set_repeat(repeat)

    async def async_get_local_mediasource_metadata_from_path(self):
        if self._media_source_uri is not None:
            rootdir = "media-source://media_source/local/"
            self._trackc = self._media_source_uri.replace(rootdir, '')
            titleuri = self._trackc.split('/')
            if len(titleuri) > 1:
                titles = titleuri[-2:]
                self._media_artist = string.capwords(titles[0].strip().strip('-').replace('_', ' '))
                self._media_title = string.capwords(titles[1].strip().strip('-').replace('_', ' '))
            else:
                self._media_title = string.capwords(titleuri[0].strip().strip('-').replace('_', ' '))
            querywords = self._media_title.split('.')
            resultwords  = [word for word in querywords if word.lower() not in CUT_EXTENSIONS]
            self._media_title = ' '.join(resultwords)
            return True
        else:
            return False

    async def async_get_playerstatus_metadata(self, plr_stat):
        try:
            if plr_stat['uri'] != "":
                self._trackc = decode_hex_utf8(plr_stat['uri']).replace(ROOTDIR_USB, '')
        except KeyError:
            pass

        title = parse_player_status_field(plr_stat.get('Title', ''))
        if title is not None:
            self._media_title = title
            if self._trackc is None:
                self._trackc = self._media_title
        elif plr_stat.get('Title') == '':
            pass  # leave previous value
        else:
            self._media_title = None

        artist = parse_player_status_field(plr_stat.get('Artist', ''))
        if artist is not None:
            self._media_artist = artist
        elif plr_stat.get('Artist') == '':
            pass
        else:
            self._media_artist = None

        album = parse_player_status_field(plr_stat.get('Album', ''))
        if album is not None:
            self._media_album = album
        elif plr_stat.get('Album') == '':
            pass
        else:
            self._media_album = None

        return self._media_title is not None and self._media_artist is not None

    @staticmethod
    def _fwvercheck(v):
        return tuple(point.zfill(8) for point in v.split("."))

    async def async_is_playing_new_track(self):
        """Check if track is changed since last update."""
        if self._playing_mediabrowser and self._media_source_uri is not None:
            # don't trigger new track flag for local mediabrowser files
            return False

        if self._icecast_name is not None:
            import unicodedata
            artmed = unicodedata.normalize('NFKD', str(self._media_artist) + str(self._media_title)).lower()
            artmedd = "".join([c for c in artmed if not unicodedata.combining(c)])
            if artmedd.find(self._icecast_name.lower()) != -1 or artmedd.find(self._source.lower()) != -1:
                # don't trigger new track flag for icecast streams where track name contains station name or source name; save some energy by not quering last.fm with this
                self._media_image_url = None
                return False

        return (
            self._media_artist != self._media_prev_artist
            or self._media_title != self._media_prev_title
        )

    async def async_preset_button(self, preset):
        """Simulate pressing a physical preset button."""
        if self._preset_key is None or preset is None:
            return
        if self._slave_mode:
            await self._master.async_preset_button(preset)
            return
        if not (0 < int(preset) <= self._preset_key):
            _LOGGER.warning(
                "Wrong preset number %s. Device: %s, has to be integer between 1 and %s",
                self.entity_id, preset, self._preset_key,
            )
            return
        await self._async_preset_button_impl(preset)

    async def _async_preset_button_impl(self, preset):
        # Snapshot the master's intended volume before MCUKeyShortClick.
        # AudioPro firmware restores the per-source saved volume on a
        # preset switch, overriding whatever the user just set via
        # set_group_volume / volume_set. Re-apply our locally tracked
        # _volume after the switch so the firmware HW + HA cache match
        # what the user asked for.
        intended_vol = int(self._volume) if self._volume is not None else None
        value = await self.call_linkplay_httpapi(f"MCUKeyShortClick:{preset!s}", None)
        if value != "OK":
            _LOGGER.warning(
                "Failed to recall preset %s. Device: %s, Got response: %s",
                self.entity_id, preset, value,
            )
            return
        if intended_vol is not None:
            await asyncio.sleep(0.3)
            await self._set_volume_on_device(intended_vol, action="preset_restore_vol")
            # Group members: re-apply each slave's offset-adjusted target
            # so the firmware's per-source volume restore on the master
            # doesn't desync the group either.
            if self._is_master and self._multiroom_group:
                by_eid = {
                    d.entity_id: d
                    for d in self.hass.data[DOMAIN].entities
                }
                for eid in self._multiroom_group:
                    device = by_eid.get(eid)
                    if device is None or device is self:
                        continue
                    offset = getattr(device, "_volume_offset", 0) or 0
                    target_pct = max(0, min(100, intended_vol + offset))
                    await device._set_volume_on_device(
                        target_pct, action="preset_restore_slave_vol",
                    )

    async def async_play_track(self, track):
        """Play media track by name found in the tracks list."""
        if len(self._trackq) <= 0 or track is None:
            return False

        track.hass = self.hass   # render template
        trackn = track.async_render()

        if not self._slave_mode:
            try:
                index = next(idx for idx, s in enumerate(self._trackq) if trackn in s)
            except StopIteration:
                return False

            if index <= 0:
                return False

            value = await self.call_linkplay_httpapi(f"setPlayerCmd:playLocalList:{index}", None)
            if value != "OK":
                _LOGGER.warning("Failed to play media track by name. Device: %s, Got response: %s", self.entity_id, value)
                return False
            else:
                self._state = STATE_PLAYING
                self._playing_tts = False
                self._media_title = None
                self._media_artist = None
                self._media_album = None
                self._trackc = None
                self._icecast_name = None
                self._playhead_position = 0
                self._duration = 0
                self._position_updated_at = utcnow()
                self._media_image_url = None
                self._media_uri = None
                self._media_uri_final = None
                self._ice_skip_throt = False
                self._unav_throttle = False
                return True
        await self._master.async_play_track(track)
        return True

    _USB_DISK_ROOT_ID = "linkplay_udisk"

    async def async_browse_media(self, media_content_type=None, media_content_id=None):
        """Implement the websocket media browsing helper.

        Surfaces two sources:

        * Home Assistant media sources (HA media_source integration).
        * If this LinkPlay device has a USB disk attached and reported a
          track queue, an additional ``USB Disk`` folder listing each
          track. Tracks are referenced by 1-based index in the queue so
          ``play_media`` with ``MediaType.MUSIC`` plays the correct file.
        """
        if media_content_id == self._USB_DISK_ROOT_ID:
            return self._build_udisk_browse()

        ha_sources = await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

        if media_content_id is not None or not self._has_udisk_tracks():
            return ha_sources

        # At the root level, append the device's USB disk as a child so it
        # sits next to HA's media sources.
        udisk_root = BrowseMedia(
            title=self._source_list.get("udisk", "USB Disk"),
            media_class=MediaClass.DIRECTORY,
            media_content_id=self._USB_DISK_ROOT_ID,
            media_content_type="listing",
            can_play=False,
            can_expand=True,
            thumbnail=None,
        )
        children = list(ha_sources.children or [])
        children.append(udisk_root)
        ha_sources.children = children
        return ha_sources

    def _has_udisk_tracks(self) -> bool:
        return bool(self._trackq) and "udisk" in self._source_list

    def _build_udisk_browse(self) -> "BrowseMedia":
        """Return the BrowseMedia subtree listing tracks on the USB disk."""
        tracks = [
            BrowseMedia(
                title=track,
                media_class=MediaClass.MUSIC,
                media_content_id=str(index),
                media_content_type=MediaType.MUSIC,
                can_play=True,
                can_expand=False,
            )
            for index, track in enumerate(self._trackq, start=1)
        ]
        return BrowseMedia(
            title=self._source_list.get("udisk", "USB Disk"),
            media_class=MediaClass.DIRECTORY,
            media_content_id=self._USB_DISK_ROOT_ID,
            media_content_type="listing",
            can_play=False,
            can_expand=True,
            children=tracks,
        )
