"""Config flow to configure Linkplay component.

Simple discovery and setup flow following Home Assistant best practices.
"""

# mypy: ignore-errors

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import onboarding
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PROTOCOL
from homeassistant.core import callback
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class LinkplayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Linkplay config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self.data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> LinkplayOptionsFlow:
        """Return the options flow."""
        return LinkplayOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle user-initiated setup - go directly to manual entry for speed."""
        return await self.async_step_manual()

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle manual IP entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            name = user_input.get(CONF_NAME, "")
            protocol = user_input.get(CONF_PROTOCOL, "http")

            # Validate device connectivity and get device info
            device_info = await self._validate_device(host, protocol)
            if not device_info:
                errors["base"] = "cannot_connect"
            else:
                # Use device UUID as unique ID (falls back to formatted MAC or host if UUID unavailable)
                unique_id = device_info.get("uuid", "")
                if not unique_id:
                    # If no UUID, we cannot guarantee uniqueness - warn but allow
                    _LOGGER.warning(
                        "Device at %s does not provide UUID. "
                        "This may cause issues with duplicate device detection.",
                        host
                    )
                    # Use host as fallback (not ideal but better than nothing)
                    unique_id = f"linkplay_{host.replace('.', '_')}"

                # Check for existing entry with same UUID
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})

                # Use device name if provided by device and user didn't specify one
                if not name and device_info.get("name"):
                    name = device_info["name"]
                elif not name:
                    name = f"Linkplay Device ({host})"

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_HOST: host,
                        CONF_NAME: name,
                        CONF_PROTOCOL: protocol,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, description="IP address of your Linkplay device"): str,
                vol.Optional(CONF_NAME, description="Device name"): str,
                vol.Optional(CONF_PROTOCOL, default="http"): vol.In(["http", "https"]),
            }
        )

        return self.async_show_form(
            step_id="manual",
            data_schema=schema,
            errors=errors,
            description_placeholders={"example_ip": "192.168.1.100"},
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """Handle Zeroconf discovery."""
        host = discovery_info.host
        _LOGGER.debug("Zeroconf discovery for host: %s", host)

        # Validate device and get info
        device_info = await self._validate_device(host, "http")
        if not device_info:
            return self.async_abort(reason="cannot_connect")

        # Use device UUID as unique ID
        unique_id = device_info.get("uuid", "")
        if not unique_id:
            _LOGGER.warning("Zeroconf device at %s has no UUID, using fallback", host)
            unique_id = f"linkplay_{host.replace('.', '_')}"

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        # Use device name from device if available
        device_name = device_info.get("name") or f"Linkplay Device ({host})"
        self.data = {
            CONF_HOST: host,
            "name": device_name,
            CONF_PROTOCOL: "http",
            "uuid": unique_id,
        }
        return await self.async_step_discovery_confirm()

    async def async_step_ssdp(self, discovery_info: SsdpServiceInfo) -> ConfigFlowResult:
        """Handle SSDP discovery."""
        _LOGGER.debug("SSDP discovery from: %s", discovery_info.ssdp_location)

        if not discovery_info.ssdp_location:
            return self.async_abort(reason="no_host")

        host = urlparse(discovery_info.ssdp_location).hostname
        if not host:
            return self.async_abort(reason="no_host")

        # Validate device and get info
        device_info = await self._validate_device(host, "http")
        if not device_info:
            return self.async_abort(reason="cannot_connect")

        # Use device UUID as unique ID
        unique_id = device_info.get("uuid", "")
        if not unique_id:
            _LOGGER.warning("SSDP device at %s has no UUID, using fallback", host)
            unique_id = f"linkplay_{host.replace('.', '_')}"

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        # Use device name from device if available
        device_name = device_info.get("name") or f"Linkplay Device ({host})"
        self.data = {
            CONF_HOST: host,
            "name": device_name,
            CONF_PROTOCOL: "http",
            "uuid": unique_id,
            "ssdp_info": {"location": discovery_info.ssdp_location} if discovery_info.ssdp_location else {},
        }
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm discovery."""
        # Auto-create entry during onboarding or when user confirms
        if user_input is not None or not onboarding.async_is_onboarded(self.hass):
            entry_data = {
                CONF_HOST: self.data[CONF_HOST],
                CONF_NAME: self.data.get("name", f"Linkplay Device ({self.data[CONF_HOST]})"),
                CONF_PROTOCOL: self.data.get(CONF_PROTOCOL, "http"),
            }
            if "ssdp_info" in self.data:
                entry_data["ssdp_info"] = self.data["ssdp_info"]

            return self.async_create_entry(
                title=self.data["name"],
                data=entry_data,
            )

        # Show confirmation form only after onboarding is complete
        description_placeholders = {"name": self.data["name"]}

        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders=description_placeholders,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle reconfiguration initiated by the user."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            protocol = user_input.get(CONF_PROTOCOL, "http")

            # Validate device at new IP address
            device_info = await self._validate_device(host, protocol)
            if not device_info:
                errors["base"] = "cannot_connect"
            else:
                # Verify it's the same device by checking UUID
                if device_info.get("uuid") and reconfigure_entry.unique_id:
                    if device_info["uuid"] != reconfigure_entry.unique_id:
                        errors["base"] = "different_device"
                        _LOGGER.warning(
                            "Device at %s has UUID %s but expected %s",
                            host, device_info["uuid"], reconfigure_entry.unique_id
                        )

                if not errors:
                    # Update entry with new IP and reload
                    return self.async_update_reload_and_abort(
                        reconfigure_entry,
                        data_updates={
                            CONF_HOST: host,
                            CONF_PROTOCOL: protocol,
                        },
                        reason="reconfigure_successful",
                    )

        # Show form with current IP pre-filled
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST,
                    default=reconfigure_entry.data.get(CONF_HOST),
                    description="IP address of your Linkplay device",
                ): str,
                vol.Optional(
                    CONF_PROTOCOL,
                    default=reconfigure_entry.data.get(CONF_PROTOCOL, "http"),
                ): vol.In(["http", "https"]),
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "name": reconfigure_entry.title,
                "current_ip": reconfigure_entry.data.get(CONF_HOST, "Unknown"),
            },
        )

    async def _validate_device(self, host: str, protocol: str) -> dict[str, Any] | None:
        """Validate device connectivity and retrieve device information.

        Returns device info dict with 'uuid' and 'name' if successful, None otherwise.
        """
        try:
            session = async_get_clientsession(self.hass)
            url = f"{protocol}://{host}/httpapi.asp?command=getStatus"

            async with session.get(url, ssl=False, timeout=5) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    # Extract UUID and device name from response
                    device_info = {
                        "uuid": data.get("uuid", ""),
                        "name": data.get("DeviceName", ""),
                    }
                    _LOGGER.debug("Device info for %s: %s", host, device_info)
                    return device_info
                elif response.status in (400, 401, 403):
                    # Device responds but doesn't provide JSON - still valid
                    _LOGGER.warning("Device at %s responded with status %s, UUID unavailable", host, response.status)
                    return {"uuid": "", "name": ""}
                return None

        except Exception as err:
            _LOGGER.debug("Device validation failed for %s: %s", host, err)
            return None

    def is_matching(self, other_flow: config_entries.ConfigFlow) -> bool:
        """Check if two flows are matching."""
        return False


class LinkplayOptionsFlow(config_entries.OptionsFlow):
    """Handle Linkplay options."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle options flow."""
        try:
            if user_input is not None:
                # Store any future options here
                return self.async_create_entry(title="", data=user_input)

            schema = vol.Schema({})

            return self.async_show_form(step_id="init", data_schema=schema)

        except Exception as err:
            _LOGGER.exception("Error in options flow: %s", err)
            return self.async_show_form(
                step_id="init",
                errors={"base": "unknown_error"},
                data_schema=vol.Schema({}),
            )
