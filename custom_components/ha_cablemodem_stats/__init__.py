"""The Arris/Motorola Cable Modem Stats integration."""
from __future__ import annotations

from datetime import timedelta
import logging
import re
from typing import Any
from bs4 import BeautifulSoup
import json

import aiohttp
import async_timeout
import voluptuous as vol

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
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, SUPPORTED_MODELS

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Arris Modem Stats from a config entry."""
    host = entry.data[CONF_HOST]
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    use_ssl = entry.data.get(CONF_SSL, True)
    model = entry.data["model"]
    
    # Get scan interval from config, default to 5 minutes if not specified
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds())
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

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

def parse_uptime(text: str) -> int:
    """Parse uptime string to seconds."""
    days = hours = minutes = seconds = 0
    
    # Parse format: "x days xxh:xxm:xxs"
    match = re.match(r"(\d+) days (\d+)h:(\d+)m:(\d+)s", text)
    if match:
        days, hours, minutes, seconds = map(int, match.groups())
    else:
        # Parse format: "x days xxh xxm xxs"
        parts = text.split()
        for i, part in enumerate(parts):
            if part == "days":
                days = int(parts[i-1])
            elif part.endswith("h"):
                hours = int(part[:-1])
            elif part.endswith("m"):
                minutes = int(part[:-1])
            elif part.endswith("s"):
                seconds = int(part[:-1])
    
    return days * 86400 + hours * 3600 + minutes * 60 + seconds

class ArrisModemDataUpdateCoordinator(DataUpdateCoordinator):
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
        result = {
            "downstream": {},
            "upstream": {},
        }

        # Parse downstream channels
        ds_channels = data["GetMultipleHNAPsResponse"]["GetMotoStatusDownstreamChannelInfoResponse"]["MotoConnDownstreamChannel"].split("|+|")
        for channel_raw in ds_channels:
            if not channel_raw:
                continue
            channel_data = channel_raw.split("^")
            channel_num = int(channel_data[0])
            result["downstream"][channel_num] = {
                "channel": channel_num,
                "lock_status": channel_data[1],
                "modulation": channel_data[2],
                "channel_id": int(channel_data[3]),
                "frequency": float(channel_data[4]),
                "power": float(channel_data[5]),
                "snr": float(channel_data[6]),
                "corrected_errors": int(channel_data[7]),
                "uncorrected_errors": int(channel_data[8]),
            }

        # Parse upstream channels
        us_channels = data["GetMultipleHNAPsResponse"]["GetMotoStatusUpstreamChannelInfoResponse"]["MotoConnUpstreamChannel"].split("|+|")
        for channel_raw in us_channels:
            if not channel_raw:
                continue
            channel_data = channel_raw.split("^")
            channel_num = int(channel_data[0])
            result["upstream"][channel_num] = {
                "channel": channel_num,
                "lock_status": channel_data[1],
                "modulation": channel_data[2],
                "channel_id": int(channel_data[3]),
                "symbol_rate": int(channel_data[4]),
                "frequency": float(channel_data[5]),
                "power": float(channel_data[6]),
            }

        # Get system uptime
        uptime_str = data["GetMultipleHNAPsResponse"]["GetMotoStatusConnectionInfoResponse"]["MotoConnSystemUpTime"]
        result["system_uptime"] = parse_uptime(uptime_str)

        return result

    def _parse_cgm4331com_html(self, html: str) -> dict[str, Any]:
        """Parse CGM4331COM/CGM4981COM HTML response."""
        soup = BeautifulSoup(html, 'html.parser')
        result = {
            "downstream": {},
            "upstream": {},
        }

        # Find uptime
        uptime_row = soup.find("span", text="System Uptime:")
        if uptime_row:
            uptime_str = uptime_row.find_next_sibling("span").text
            result["system_uptime"] = parse_uptime(uptime_str)
            _LOGGER.debug("Found uptime: %s", uptime_str)
        else:
            _LOGGER.warning("Could not find uptime in HTML response")

        # Process all tables (downstream, upstream, errors)
        tables = soup.find_all("tbody")
        _LOGGER.debug("Found %d tables in HTML response", len(tables))
        
        if len(tables) >= 3:  # We need at least 3 tables for DS, US, and errors
            # Parse downstream data
            downstream_table = tables[0]
            downstream_rows = downstream_table.find_all("tr")
            _LOGGER.debug("Downstream table has %d rows", len(downstream_rows))
            
            # Extract values from each row
            # For downstream, we need to use the pattern of the table to extract values
            
            # First, gather all row data
            downstream_data = {}
            for row in downstream_rows:
                th = row.find("th")
                if not th:
                    continue
                
                header = th.text.strip().split('\n')[0].strip()
                
                # We need to collect all td values for this row
                values = []
                for td in row.find_all("td"):
                    for div in td.find_all("div"):
                        values.append(div.text.strip())
                
                if not values and header == "Channel ID":
                    # Try to extract individual channel values from first row
                    # In some cases, values are concatenated in the TH rather than in TD divs
                    full_text = th.text.strip()
                    if '\n' in full_text:
                        value_text = full_text.split('\n', 1)[1].strip()
                        # Look for groups of digits in the value text
                        channel_ids = re.findall(r'\d+', value_text)
                        
                        # If we still see a giant concatenated number, try to break it up
                        if len(channel_ids) == 1 and len(channel_ids[0]) > 3:
                            # Try breaking it every 1-2 digits
                            values = []
                            giant_id = channel_ids[0]
                            i = 0
                            while i < len(giant_id):
                                if i+2 < len(giant_id) and int(giant_id[i:i+3]) < 100:
                                    # This is likely a 2-digit channel ID
                                    values.append(giant_id[i:i+2])
                                    i += 2
                                else:
                                    # This is likely a 1-digit channel ID
                                    values.append(giant_id[i])
                                    i += 1
                        else:
                            values = channel_ids
                
                downstream_data[header] = values
                _LOGGER.debug("Downstream row '%s' has %d values: %s", 
                             header, len(values), values[:5])
            
            # Now let's process these values and create channel objects
            # First, we need to determine how many channels we have
            num_ds_channels = max([len(values) for values in downstream_data.values()])
            _LOGGER.debug("Detected %d downstream channels", num_ds_channels)
            
            # If we have channel IDs, use them to create our channels
            if "Channel ID" in downstream_data and downstream_data["Channel ID"]:
                # Create channel objects
                for i in range(num_ds_channels):
                    channel_num = i + 1  # 1-based channel index
                    if i < len(downstream_data["Channel ID"]):
                        try:
                            channel_id = int(downstream_data["Channel ID"][i])
                        except (ValueError, TypeError):
                            channel_id = channel_num
                    else:
                        channel_id = channel_num
                    
                    result["downstream"][channel_num] = {
                        "channel": channel_num,
                        "channel_id": channel_id,
                        "lock_status": "",
                        "modulation": "",
                        "frequency": 0.0,
                        "power": 0.0,
                        "snr": 0.0,
                        "corrected_errors": 0,
                        "uncorrected_errors": 0,
                    }
                
                # Now set the channel values
                for header, values in downstream_data.items():
                    # Skip channel ID since we already used it
                    if header == "Channel ID":
                        continue
                    
                    # Process each value according to its header
                    for i, value in enumerate(values):
                        channel_num = i + 1
                        if channel_num not in result["downstream"]:
                            continue  # Skip if we don't have this channel
                        
                        if header == "Lock Status":
                            result["downstream"][channel_num]["lock_status"] = value
                        elif header == "Frequency":
                            # Extract number and handle unit
                            freq_match = re.match(r'(\d+(?:\.\d+)?)\s*(\w*)', value)
                            if freq_match:
                                freq = float(freq_match.group(1))
                                # Convert to MHz if needed
                                if freq_match.group(2) != "MHz" and freq > 1000000:
                                    freq /= 1000000.0
                                result["downstream"][channel_num]["frequency"] = freq
                        elif header == "SNR":
                            # Extract number and ignore unit (dB)
                            snr_match = re.match(r'(\d+(?:\.\d+)?)', value)
                            if snr_match:
                                result["downstream"][channel_num]["snr"] = float(snr_match.group(1))
                        elif header == "Power Level":
                            # Extract number and ignore unit (dBmV)
                            power_match = re.match(r'([+-]?\d+(?:\.\d+)?)', value)
                            if power_match:
                                result["downstream"][channel_num]["power"] = float(power_match.group(1))
                        elif header == "Modulation":
                            result["downstream"][channel_num]["modulation"] = value
            
            # Parse upstream data
            if len(tables) > 1:
                upstream_table = tables[1]
                upstream_rows = upstream_table.find_all("tr")
                _LOGGER.debug("Upstream table has %d rows", len(upstream_rows))
                
                # Extract values from each row
                upstream_data = {}
                for row in upstream_rows:
                    th = row.find("th")
                    if not th:
                        continue
                    
                    header = th.text.strip().split('\n')[0].strip()
                    
                    # We need to collect all td values for this row
                    values = []
                    for td in row.find_all("td"):
                        for div in td.find_all("div"):
                            values.append(div.text.strip())
                    
                    if not values and header == "Channel ID":
                        # Try to extract values from TH if no TD found
                        full_text = th.text.strip()
                        if '\n' in full_text:
                            value_text = full_text.split('\n', 1)[1].strip()
                            # Look for groups of digits in the value text
                            channel_ids = re.findall(r'\d+', value_text)
                            
                            # If we still see a giant concatenated number, try to break it up
                            if len(channel_ids) == 1 and len(channel_ids[0]) > 3:
                                # Try breaking it every 1-2 digits
                                values = []
                                giant_id = channel_ids[0]
                                i = 0
                                while i < len(giant_id):
                                    if i+2 < len(giant_id) and int(giant_id[i:i+3]) < 100:
                                        # This is likely a 2-digit channel ID
                                        values.append(giant_id[i:i+2])
                                        i += 2
                                    else:
                                        # This is likely a 1-digit channel ID
                                        values.append(giant_id[i])
                                        i += 1
                            else:
                                values = channel_ids
                    
                    upstream_data[header] = values
                    _LOGGER.debug("Upstream row '%s' has %d values: %s", 
                                header, len(values), values[:5])
                
                # Now let's process these values and create channel objects
                # First, we need to determine how many channels we have
                num_us_channels = max([len(values) for values in upstream_data.values()])
                _LOGGER.debug("Detected %d upstream channels", num_us_channels)
                
                # If we have channel IDs, use them to create our channels
                if "Channel ID" in upstream_data and upstream_data["Channel ID"]:
                    # Create channel objects
                    for i in range(num_us_channels):
                        channel_num = i + 1  # 1-based channel index
                        if i < len(upstream_data["Channel ID"]):
                            try:
                                channel_id = int(upstream_data["Channel ID"][i])
                            except (ValueError, TypeError):
                                channel_id = channel_num
                        else:
                            channel_id = channel_num
                        
                        result["upstream"][channel_num] = {
                            "channel": channel_num,
                            "channel_id": channel_id,
                            "lock_status": "",
                            "modulation": "",
                            "frequency": 0.0,
                            "power": 0.0,
                            "symbol_rate": 0,
                        }
                    
                    # Now set the channel values
                    for header, values in upstream_data.items():
                        # Skip channel ID since we already used it
                        if header == "Channel ID":
                            continue
                        
                        # Process each value according to its header
                        for i, value in enumerate(values):
                            channel_num = i + 1
                            if channel_num not in result["upstream"]:
                                continue  # Skip if we don't have this channel
                            
                            if header == "Lock Status":
                                result["upstream"][channel_num]["lock_status"] = value
                            elif header == "Frequency":
                                # Extract number and handle unit
                                freq_match = re.match(r'(\d+(?:\.\d+)?)\s*(\w*)', value)
                                if freq_match:
                                    freq = float(freq_match.group(1))
                                    # Convert to MHz if needed
                                    if freq_match.group(2) != "MHz" and freq > 1000000:
                                        freq /= 1000000.0
                                    result["upstream"][channel_num]["frequency"] = freq
                            elif header == "Symbol Rate":
                                # Extract number (no unit expected)
                                rate_match = re.match(r'(\d+)', value)
                                if rate_match:
                                    result["upstream"][channel_num]["symbol_rate"] = int(rate_match.group(1))
                            elif header == "Power Level":
                                # Extract number and ignore unit (dBmV)
                                power_match = re.match(r'([+-]?\d+(?:\.\d+)?)', value)
                                if power_match:
                                    result["upstream"][channel_num]["power"] = float(power_match.group(1))
                            elif header == "Modulation":
                                result["upstream"][channel_num]["modulation"] = value
            
            # Parse error data (third table) if available
            if len(tables) > 2:
                error_table = tables[2]
                error_rows = error_table.find_all("tr")
                _LOGGER.debug("Error table has %d rows", len(error_rows))
                
                # Extract values from each row
                error_data = {}
                for row in error_rows:
                    th = row.find("th")
                    if not th:
                        continue
                    
                    header = th.text.strip().split('\n')[0].strip()
                    
                    # We need to collect all td values for this row
                    values = []
                    for td in row.find_all("td"):
                        for div in td.find_all("div"):
                            values.append(div.text.strip())
                    
                    if not values:
                        # Try to extract from TH if no TD found
                        full_text = th.text.strip()
                        if '\n' in full_text:
                            value_text = full_text.split('\n', 1)[1].strip()
                            
                            # These are error values, which may be large numbers
                            # We need to split them into individual channel values
                            if header == "Channel ID":
                                channel_ids = re.findall(r'\d+', value_text)
                                if len(channel_ids) == 1 and len(channel_ids[0]) > 3:
                                    # Similar breaking logic as above
                                    values = []
                                    giant_id = channel_ids[0]
                                    i = 0
                                    while i < len(giant_id):
                                        if i+2 < len(giant_id) and int(giant_id[i:i+3]) < 100:
                                            values.append(giant_id[i:i+2])
                                            i += 2
                                        else:
                                            values.append(giant_id[i])
                                            i += 1
                                else:
                                    values = channel_ids
                            elif header in ["Correctable Codewords", "Uncorrectable Codewords"]:
                                # For error counts, we need to carefully match the channel IDs
                                error_values = []
                                if "Channel ID" in error_data:
                                    # Split the large number into parts that match the channel count
                                    big_value = re.sub(r'[^\d]', '', value_text)
                                    chunk_size = len(big_value) // len(error_data["Channel ID"])
                                    if chunk_size > 0:
                                        for i in range(0, len(big_value), chunk_size):
                                            end = min(i + chunk_size, len(big_value))
                                            error_values.append(big_value[i:end])
                                    else:
                                        # Fallback: just try to find numbers
                                        error_values = re.findall(r'\d+', value_text)
                                else:
                                    error_values = re.findall(r'\d+', value_text)
                                values = error_values
                    
                    error_data[header] = values
                    _LOGGER.debug("Error row '%s' has %d values: %s", 
                                header, len(values), values[:5])
                
                # Now assign error values to downstream channels if available
                if "Channel ID" in error_data and "Correctable Codewords" in error_data and "Uncorrectable Codewords" in error_data:
                    for i, channel_id in enumerate(error_data["Channel ID"]):
                        channel_num = i + 1
                        if channel_num in result["downstream"]:
                            if i < len(error_data["Correctable Codewords"]):
                                try:
                                    result["downstream"][channel_num]["corrected_errors"] = int(error_data["Correctable Codewords"][i])
                                except (ValueError, TypeError):
                                    # Skip if we can't convert to int
                                    pass
                            
                            if i < len(error_data["Uncorrectable Codewords"]):
                                try:
                                    result["downstream"][channel_num]["uncorrected_errors"] = int(error_data["Uncorrectable Codewords"][i])
                                except (ValueError, TypeError):
                                    # Skip if we can't convert to int
                                    pass

        _LOGGER.debug("Parsed data has %d downstream channels and %d upstream channels", 
                     len(result["downstream"]), len(result["upstream"]))
        
        # Log an example channel if available
        if result["downstream"] and 1 in result["downstream"]:
            _LOGGER.debug("Example downstream channel 1: %s", result["downstream"][1])
        if result["upstream"] and 1 in result["upstream"]:
            _LOGGER.debug("Example upstream channel 1: %s", result["upstream"][1])
            
        return result

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
                        if not response.status in (301, 302):  # Should get a redirect on success
                            _LOGGER.error("Authentication failed with status %s", response.status)
                            raise UpdateFailed("Authentication failed")
                        
                        # Get session cookie
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
            _LOGGER.exception("Error communicating with modem")  # This will log the full stack trace
            raise UpdateFailed(f"Error communicating with modem: {err}") 