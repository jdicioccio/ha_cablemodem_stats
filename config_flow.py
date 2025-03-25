"""Config flow for Arris/Motorola Cable Modem Stats integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SSL,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import DEFAULT_SCAN_INTERVAL
from .const import DOMAIN, SUPPORTED_MODELS

_LOGGER = logging.getLogger(__name__)

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    session = async_get_clientsession(hass)
    protocol = "https" if data.get(CONF_SSL, True) else "http"
    model = data[CONF_MODEL]

    try:
        if model == "MB8600":
            url = f"{protocol}://{data[CONF_HOST]}/HNAP1"
            headers = {
                "SOAPACTION": '"http://purenetworks.com/HNAP1/GetMultipleHNAPs"',
                "Content-Type": "application/json",
            }
            payload = {
                "GetMultipleHNAPs": {
                    "GetMotoStatusStartupSequence": "",
                    "GetMotoStatusConnectionInfo": "",
                    "GetMotoStatusDownstreamChannelInfo": "",
                    "GetMotoStatusUpstreamChannelInfo": "",
                    "GetMotoLagStatus": "",
                }
            }
            
            async with session.post(url, json=payload, headers=headers) as response:
                response.raise_for_status()
                await response.json()  # Validate we can parse the response
        else:  # CGM4331COM or CGM4981COM
            if not data.get(CONF_USERNAME) or not data.get(CONF_PASSWORD):
                raise ValueError("Username and password are required for CGM models")

            # First request to get session cookie
            login_url = f"{protocol}://{data[CONF_HOST]}/check.jst"
            payload = {
                "username": data[CONF_USERNAME],
                "password": data[CONF_PASSWORD],
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
            }
            
            async with session.post(login_url, data=payload, headers=headers, allow_redirects=False) as response:
                if not response.status in (301, 302):  # Should get a redirect on success
                    raise aiohttp.ClientError("Authentication failed")
                
                # Get session cookie
                cookies = response.cookies
                if not cookies:
                    raise aiohttp.ClientError("No session cookie received")

            # Second request to get the data
            data_url = f"{protocol}://{data[CONF_HOST]}/network_setup.jst"
            async with session.get(data_url, cookies=cookies) as response:
                response.raise_for_status()
                await response.text()  # Validate we can get the response

        return {"title": f"Arris Modem {model}"}
    except Exception as err:
        _LOGGER.error("Failed to connect to modem: %s", err)
        raise

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Arris/Motorola Cable Modem Stats."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except ValueError as err:
                _LOGGER.error(err)
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_MODEL): vol.In(SUPPORTED_MODELS),
                    vol.Optional(CONF_USERNAME): str,
                    vol.Optional(CONF_PASSWORD): str,
                    vol.Optional(CONF_SSL, default=True): bool,
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=DEFAULT_SCAN_INTERVAL.total_seconds(),
                    ): vol.All(vol.Coerce(int), vol.Range(min=60)),  # Minimum 1 minute
                }
            ),
            errors=errors,
        ) 