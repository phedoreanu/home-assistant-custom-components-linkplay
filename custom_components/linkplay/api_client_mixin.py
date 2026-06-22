"""Wire-level transport for LinkPlayDevice.

Wraps the two ways the firmware accepts commands:

* HTTPAPI on port 80/443 (``httpapi.asp?command=...``)
* TCP UART on port 8899 (for ``MCU+XXX`` style passthrough commands)

Plus the throttled ``getPlayerStatus`` poll that other update logic
hangs off of.
"""

from __future__ import annotations

import logging
import socket
from datetime import timedelta
from http import HTTPStatus

import aiohttp
import async_timeout
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

_API_TIMEOUT = 2
_FIRST_UPDATE_TIMEOUT = 10
_TCPPORT = 8899
_UART_HEAD1 = "18 96 18 20 "
_UART_HEAD2 = " 00 00 00 c1 02 00 00 00 00 00 00 00 00 00 00 "
_UNA_THROTTLE = timedelta(seconds=20)


class LinkPlayAPIClientMixin:
    """HTTPAPI / TCP UART client + throttled status poll."""

    async def call_linkplay_httpapi(self, cmd: str, jsn: bool | None, protocol: str | None = None):
        """Call the device httpapi.asp endpoint and return the parsed body.

        Returns ``False`` on any transport error so the caller can
        differentiate a failure from a legitimate ``None`` / empty
        response payload.
        """
        if protocol is None and self._protocol is None:
            _LOGGER.warning(
                "Protocol not known. Skipping communication with LinkPlayDevice '%s'",
                self._name,
            )
            return False

        proto = self._protocol if protocol is None else protocol
        url = f"{proto}://{self._host}/httpapi.asp?command={cmd}"
        timeout = _FIRST_UPDATE_TIMEOUT if self._first_update else _API_TIMEOUT
        verify_ssl = proto == "https"

        try:
            session = async_get_clientsession(self.hass)
            async with async_timeout.timeout(timeout):
                response = await session.get(url, ssl=verify_ssl, allow_redirects=True)
        except TimeoutError:
            _LOGGER.warning(
                "Failed communicating with LinkPlayDevice (httpapi) '%s': Timeout",
                self._name,
            )
            return False
        except aiohttp.ClientSSLError as error:
            _LOGGER.warning(
                "Failed communicating with LinkPlayDevice (httpapi) '%s': SSL Error - %s. Try using 'http' protocol",
                self._name, error,
            )
            return False
        except aiohttp.ClientConnectorError as error:
            _LOGGER.warning(
                "Failed communicating with LinkPlayDevice (httpapi) '%s': Connection Error - %s",
                self._name, error,
            )
            return False
        except aiohttp.ClientError as error:
            _LOGGER.warning(
                "Failed communicating with LinkPlayDevice (httpapi) '%s': %s",
                self._name, type(error).__name__,
            )
            return False
        except Exception as error:
            _LOGGER.warning(
                "Failed communicating with LinkPlayDevice (httpapi) '%s': Unexpected error - %s",
                self._name, error,
            )
            return False

        if response.status != HTTPStatus.OK:
            _LOGGER.error(
                "For: %s (%s) Get failed, response code: %s",
                self._name, self._host, response.status,
            )
            return False

        if jsn:
            return await response.json(content_type=None)
        data = await response.text()
        _LOGGER.debug("For: %s cmd: %s resp: %s", self._name, cmd, data)
        return data

    async def call_linkplay_tcpuart(self, cmd: str) -> str | None:
        """Send a raw TCP UART command and return the decoded response.

        Runs the blocking socket call on the executor so it does not
        stall the event loop on slow or unreachable devices.
        """
        lenc = format(len(cmd), "02x")
        cmhx = " ".join(hex(ord(c))[2:] for c in cmd)
        payload = bytes.fromhex(_UART_HEAD1 + lenc + _UART_HEAD2 + cmhx)
        _LOGGER.debug(
            "For: %s Sending to %s TCP UART command: %s",
            self._name, self._host, cmd,
        )

        def _send_recv() -> str | None:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(_API_TIMEOUT)
                    sock.connect((self._host, _TCPPORT))
                    sock.send(payload)
                    return str(repr(sock.recv(1024))).encode().decode("unicode-escape")
            except OSError as ex:
                _LOGGER.debug(
                    "For: %s Error sending TCP UART command: %s with %s",
                    self._name, cmd, ex,
                )
                return None

        data = await self.hass.async_add_executor_job(_send_recv)
        if data is None:
            return None

        marker = data.find("AXX")
        if marker == -1:
            marker = data.find("MCU")
        data = data[marker:len(data) - 2]
        _LOGGER.debug(
            "For: %s Received from %s TCP UART command result: %s",
            self._name, self._host, data,
        )
        return data

    @Throttle(_UNA_THROTTLE)
    async def async_get_status(self) -> None:
        """Throttled getPlayerStatus poll. Marks the entity unavailable on failure."""
        resp = await self.call_linkplay_httpapi("getPlayerStatus", True)
        if resp is False:
            _LOGGER.debug(
                "Unable to connect to device: %s, %s", self.entity_id, self._name,
            )
            self._state = STATE_UNAVAILABLE
            self._unav_throttle = True
            self._wait_for_mcu = 0
            self._playhead_position = None
            self._duration = None
            self._position_updated_at = None
            self._media_title = None
            self._media_artist = None
            self._media_album = None
            self._media_image_url = None
            self._media_uri = None
            self._media_uri_final = None
            self._media_source_uri = None
            self._playing_mediabrowser = False
            self._playing_stream = False
            self._icecast_name = None
            self._source = None
            self._upnp_device = None
            self._first_update = True
            self._slave_mode = False
            self._is_master = False
            self._player_statdata = None
            return
        self._player_statdata = resp.copy()

    async def async_trigger_schedule_update(self, before: bool) -> None:
        """Convenience wrapper for callers that just want a fresh HA state."""
        await self.async_schedule_update_ha_state(before)
