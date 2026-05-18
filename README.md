# Linkplay-based speakers and sound devices

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/phedoreanu/home-assistant-custom-components-linkplay?style=for-the-badge)](https://github.com/phedoreanu/home-assistant-custom-components-linkplay/releases)

Home Assistant custom integration for audio devices based on the Linkplay A31 chipset (Arylic, August, Audio Pro, iEAST, and many other brands — full list at the bottom).

Originally developed by nicjo814, maintained by limych, archived by nagyrobi, now maintained by phedoreanu.

Fully compatible with [Mini Media Player card](https://github.com/kalkih/mini-media-player) by kalkih, including speaker group management.

## Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Services](#services)
- [Multiroom](#multiroom)
- [SomaFM track metadata](#somafm-track-metadata)
- [Presets](#presets)
- [Specific commands](#specific-commands)
- [Snapshot and restore](#snapshot-and-restore)
- [Service call examples](#service-call-examples)
- [Automation examples](#automation-examples)
- [About Linkplay](#about-linkplay)
- [License](#home-assistant-component-license)

## Installation

### Via HACS (Recommended)
1. Open HACS in Home Assistant.
2. Go to "Integrations" section.
3. Click the 3 dots in the top right corner and select "Custom repositories".
4. Add `https://github.com/phedoreanu/home-assistant-custom-components-linkplay` as an "Integration".
5. Search for "Linkplay" and install it.
6. Restart Home Assistant.

### Manual Installation
1. Copy all files in `custom_components/linkplay` to your `<config directory>/custom_components/linkplay/` directory.
2. Restart Home Assistant.

## Configuration

### UI Configuration (Recommended)
Devices are automatically discovered via SSDP/Zeroconf. You should see them appear in **Settings → Devices & Services → Integrations**.

If a device is not discovered automatically:
1. Go to **Settings → Devices & Services**.
2. Click **+ ADD INTEGRATION** button.
3. Search for "Linkplay".
4. Select it and follow the instructions to add your device by IP address.

### Options (Advanced Settings)
Each device can be configured individually via the "Configure" button on the integration card:
- **Icecast Metadata**: Choose between `Off`, `StationName`, or `StationNameSongTitle`.
- **Multiroom Wi-Fi Direct**: Toggle to use Wi-Fi Direct (AP mode) for multiroom instead of Router mode.
- **Turn Off LED**: Toggle to turn off the front LED (supported devices only).
- **Volume Step Size**: Set the percentage step for volume changes (1-25).
- **Crossfade (ms)**: Soften the abrupt audio cut when switching source / preset / URL by ramping the volume down → switching → ramping back up. Default 300 ms; set to 0 to disable. Total wall time added per switch is roughly the configured value plus a 200 ms settle gap.

### YAML Configuration (Legacy)
**Note:** YAML configuration is supported but considered legacy. Prefer the UI for new setups. Some advanced fields (`sources`, `common_sources`, `lastfm_api_key`, `uuid`) are only available via YAML; the UI options flow exposes only the most common ones. Unique IDs are now based on device UUIDs, not IP addresses.

```yaml
# Example configuration.yaml entry
media_player:
    - platform: linkplay
      host: 192.168.1.11
      protocol: http
      name: Sound Room1
      volume_step: 10
      icecast_metadata: 'StationNameSongTitle'
      multiroom_wifidirect: False
      sources: 
        {
          'optical': 'TV sound', 
          'line-in': 'Radio tuner', 
          'bluetooth': 'Bluetooth',
          'udisk': 'USB stick',
          'http://94.199.183.186:8000/jazzy-soul.mp3': 'Jazzy Soul',
        }
```

### Configuration Variables (YAML)

**host:**  
  *(string)* *(Required)* The IP address of the Linkplay unit. Note that using a hostname will not work with a few commands, e.g., joining multiroom groups.

**protocol:**  
  *(string)* *(Optional)* The protocol used by the device. Can be one of `http` or `https`. If omitted, the player will first try on `https` and if fails will switch to `http`, but that may cause issues when the player becomes unreachable and comes back.

**name:**  
  *(string)* *(Required)* Name that Home Assistant will generate the `entity_id` based on. It is also the base of the friendly name seen in the dashboard, but will be overriden by the device name set in the Android app.

**uuid:**  
  *(string)* *(Optional)* Hardware UUID of the player. Can be read out from the attibutes of the entity. Set it manually to that value to handle double-added entity cases when Home Assistant starts up without the Linkplay device being on the network at that moment.

**volume_step:**  
  *(integer)* *(Optional)* Step size in percent to change volume when calling `volume_up` or `volume_down` service against the media player. Defaults to `5`, can be a number between `1` and `25`. 

**sources:**  
  *(list)* *(Optional)* A list with available source inputs on the device. If not specified, the integration will assume that all the supported source input types are present on it:
```yaml
'bluetooth': 'Bluetooth', 
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
'cd': 'CD'
```
The sources can be renamed to your preference (change only the part _after_ **:** ). You can also specify http-based (Icecast / Shoutcast) internet radio streams as input sources:
```yaml
'http://1.2.3.4:8000/your_radio': 'Your Radio',
'http://icecast.streamserver.tld/mountpoint.aac': 'Another radio'
```
If you don't want a source selector to be available at all, set option to empty: `sources: {}`.

_Note:_ **Don't** use HTTP**S** streams. Linkplay chipsets seem to have limited support for HTTPS. Besides, using HTTPS is useless in practice for a public webradio stream — it wastes computing resources on both server and player.

**common_sources:**  
  *(list)* *(Optional)* Another list with sources which should appear on the device. Useful if you have multiple devices on the network, and you'd like to maintain a common list of http-based internet radio stream sources for all of them in a single file with `!include linkplay-radio-sources.yaml`. The included file should be in the same place as the main config file containing `linkplay` platform.   
  For example:
```yaml
{
  'http://1.2.3.4:8000/your_radio': 'Your Radio',
  'http://icecast.streamserver.tld/mountpoint.aac': 'Another radio'
}
```

**icecast_metadata:**  
  *(string)* *(Optional)* When playing icecast webradio streams, how to handle metadata. Valid values here are `'Off'`, `'StationName'`, `'StationNameSongTitle'`, defaulting to `'StationName'` when not set. With `'Off'`, Home Assistant will not try to request any metadata from the IceCast server. With `'StationName'`, Home Assistant will request only once when starting the playback the stream name from the headers, and display it in the `media_title` property of the player. With `'StationNameSongTitle'` Home Assistant will request the stream server periodically for icy-metadata, and read out `StreamTitle`, trying to figure out correct values for `media_title` and `media_artist`, in order to gather cover art information from LastFM service (see below). Note that metadata retrieval success depends on how the icecast radio station servers and encoders are configured, if they don't provide proper infos, or they don't display correctly, it's better to turn it off or just use StationName to save server load. There's no standard way enforced on the servers, it's up to the server maintainers how it works.

**lastfm_api_key:**  
  *(string)* *(Optional)* API key to LastFM service to get album covers. Register for one.

**multiroom_wifidirect:**  
  *(boolean)* *(Optional)* Set to `True` to override the default router mode used by the component with wifi-direct connection mode (more details below).

**led_off:**  
  *(boolean)* *(Optional)* Set to `True` to turn off the LED on the front panel of the Arylic devices (works only for this brand).


## Services

| Service | Required fields | Optional fields | Purpose |
|---|---|---|---|
| `linkplay.join` | `entity_id` (slaves), `master` | — | Add slaves to a multiroom group |
| `linkplay.unjoin` | `entity_id` | — | Leave a multiroom group (master ungroups all) |
| `linkplay.play_preset` | `entity_id`, `preset_number` | — | Recall a saved device preset |
| `linkplay.command` | `entity_id`, `command` | `notify` (default `True`) | Execute a raw LinkPlay API command |
| `linkplay.snapshot` | `entity_id` | `switchinput` (default `True`) | Save player state for later restore |
| `linkplay.restore` | `entity_id` | — | Restore previously snapshotted state |
| `linkplay.play_track` | `entity_id`, `track` | — | Play a track from a template URL |
| `linkplay.set_group_volume` | `entity_id` (master), `volume` (0.0–1.0) | — | Set master volume; each slave shifts by the same delta, mini-media-player style |

Home Assistant standard services `media_player.join`, `media_player.unjoin`, `media_player.volume_set`, `media_player.play_media`, `media_player.select_source`, etc. are also supported. Cards like mini-media-player use these.

### linkplay.play_track

Plays a track from a templated URL — useful for dynamically composed stream URLs:
```yaml
    - service: linkplay.play_track
      data:
        entity_id: media_player.sound_room1
        track: "http://my.server.tld/{{ states('input_select.station') }}.mp3"
```


## Multiroom

Linkplay devices support multiroom in two modes:
- Wi-Fi direct mode, where the master turns into a hidden AP and the slaves connect directly to it. The advantage is that this is a dedicated direct connection between the speakers, with network parameters optimized by the factory for streaming. Disadvantage is that switching of the stream is slower, plus the coverage can be limited due to the building's specifics. _This is the default method used by the Android app to create multirooms._
- Router mode, where the master and slaves connect to each other through the local network (from firmware `v4.2.8020` up). The advantage is that all speakers remain connected to the existing network, switching the stream happens faster, and the coverage can be bigger being ensured by the network infrastructure of the building (works through multiple interconnected APs and switches). Disadvantage is that the network is not dedicated, and it's the user responsibility to provide proper network infrastructure for reliable streaming. _This only works through this component, and it's the preferred mode._

This integration will autodetect the firmware version running on the player and choose multiroom mode accordingly. Units with firmware version lower than `v4.2.8020` can connect to multirooms _only in wifi-direct mode_. Firmware version number can be seen in device attributes. If the user has a mix of players running old and new firmware, autodetection can be overriden with option `multiroom_wifidirect: True`, and is needed only for units with newer versions, to force them down to wifi-direct multiroom.

To create a multiroom group, connect `media_player.sound_room2` (slave) to `media_player.sound_room1` (master):
```yaml
    - service: linkplay.join
      data:
        entity_id: media_player.sound_room2
        master: media_player.sound_room1
```
To exit from the multiroom group, use the entity ids of the players that need to be unjoined. If this is the entity of a master, all slaves will be disconnected:
```yaml
    - service: linkplay.unjoin
      data:
        entity_id: media_player.sound_room1
```
These services are compatible out of the box with the speaker group object in @kalkih's [Mini Media Player](https://github.com/kalkih/mini-media-player) card for Lovelace UI.

It's also possible to use Home Assistant's [standard multiroom](https://www.home-assistant.io/integrations/media_player/#service-media_playerjoin) join and unjoin functions for multiroom control.

*Tip*: if you experience temporary `Unavailable` status on the slaves after unjoining from a multiroom group in router mode, run once the Linkplay-specific command `RouterMultiroomEnable` - see details further down.

### Group volume (`linkplay.set_group_volume`)

Mirrors how mini-media-player's group slider works: `volume` is applied to the **master** speaker and every slave shifts by the **same delta** (new master − old master) from its current volume. Each slave keeps its relative offset from the master. Final values are clamped to `[0.0, 1.0]`.

```yaml
service: linkplay.set_group_volume
data:
  entity_id: media_player.living_room   # master of the group
  volume: 0.5                           # new master volume; slaves shift by the delta
```

Example: master is at 0.40, kitchen at 0.30 (-0.10 offset), bedroom at 0.60 (+0.20 offset). Calling the service with `volume: 0.60` (delta +0.20) sets master → 0.60, kitchen → 0.50, bedroom → 0.80. A slave already at 1.0 stays at 1.0 when the master goes up; when the master comes back down the slave drops normally from there.

#### Automation example

```yaml
automation:
  - alias: "Quieter at night"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: linkplay.set_group_volume
        data:
          entity_id: media_player.living_room
          volume: 0.2
```

For explicit per-speaker control, call the standard `media_player.volume_set` against each entity directly.


## SomaFM track metadata

LinkPlay's TuneIn integration on most firmwares (AudioPro A36 and similar) only proxies the station name — actual track artist/title are not exposed via `getPlayerStatus` or UPnP DIDL. When the integration detects a SomaFM station playing (anything matching `SomaFM: <Channel>`), it fetches now-playing JSON directly from `https://somafm.com/songs/<channel>.json` and surfaces artist, title, album and per-track album art on the media card.

Channel slugs are resolved via `https://somafm.com/channels.json` (cached for the lifetime of the HA process), so stations like `SomaFM: Space Station Soma` correctly map to the `spacestation` slug. The channel cover art is used as a stable fallback when the current track has no per-song album art.

Nothing to configure — it activates automatically for any SomaFM preset played through TuneIn. The fetcher polls every 5 seconds per device, so the displayed track refreshes within ~6 seconds of pressing play **and** between songs while the channel keeps playing.

Per-track artwork is resolved in priority order: **iTunes Search** (queried with `artist + title`, returns 600x600 album cover for known albums) → SomaFM's per-track `albumart` field (set on some channels) → SomaFM's channel logo. iTunes is keyless, throttled to 4 seconds per device, and cached per `(artist, title)` so each track only hits the network once. The lookup also fires for any non-SomaFM stream whenever the resolved track changes, so generic Icecast / TuneIn stations get real album art too.

If you want to hide the title / artist row entirely, use the mini-media-player card's `hide: info: true` option — `icecast_metadata = Off` keeps reporting the firmware-supplied title.

## Presets

Linkplay devices allow saving music presets (for example Spotify playlists) via the control app on the phone/tablet, to be recalled for later listening. Recall a preset from Home Assistant:
```yaml
    - service: linkplay.play_preset
      data:
        entity_id: media_player.sound_room1
        preset_number: 1
```
Preset count varies from device type to type, usually the phone app shows how many presets can be stored maximum. The integration detects the max number and the command only accepts numbers from the allowed range. You can specify multiple entity ids separated by comma or use `all` to run the service against.

## Specific commands

Linkplay devices support some commands through the API, this is a wrapper to be able to use these in Home Assistant:
```yaml
    - service: linkplay.command
      data:
        entity_id: media_player.sound_room1
        command: TimeSync
        notify: False
```
Implemented commands:
- `PromptEnable` and `PromptDisable` - enable or disable the audio prompts played through the speakers when connecting to the network or joining multiroom etc.
- `"WriteDeviceNameToUnit: My Device Name"` - change the friendly name of the device both in firmware and in Home Assistant. Needs to be in quotes.
- `"SetApSSIDName: NewWifiName"` - change the SSID name of the AP created by the unit for wifidirect multiroom connections. Needs to be in quotes.
- `SetRandomWifiKey`- perhaps as an extra security feature, one could make an automation to change the keys on the APs to some random values periodically.
- `TimeSync` - is for units on networks not connected to internet to compensate for an unreachable NTP server. Correct time is needed for the alarm clock functionality (not implemented yet here).
- `RouterMultiroomEnable` - router mode is available by default in firmwares above v4.2.8020, but there’s also a logic included to build it up, this command ensures to set the good priority. Only use if you have issues with multiroom in router mode.
- `MCU+XXX+XXX` - passthrough for direct TCP UART commands [supported by the module](https://forum.arylic.com/t/home-assistant-integratio-available/729/23). Input not validated, use at your own risk.
- `Rescan` - do not wait for the current 60-second throttle cycle to reconnect to the unavailable devices, trigger testing for availability immediately.

If parameter `notify: False` is omitted, results will appear in Lovelace UI's left pane as persistent notifications which can be dismissed. You can specify multiple entity ids separated by comma or use `all` to run the service against.

## Snapshot and restore

These functions are useless since Home Assistant 2022.6 because this component has support for announcements so it does the snapshot and the restore automatically for any TTS message coming in.
See below on how to call a TTS announcement service.

To prepare the player to play TTS and save the current state of it for restoring afterward, current playback will stop:
```yaml
    - service: linkplay.snapshot
      data:
        entity_id: media_player.sound_room1
        switchinput: true
```
Note the `switchinput` parameter: if the currently playing source is Spotify and this parameter is `True`, it will only save the current volume of the player. You can use Home Assistant's Spotify integration to pause playback within an automation (read further below). If it's `False`, it will save the current Spotify playlist to the player's preset memory. With other playback sources (like Line-In), it will only switch to network playback.

To restore the player state:
```yaml
    - service: linkplay.restore
      data:
        entity_id: media_player.sound_room1
```
You can specify multiple entity ids separated by comma or use `all` to run the service against. Currently, the following state is being snapshotted/restored:
- Volume
- Input source
- Webradio stream (as long as it's configured as an input source)
- USB audio files playback (track will restart from the beginning)
- Spotify: If the snapshot was taken with `switchinput` as `False`, it will recall the playlist, but playback may restart the same track or not, depends on Spotify settings. With `switchinput` as `True` it will do nothing, but you can resume playback from the Spotify integration in an automation (see example below).

## Service call examples

Play a sound file located on an http server or a webradio stream:
```yaml
    - service: media_player.play_media
      data:
        entity_id: media_player.sound_room1
        media_content_id: 'http://icecast.streamserver.tld/mountpoint.mp3'
        media_content_type: url
```

Play the first sound file located on the local storage directly attached to the device (folder\files order seen by the chip seems to be alphabetic):
```yaml
    - service: media_player.play_media
      data:
        entity_id: media_player.sound_room1
        media_content_id: '1'
        media_content_type: music
```

Play a TTS (text-to-speech) announcement:
```yaml
      - service: tts.google_translate_say
        data:
          entity_id: media_player.sound_room1
          message: "Hanna has arrived home."
          language: en
```
If you experience that the announcement audio is cut off at the beginning, this happens because the player hardware needs some time to switch to playing out the stream. The only good solution for this is to add a configurable amount of silence at the beginning of the audio stream, I've modified [Mary TTS](https://github.com/nagyrobi/home-assistant-custom-components-marytts), [Google Translate](https://github.com/nagyrobi/home-assistant-custom-components-google_translate) and [VoiceRSS](https://github.com/nagyrobi/home-assistant-custom-components-voicerss) to do this, they can be installed manually as custom components ([even through HACS, manually](https://hacs.xyz/docs/faq/custom_repositories)). Linkplay modules seem to need about `800`ms of silence at the beginning of the stream in order for the first soundbits not to be cut down from the speech.

## Automation examples

Select an input and set volume and unmute via an automation:
```yaml
- alias: 'Switch to the line input of the TV when TV turns on'
  trigger:
    - platform: state
      entity_id: media_player.tv_room1
      to: 'on'
  action:
    - service: media_player.select_source
      data:
        entity_id: media_player.sound_room1
        source: 'TV sound'
    - service: media_player.volume_set
      data:
        entity_id: media_player.sound_room1
        volume_level: 1
    - service: media_player.volume_mute
      data:
        entity_id: media_player.sound_room1
        is_volume_muted: false
```
Note that you have to specify source names as you've set them in the configuration of the component.


## About Linkplay

Linkplay is a smart audio chipset and module manufacturer. Their various module types share the same functionality across the whole platform and alow for native audio content playback from lots of sources, including local inputs, local files, Bluetooth, DNLA, Airplay and also web-based services like Icecast, Spotify, Tune-In, Deezer, Tidal etc. They allow setting up multiroom listening environments using either self-created wireless connections or relying on existing network infrastructure, for longer distances coverage. For more information visit https://linkplay.com/.
There are quite a few manufacturers and devices that operate on the basis of Linkplay platform. Here are just some examples of the brands and models with A31 chipset:
- **Arylic** (S50Pro, A50, Up2Stream),
- **August** (WS300G),
- **Audio Pro** (A10, A26, A36, A40, Addon C3/C5/C5A/C10/C-SUB, D-1, Drumfire, Link 1),
- **Auna** (Intelligence Tube),
- **Bauhn** (SoundMax 5),
- **Bem** (Speaker Big Mo),
- **Centaurus** (Flyears),
- **Champion** (AWF320),
- **COWIN** (DiDa, Thunder),
- **Crystal Acoustics** (Crystal Audio),
- **CVTE** (FD2140),
- **Dayton Audio** (AERO),
- **DOSS** (Deshi, Soundbox Mini, DOSS Assistant, Cloud Fox A1),
- **DYON** (DYON Area Player),
- **Edifier** (MA1),
- **Energy Sistem** (Multiroom Tower Wi-Fi, Multiroom Portable Wi-Fi),
- **FABRIQ** (Chorus, Riff),
- **First Alert** (Onelink Safe & Sound),
- **GE Sol** (C),
- **GGMM** (E2 Wireless, E3 Wireless, E5 Wireless),
- **GIEC** (Hi-Fi Smart Sound S1),
- **Harman Kardon** (Allure),
- **Hyundai** (Modern Oxygen Bar),
- **iDeaUSA** (iDEaHome, Home Speaker, Mini Home Soundbar),
- **iEAST Sonoé** (AudioCast M5, SoundStream, Stream Pro, StreamAmp AM160, StreamAmp i50B),
- **iHome** (iAVS16),
- **iLive** (Concierge, Platinum),
- **iLuv** (Aud Air, Aud Click Shower, Aud Click),
- **JAM Audio** (Voice, Symphony, Rhythm),
- **JD** (CrazyBoa 2Face),
- **KEiiD**,
- **Lowes** (Showbox),
- **Magnavox** (MSH315V),
- **Medion** (MD43631, MedionX MD43259),
- **Meidong** (Meidong 3119),
- **MK** (MK Alexa Speaker),
- **MÜZO** (Cobblestone),
- **Naxa** (NAS-5003, NHS-5002, NAS-5001, NAS-5000),
- **Nexum** (Memo),
- **Omaker** (WoW),
- **Omars** (Dogo),
- **Polaroid** (PWF1001),
- **Roxcore**	(Roxcore),
- **Sharper Image** (SWF1002),
- **Shenzhen Renqing Technology Ltd** (ROCKLAVA),
- **SoundBot** (SB600),
- **SoundLogic** (Buddy),
- **Stereoboommm** (MR200, MR300),
- **Tibo** (Choros Tap),
- **Tinman** (Smart JOJO),
- **Venz** (A501),
- **Uyesee** (AM160),
- **Youzhuan** (Intelligent Music Ceiling),
- **Zolo Audio** (Holo),
- etc.

## Home Assistant component authors & contributors

- @nicjo814 (original)
- @limych
- @nagyrobi
- @phedoreanu (current maintainer)

## Home Assistant component License

MIT License

- Copyright © 2019 Niclas Berglind nicjo814
- Copyright © 2019—2020 Andrey "Limych" Khrolenok
- Copyright © 2020 nagyrobi Robert Horvath-Arkosi
- Copyright © 2026 phedoreanu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

[forum-support]: https://community.home-assistant.io/t/linkplay-integration/33878
