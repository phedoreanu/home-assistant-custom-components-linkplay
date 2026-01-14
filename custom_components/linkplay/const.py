"""Constants for Linkplay integration."""

DOMAIN = "linkplay"

# Configuration Constants
CONF_ICECAST_METADATA = "icecast_metadata"
CONF_MULTIROOM_WIFIDIRECT = "multiroom_wifidirect"
CONF_LEDOFF = "led_off"
CONF_VOLUME_STEP = "volume_step"
CONF_SOURCES = "sources"

# Defaults
DEFAULT_ICECAST_UPDATE = "StationName"
DEFAULT_MULTIROOM_WIFIDIRECT = False
DEFAULT_LEDOFF = False
DEFAULT_VOLUME_STEP = 5
API_TIMEOUT = 10

ICECAST_METADATA_MODES = ["Off", "StationName", "StationNameSongTitle"]

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
