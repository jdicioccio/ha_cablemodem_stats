"""The Arris/Motorola Cable Modem Stats integration."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

import aiohttp
import async_timeout
import voluptuous as vol

from .const import DOMAIN, SUPPORTED_MODELS
from .parser import (
    parse_cgm4331com_html,
    parse_mb8600_json,
    parse_uptime,
)

_LOGGER = logging.getLogger(__name__)
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)

# ---------------------------------------------------------------------------
# Home Assistant is an *optional* runtime dependency for this package.
#
# This allows the CLI (`python -m custom_components.ha_cablemodem_stats`)
# to be used for fast offline parser testing (--html-file) and one-shot
# live HTML captures (--save-html) without requiring a full Home Assistant
# development environment.
#
# When Home Assistant is present, the normal integration works as before.
# When it is not present, we provide clear errors for the parts that need it.
# ---------------------------------------------------------------------------

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import (
        CONF_HOST,
        CONF_PASSWORD,
        CONF_USERNAME,
        CONF_SSL,
        CONF_SCAN_INTERVAL,
        Platform,
    )
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.update_coordinator import (
        DataUpdateCoordinator,
        UpdateFailed,
    )

    HAS_HOME_ASSISTANT = True
    PLATFORMS = [Platform.SENSOR]

except ImportError:
    HAS_HOME_ASSISTANT = False
    ConfigEntry = None  # type: ignore[assignment]
    HomeAssistant = None  # type: ignore[assignment]
    Platform = None  # type: ignore[assignment]
    PLATFORMS = []
    async_get_clientsession = None  # type: ignore[assignment]

    def _make_unavailable(name: str):
        def _unavailable(*args, **kwargs):
            raise RuntimeError(
                f"{name} requires Home Assistant. "
                "For offline parser testing use --html-file. "
                "For live modem access (--save-html or full integration), "
                "install the 'homeassistant' package or run from a Home Assistant environment."
            )
        return _unavailable

    async_setup_entry = _make_unavailable("async_setup_entry")
    async_unload_entry = _make_unavailable("async_unload_entry")

    class ArrisModemDataUpdateCoordinator:  # type: ignore[no-redef]
        """Stub when Home Assistant is not installed."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "ArrisModemDataUpdateCoordinator requires Home Assistant. "
                "Use --html-file for offline parser development. "
                "For live captures install the 'homeassistant' package."
            )


if HAS_HOME_ASSISTANT:
    async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        """Set up Arris Modem Stats from a config entry."""
        # Prefer options over data so users can update credentials / host / interval
        # after the integration has been added (via the Options flow).
        config = {**entry.data, **(entry.options or {})}

        host = config[CONF_HOST]
        username = config.get(CONF_USERNAME)
        password = config.get(CONF_PASSWORD)
        use_ssl = config.get(CONF_SSL, True)
        model = config["model"]

        scan_interval = config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds())
        scan_interval = timedelta(seconds=scan_interval)

        coordinator = ArrisModemDataUpdateCoordinator(
            hass,
            host=host,
            username=username,
            password=password,
            use_ssl=use_ssl,
            model=model,
            scan_interval=scan_interval,
        )

        _LOGGER.debug("Setting up coordinator with model: %s, host: %s", model, host)

        await coordinator.async_config_entry_first_refresh()

        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Reload the integration when options are changed by the user
        entry.async_on_unload(
            entry.add_update_listener(async_reload_entry)
        )

        return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)

    async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        """Unload a config entry."""
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if unload_ok:
            hass.data[DOMAIN].pop(entry.entry_id)
        return unload_ok

    class ArrisModemDataUpdateCoordinator(DataUpdateCoordinator):  # type: ignore[no-redef]
        """Class to manage fetching data from the modem."""

        def __init__(
            self,
            hass: HomeAssistant,
            host: str,
            username: str | None,
            password: str | None,
            use_ssl: bool,
            model: str,
            scan_interval: timedelta,
        ) -> None:
            """Initialize."""
            self.host = host
            self.username = username
            self.password = password
            self.use_ssl = use_ssl
            self.model = model
            self.session = async_get_clientsession(hass)

            super().__init__(
                hass,
                _LOGGER,
                name=DOMAIN,
                update_interval=scan_interval,
            )

        def _parse_mb8600_json(self, data: dict) -> dict[str, Any]:
            """Parse MB8600 JSON response."""
            return parse_mb8600_json(data)

        def _parse_cgm4331com_html(self, html: str) -> dict[str, Any]:
            """Parse CGM4331COM/CGM4981COM HTML response."""
            return parse_cgm4331com_html(html)

        async def _async_update_data(self) -> dict[str, Any]:
            """Update data via library."""
            try:
                _LOGGER.debug("Starting data update for %s model at %s", self.model, self.host)

                async with async_timeout.timeout(10):
                    protocol = "https" if self.use_ssl else "http"

                    if self.model == "MB8600":
                        url = f"{protocol}://{self.host}/HNAP1"
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

                        _LOGGER.debug("Sending request to MB8600 at %s", url)
                        async with self.session.post(url, json=payload, headers=headers) as response:
                            response.raise_for_status()
                            data = await response.json()
                            result = self._parse_mb8600_json(data)
                            _LOGGER.debug("Successfully parsed data from MB8600")
                            return result
                    else:  # CGM4331COM or CGM4981COM
                        if not self.username or not self.password:
                            raise UpdateFailed("Username and password are required for CGM models")

                        # First request to get session cookie
                        login_url = f"{protocol}://{self.host}/check.jst"
                        payload = {
                            "username": self.username,
                            "password": self.password,
                        }
                        headers = {
                            "Content-Type": "application/x-www-form-urlencoded",
                        }

                        _LOGGER.debug("Authenticating to CGM model at %s", login_url)
                        async with self.session.post(login_url, data=payload, headers=headers, allow_redirects=False) as response:
                            if response.status not in (301, 302):
                                _LOGGER.error("Authentication failed with status %s", response.status)
                                raise UpdateFailed("Authentication failed")

                            cookies = response.cookies
                            if not cookies:
                                _LOGGER.error("No session cookies received")
                                raise UpdateFailed("No session cookie received")

                            _LOGGER.debug("Authentication successful, received cookies")

                        # Second request to get the data
                        data_url = f"{protocol}://{self.host}/network_setup.jst"
                        _LOGGER.debug("Getting data from %s", data_url)
                        async with self.session.get(data_url, cookies=cookies) as response:
                            response.raise_for_status()
                            html = await response.text()
                            _LOGGER.debug("Got HTML response of length %d", len(html))
                            result = self._parse_cgm4331com_html(html)
                            _LOGGER.debug("Successfully parsed data from CGM model")
                            return result

            except Exception as err:
                _LOGGER.exception("Error communicating with modem")
                raise UpdateFailed(f"Error communicating with modem: {err}") from err
