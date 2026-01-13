"""Tests for Linkplay config flow."""

from __future__ import annotations

from ipaddress import IPv4Address
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import data_entry_flow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PROTOCOL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from custom_components.linkplay.config_flow import (
    LinkplayConfigFlow,
    LinkplayOptionsFlow,
)
from custom_components.linkplay.const import DOMAIN

# MockConfigEntry compatibility
try:
    from homeassistant.test.common import MockConfigEntry
except ImportError:
    # Fallback for older Home Assistant versions
    class MockConfigEntry:  # type: ignore
        """Mock config entry."""
        def __init__(self, domain, data, title=None):
            self.domain = domain
            self.data = data
            self.title = title or "Mock Entry"

        def add_to_hass(self, hass):
            """Add to hass."""
            pass


class TestLinkplayConfigFlow:
    """Test Linkplay config flow."""

    @pytest.fixture
    def mock_async_setup(self):
        """Mock async setup."""
        with patch(
            "custom_components.linkplay.async_setup_entry", new_callable=AsyncMock
        ) as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_async_step_user_manual_entry(self, hass: HomeAssistant):
        """Test user step redirects to manual entry."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        result = await flow.async_step_user()

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "manual"

    @pytest.mark.asyncio
    async def test_async_step_manual_success(self, hass: HomeAssistant):
        """Test successful manual entry with valid device."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        with patch.object(flow, "_validate_device", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            with patch.object(
                flow, "async_set_unique_id"
            ) as mock_set_unique_id:
                with patch.object(
                    flow, "_abort_if_unique_id_configured"
                ):
                    result = await flow.async_step_manual(
                        user_input={
                            CONF_HOST: "192.168.1.100",
                            CONF_NAME: "Living Room Speaker",
                            CONF_PROTOCOL: "http",
                        }
                    )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == "Living Room Speaker"
        assert result["data"][CONF_HOST] == "192.168.1.100"
        assert result["data"][CONF_NAME] == "Living Room Speaker"
        assert result["data"][CONF_PROTOCOL] == "http"
        mock_set_unique_id.assert_called_once_with("192.168.1.100")

    @pytest.mark.asyncio
    async def test_async_step_manual_failure_cannot_connect(
        self, hass: HomeAssistant
    ):
        """Test manual entry with unreachable device."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        with patch.object(flow, "_validate_device", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = False

            result = await flow.async_step_manual(
                user_input={
                    CONF_HOST: "192.168.1.100",
                    CONF_NAME: "Living Room Speaker",
                    CONF_PROTOCOL: "http",
                }
            )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "manual"
        assert result["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_async_step_manual_default_name(self, hass: HomeAssistant):
        """Test manual entry with default device name."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        with patch.object(flow, "_validate_device", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            with patch.object(
                flow, "async_set_unique_id"
            ):
                with patch.object(
                    flow, "_abort_if_unique_id_configured"
                ):
                    result = await flow.async_step_manual(
                        user_input={
                            CONF_HOST: "192.168.1.100",
                            CONF_PROTOCOL: "http",
                        }
                    )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert "Linkplay Device (192.168.1.100)" in result["title"]

    @pytest.mark.asyncio
    async def test_async_step_manual_https_protocol(self, hass: HomeAssistant):
        """Test manual entry with HTTPS protocol."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        with patch.object(flow, "_validate_device", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            with patch.object(
                flow, "async_set_unique_id"
            ):
                with patch.object(
                    flow, "_abort_if_unique_id_configured"
                ):
                    result = await flow.async_step_manual(
                        user_input={
                            CONF_HOST: "192.168.1.100",
                            CONF_PROTOCOL: "https",
                        }
                    )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_PROTOCOL] == "https"

    @pytest.mark.asyncio
    async def test_async_step_manual_whitespace_stripping(self, hass: HomeAssistant):
        """Test that whitespace is stripped from host input."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        with patch.object(flow, "_validate_device", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            with patch.object(
                flow, "async_set_unique_id"
            ) as mock_set_unique_id:
                with patch.object(
                    flow, "_abort_if_unique_id_configured"
                ):
                    result = await flow.async_step_manual(
                        user_input={
                            CONF_HOST: "  192.168.1.100  ",
                            CONF_PROTOCOL: "http",
                        }
                    )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        mock_set_unique_id.assert_called_once_with("192.168.1.100")
        mock_validate.assert_called_once_with("192.168.1.100", "http")

    @pytest.mark.asyncio
    async def test_async_step_zeroconf_success(self, hass: HomeAssistant):
        """Test successful Zeroconf discovery."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        discovery_info = ZeroconfServiceInfo(
            ip_address="192.168.1.100",
            ip_addresses=["192.168.1.100"],
            hostname="linkplay.local",
            name="Linkplay Speaker._http._tcp.local.",
            port=8080,
            properties={},
            type="_http._tcp.local.",
        )

        with patch.object(flow, "_validate_device", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            with patch.object(
                flow, "async_set_unique_id"
            ):
                with patch.object(
                    flow, "_abort_if_unique_id_configured"
                ):
                    result = await flow.async_step_zeroconf(discovery_info)

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "discovery_confirm"

    @pytest.mark.asyncio
    async def test_async_step_zeroconf_already_configured(self, hass: HomeAssistant):
        """Test Zeroconf discovery when device already configured."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        # Create a mock entry for already configured case
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_HOST: "192.168.1.100"},
        )
        entry.add_to_hass(hass)

        discovery_info = ZeroconfServiceInfo(
            ip_address="192.168.1.100",
            ip_addresses=["192.168.1.100"],
            hostname="linkplay.local",
            name="Linkplay Speaker._http._tcp.local.",
            port=8080,
            properties={},
            type="_http._tcp.local.",
        )

        # Mock _async_current_entries to return our test entry
        with patch.object(flow, "_async_current_entries", return_value=[entry]):
            result = await flow.async_step_zeroconf(discovery_info)

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    @pytest.mark.asyncio
    async def test_async_step_zeroconf_cannot_connect(self, hass: HomeAssistant):
        """Test Zeroconf discovery when device cannot be validated."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        discovery_info = ZeroconfServiceInfo(
            ip_address="192.168.1.100",
            ip_addresses=["192.168.1.100"],
            hostname="linkplay.local",
            name="Linkplay Speaker._http._tcp.local.",
            port=8080,
            properties={},
            type="_http._tcp.local.",
        )

        with patch.object(flow, "_validate_device", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = False

            result = await flow.async_step_zeroconf(discovery_info)

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_async_step_ssdp_success(self, hass: HomeAssistant):
        """Test successful SSDP discovery."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        discovery_info = SsdpServiceInfo(
            ssdp_usn="uuid:12345678::ssdp:all",
            ssdp_location="http://192.168.1.100:8080/description.xml",
            ssdp_st="ssdp:all",
            upnp={},
        )

        with patch.object(flow, "_validate_device", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = True
            with patch.object(
                flow, "async_set_unique_id"
            ):
                with patch.object(
                    flow, "_abort_if_unique_id_configured"
                ):
                    result = await flow.async_step_ssdp(discovery_info)

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "discovery_confirm"

    @pytest.mark.asyncio
    async def test_async_step_ssdp_no_location(self, hass: HomeAssistant):
        """Test SSDP discovery with no location."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        discovery_info = SsdpServiceInfo(
            ssdp_usn="uuid:12345678::ssdp:all",
            ssdp_location=None,
            ssdp_st="ssdp:all",
            upnp={},
        )

        result = await flow.async_step_ssdp(discovery_info)

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "no_host"

    @pytest.mark.asyncio
    async def test_async_step_ssdp_cannot_connect(self, hass: HomeAssistant):
        """Test SSDP discovery when device cannot be validated."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        discovery_info = SsdpServiceInfo(
            ssdp_usn="uuid:12345678::ssdp:all",
            ssdp_location="http://192.168.1.100:8080/description.xml",
            ssdp_st="ssdp:all",
            upnp={},
        )

        with patch.object(flow, "_validate_device", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = False

            result = await flow.async_step_ssdp(discovery_info)

        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_async_step_discovery_confirm_auto_create_onboarding(
        self, hass: HomeAssistant
    ):
        """Test discovery confirm auto-creates entry during onboarding."""
        flow = LinkplayConfigFlow()
        flow.hass = hass
        flow.data = {
            CONF_HOST: "192.168.1.100",
            "name": "Living Room Speaker",
            CONF_PROTOCOL: "http",
        }

        with patch(
            "custom_components.linkplay.config_flow.onboarding.async_is_onboarded",
            return_value=False,
        ):
            result = await flow.async_step_discovery_confirm()

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == "Living Room Speaker"
        assert result["data"][CONF_HOST] == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_async_step_discovery_confirm_with_user_input(
        self, hass: HomeAssistant
    ):
        """Test discovery confirm with user confirmation after onboarding."""
        flow = LinkplayConfigFlow()
        flow.hass = hass
        flow.data = {
            CONF_HOST: "192.168.1.100",
            "name": "Living Room Speaker",
            CONF_PROTOCOL: "http",
        }

        with patch(
            "custom_components.linkplay.config_flow.onboarding.async_is_onboarded",
            return_value=True,
        ):
            result = await flow.async_step_discovery_confirm(user_input={})

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == "Living Room Speaker"

    @pytest.mark.asyncio
    async def test_async_step_discovery_confirm_show_form(self, hass: HomeAssistant):
        """Test discovery confirm shows form when not onboarding."""
        flow = LinkplayConfigFlow()
        flow.hass = hass
        flow.data = {
            CONF_HOST: "192.168.1.100",
            "name": "Living Room Speaker",
            CONF_PROTOCOL: "http",
        }

        with patch(
            "custom_components.linkplay.config_flow.onboarding.async_is_onboarded",
            return_value=True,
        ):
            result = await flow.async_step_discovery_confirm(user_input=None)

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "discovery_confirm"

    @pytest.mark.asyncio
    async def test_async_step_reconfigure_success(self, hass: HomeAssistant):
        """Test successful reconfiguration."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_HOST: "192.168.1.100", CONF_PROTOCOL: "http"},
            title="Living Room Speaker",
        )
        entry.add_to_hass(hass)

        flow = LinkplayConfigFlow()
        flow.hass = hass

        with patch.object(flow, "_get_reconfigure_entry", return_value=entry):
            with patch.object(flow, "_validate_device", new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = True
                with patch.object(
                    flow, "async_update_reload_and_abort"
                ) as mock_update:
                    mock_update.return_value = {"type": "abort", "reason": "reconfigure_successful"}

                    result = await flow.async_step_reconfigure(
                        user_input={
                            CONF_HOST: "192.168.1.101",
                            CONF_PROTOCOL: "https",
                        }
                    )

        mock_validate.assert_called_once_with("192.168.1.101", "https")
        mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_step_reconfigure_failure(self, hass: HomeAssistant):
        """Test reconfiguration with unreachable device."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_HOST: "192.168.1.100", CONF_PROTOCOL: "http"},
            title="Living Room Speaker",
        )
        entry.add_to_hass(hass)

        flow = LinkplayConfigFlow()
        flow.hass = hass

        with patch.object(flow, "_get_reconfigure_entry", return_value=entry):
            with patch.object(flow, "_validate_device", new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = False

                result = await flow.async_step_reconfigure(
                    user_input={
                        CONF_HOST: "192.168.1.101",
                        CONF_PROTOCOL: "https",
                    }
                )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reconfigure"
        assert result["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_async_step_reconfigure_show_form(self, hass: HomeAssistant):
        """Test reconfigure shows form with current values."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_HOST: "192.168.1.100", CONF_PROTOCOL: "http"},
            title="Living Room Speaker",
        )
        entry.add_to_hass(hass)

        flow = LinkplayConfigFlow()
        flow.hass = hass

        with patch.object(flow, "_get_reconfigure_entry", return_value=entry):
            result = await flow.async_step_reconfigure()

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

    @pytest.mark.asyncio
    async def test_validate_device_success_http(self, hass: HomeAssistant):
        """Test device validation with successful HTTP response."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        mock_response = MagicMock()
        mock_response.status = 200

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None

        with patch(
            "custom_components.linkplay.config_flow.async_get_clientsession"
        ) as mock_session:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_context
            mock_session.return_value = mock_client

            result = await flow._validate_device("192.168.1.100", "http")

        assert result is True
        mock_client.get.assert_called_once()
        assert "192.168.1.100" in str(mock_client.get.call_args)

    @pytest.mark.asyncio
    async def test_validate_device_success_https(self, hass: HomeAssistant):
        """Test device validation with HTTPS."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        mock_response = MagicMock()
        mock_response.status = 200

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None

        with patch(
            "custom_components.linkplay.config_flow.async_get_clientsession"
        ) as mock_session:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_context
            mock_session.return_value = mock_client

            result = await flow._validate_device("192.168.1.100", "https")

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_device_timeout(self, hass: HomeAssistant):
        """Test device validation timeout."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        with patch(
            "custom_components.linkplay.config_flow.async_get_clientsession"
        ) as mock_session:
            mock_client = AsyncMock()
            mock_client.get.side_effect = TimeoutError()
            mock_session.return_value = mock_client

            result = await flow._validate_device("192.168.1.100", "http")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_device_connection_error(self, hass: HomeAssistant):
        """Test device validation with connection error."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        with patch(
            "custom_components.linkplay.config_flow.async_get_clientsession"
        ) as mock_session:
            import aiohttp

            mock_client = AsyncMock()
            mock_client.get.side_effect = aiohttp.ClientConnectorError(
                connection_key=None, os_error=OSError("Connection refused")
            )
            mock_session.return_value = mock_client

            result = await flow._validate_device("192.168.1.100", "http")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_device_ssl_error(self, hass: HomeAssistant):
        """Test device validation with SSL error."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        with patch(
            "custom_components.linkplay.config_flow.async_get_clientsession"
        ) as mock_session:
            import aiohttp

            mock_client = MagicMock()
            # Just raise the exception - aiohttp will handle it
            mock_client.get.side_effect = aiohttp.ClientError("SSL error")
            mock_session.return_value = mock_client

            result = await flow._validate_device("192.168.1.100", "https")

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_device_400_response(self, hass: HomeAssistant):
        """Test device validation accepts 400 response (device reachable)."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        mock_response = MagicMock()
        mock_response.status = 400

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None

        with patch(
            "custom_components.linkplay.config_flow.async_get_clientsession"
        ) as mock_session:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_context
            mock_session.return_value = mock_client

            result = await flow._validate_device("192.168.1.100", "http")

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_device_unreachable(self, hass: HomeAssistant):
        """Test device validation with unreachable device (500 error)."""
        flow = LinkplayConfigFlow()
        flow.hass = hass

        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__.return_value = mock_response
        mock_response.__aexit__.return_value = None

        with patch(
            "custom_components.linkplay.config_flow.async_get_clientsession"
        ) as mock_session:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_session.return_value = mock_client

            result = await flow._validate_device("192.168.1.100", "http")

        assert result is False

    @pytest.mark.asyncio
    async def test_async_get_options_flow(self):
        """Test getting options flow."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_HOST: "192.168.1.100"},
        )

        flow = LinkplayConfigFlow.async_get_options_flow(entry)

        assert isinstance(flow, LinkplayOptionsFlow)
        assert flow.entry == entry

    def test_is_matching(self, hass: HomeAssistant):
        """Test is_matching returns False."""
        flow = LinkplayConfigFlow()
        flow.hass = hass
        other_flow = LinkplayConfigFlow()
        other_flow.hass = hass

        assert flow.is_matching(other_flow) is False


class TestLinkplayOptionsFlow:
    """Test Linkplay options flow."""

    @pytest.mark.asyncio
    async def test_async_step_init_show_form(self, hass: HomeAssistant):
        """Test init step shows form."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_HOST: "192.168.1.100"},
        )
        entry.add_to_hass(hass)

        flow = LinkplayOptionsFlow(entry)
        flow.hass = hass

        result = await flow.async_step_init()

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_async_step_init_with_input(self, hass: HomeAssistant):
        """Test init step creates entry with input."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_HOST: "192.168.1.100"},
        )
        entry.add_to_hass(hass)

        flow = LinkplayOptionsFlow(entry)
        flow.hass = hass

        result = await flow.async_step_init(user_input={})

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == ""

    @pytest.mark.asyncio
    async def test_async_step_init_exception_handling(self, hass: HomeAssistant):
        """Test init step handles exceptions."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_HOST: "192.168.1.100"},
        )
        entry.add_to_hass(hass)

        flow = LinkplayOptionsFlow(entry)
        flow.hass = hass

        with patch.object(flow, "async_show_form", side_effect=Exception("Test error")):
            with pytest.raises(Exception):
                await flow.async_step_init()


