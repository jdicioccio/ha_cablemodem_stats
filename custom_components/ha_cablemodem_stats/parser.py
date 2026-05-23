"""Pure parsing logic for cable modem responses.

This module contains the standalone functions that parse raw data
from supported modems into the internal data structure used by the
integration.

It has no dependency on Home Assistant. It is the single source of
truth for parsing and is used both by the real integration and by
the offline test CLI.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)


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
                days = int(parts[i - 1])
            elif part.endswith("h"):
                hours = int(part[:-1])
            elif part.endswith("m"):
                minutes = int(part[:-1])
            elif part.endswith("s"):
                seconds = int(part[:-1])

    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def parse_mb8600_json(data: dict) -> dict[str, Any]:
    """Parse MB8600 JSON (HNAP) response into the internal data format."""
    result = {
        "downstream": {},
        "upstream": {},
    }

    # Parse downstream channels
    ds_channels = (
        data["GetMultipleHNAPsResponse"]["GetMotoStatusDownstreamChannelInfoResponse"][
            "MotoConnDownstreamChannel"
        ].split("|+|")
    )
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
    us_channels = (
        data["GetMultipleHNAPsResponse"]["GetMotoStatusUpstreamChannelInfoResponse"][
            "MotoConnUpstreamChannel"
        ].split("|+|")
    )
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
    uptime_str = data["GetMultipleHNAPsResponse"]["GetMotoStatusConnectionInfoResponse"][
        "MotoConnSystemUpTime"
    ]
    result["system_uptime"] = parse_uptime(uptime_str)

    return result


def parse_cgm4331com_html(html: str) -> dict[str, Any]:
    """Parse CGM4331COM / CGM4981COM HTML response into the internal data format."""
    soup = BeautifulSoup(html, "html.parser")
    result = {
        "downstream": {},
        "upstream": {},
    }

    # Find uptime
    uptime_row = soup.find("span", string="System Uptime:")
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

        # First, gather all row data
        downstream_data = {}
        for row in downstream_rows:
            th = row.find("th")
            if not th:
                continue

            header = th.text.strip().split("\n")[0].strip()

            # Use the centralized helper that handles both <td><div> and the
            # "everything crammed in <th>" cases the modem produces.
            values = _extract_values_from_row(th, row.find_all("td"))

            # The very first row ("Channel ID") sometimes contains a giant
            # concatenated string. Apply the dedicated splitter.
            if header == "Channel ID" and len(values) == 1 and len(values[0]) > 3:
                values = _split_concatenated_ids(values[0])

            downstream_data[header] = values
            _LOGGER.debug(
                "Downstream row '%s' has %d values: %s",
                header,
                len(values),
                values[:5],
            )

        # Determine how many channels we have
        num_ds_channels = max([len(values) for values in downstream_data.values()])
        _LOGGER.debug("Detected %d downstream channels", num_ds_channels)

        if "Channel ID" in downstream_data and downstream_data["Channel ID"]:
            # Create channel objects
            for i in range(num_ds_channels):
                channel_num = i + 1
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
                if header == "Channel ID":
                    continue

                for i, value in enumerate(values):
                    channel_num = i + 1
                    if channel_num not in result["downstream"]:
                        continue

                    if header == "Lock Status":
                        result["downstream"][channel_num]["lock_status"] = value
                    elif header == "Frequency":
                        freq_match = re.match(r"(\d+(?:\.\d+)?)\s*(\w*)", value)
                        if freq_match:
                            freq = float(freq_match.group(1))
                            if freq_match.group(2) != "MHz" and freq > 1000000:
                                freq /= 1000000.0
                            result["downstream"][channel_num]["frequency"] = freq
                    elif header == "SNR":
                        snr_match = re.match(r"(\d+(?:\.\d+)?)", value)
                        if snr_match:
                            result["downstream"][channel_num]["snr"] = float(
                                snr_match.group(1)
                            )
                    elif header == "Power Level":
                        power_match = re.match(r"([+-]?\d+(?:\.\d+)?)", value)
                        if power_match:
                            result["downstream"][channel_num]["power"] = float(
                                power_match.group(1)
                            )
                    elif header == "Modulation":
                        result["downstream"][channel_num]["modulation"] = value

        # Parse upstream data
        if len(tables) > 1:
            upstream_table = tables[1]
            upstream_rows = upstream_table.find_all("tr")
            _LOGGER.debug("Upstream table has %d rows", len(upstream_rows))

            upstream_data = {}
            for row in upstream_rows:
                th = row.find("th")
                if not th:
                    continue

                header = th.text.strip().split("\n")[0].strip()

                # Use the shared helper for both normal <td><div> and the
                # "giant concatenated string in <th>" cases.
                values = _extract_values_from_row(th, row.find_all("td"))

                if header == "Channel ID" and len(values) == 1 and len(values[0]) > 3:
                    values = _split_concatenated_ids(values[0])

                upstream_data[header] = values
                _LOGGER.debug(
                    "Upstream row '%s' has %d values: %s",
                    header,
                    len(values),
                    values[:5],
                )

            num_us_channels = max([len(values) for values in upstream_data.values()])
            _LOGGER.debug("Detected %d upstream channels", num_us_channels)

            if "Channel ID" in upstream_data and upstream_data["Channel ID"]:
                for i in range(num_us_channels):
                    channel_num = i + 1
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

                for header, values in upstream_data.items():
                    if header == "Channel ID":
                        continue

                    for i, value in enumerate(values):
                        channel_num = i + 1
                        if channel_num not in result["upstream"]:
                            continue

                        if header == "Lock Status":
                            result["upstream"][channel_num]["lock_status"] = value
                        elif header == "Frequency":
                            freq_match = re.match(r"(\d+(?:\.\d+)?)\s*(\w*)", value)
                            if freq_match:
                                freq = float(freq_match.group(1))
                                if freq_match.group(2) != "MHz" and freq > 1000000:
                                    freq /= 1000000.0
                                result["upstream"][channel_num]["frequency"] = freq
                        elif header == "Symbol Rate":
                            rate_match = re.match(r"(\d+)", value)
                            if rate_match:
                                result["upstream"][channel_num]["symbol_rate"] = int(
                                    rate_match.group(1)
                                )
                        elif header == "Power Level":
                            power_match = re.match(r"([+-]?\d+(?:\.\d+)?)", value)
                            if power_match:
                                result["upstream"][channel_num]["power"] = float(
                                    power_match.group(1)
                                )
                        elif header == "Modulation":
                            result["upstream"][channel_num]["modulation"] = value

        # Parse error data (third table) if available
        if len(tables) > 2:
            error_table = tables[2]
            error_rows = error_table.find_all("tr")
            _LOGGER.debug("Error table has %d rows", len(error_rows))

            error_data = {}
            for row in error_rows:
                th = row.find("th")
                if not th:
                    continue

                header = th.text.strip().split("\n")[0].strip()

                values = []
                for td in row.find_all("td"):
                    for div in td.find_all("div"):
                        values.append(div.text.strip())

                # Always use the helper for consistency
                values = _extract_values_from_row(th, row.find_all("td"))

                if header == "Channel ID" and len(values) == 1 and len(values[0]) > 3:
                    values = _split_concatenated_ids(values[0])
                elif header in ["Correctable Codewords", "Uncorrectable Codewords"]:
                    # The error rows often contain one giant concatenated number.
                    # We try to split it intelligently using the number of channels
                    # we already discovered from the Channel ID row.
                    if len(values) == 1 and len(values[0]) > 10:
                        big = values[0]
                        if "Channel ID" in error_data and error_data["Channel ID"]:
                            n_channels = len(error_data["Channel ID"])
                            chunk = max(1, len(big) // n_channels)
                            values = [big[i : i + chunk] for i in range(0, len(big), chunk)]
                        else:
                            # Fallback: just take all digit groups
                            values = re.findall(r"\d+", big)

                error_data[header] = values
                _LOGGER.debug(
                    "Error row '%s' has %d values: %s",
                    header,
                    len(values),
                    values[:5],
                )

            # Assign error values to downstream channels
            if (
                "Channel ID" in error_data
                and "Correctable Codewords" in error_data
                and "Uncorrectable Codewords" in error_data
            ):
                for i, channel_id in enumerate(error_data["Channel ID"]):
                    channel_num = i + 1
                    if channel_num in result["downstream"]:
                        if i < len(error_data["Correctable Codewords"]):
                            try:
                                result["downstream"][channel_num][
                                    "corrected_errors"
                                ] = int(error_data["Correctable Codewords"][i])
                            except (ValueError, TypeError):
                                pass

                        if i < len(error_data["Uncorrectable Codewords"]):
                            try:
                                result["downstream"][channel_num][
                                    "uncorrected_errors"
                                ] = int(error_data["Uncorrectable Codewords"][i])
                            except (ValueError, TypeError):
                                pass

    _LOGGER.debug(
        "Parsed data has %d downstream channels and %d upstream channels",
        len(result["downstream"]),
        len(result["upstream"]),
    )

    if result["downstream"] and 1 in result["downstream"]:
        _LOGGER.debug("Example downstream channel 1: %s", result["downstream"][1])
    if result["upstream"] and 1 in result["upstream"]:
        _LOGGER.debug("Example upstream channel 1: %s", result["upstream"][1])

    return result


# ---------------------------------------------------------------------------
# Internal helpers for the CGM HTML parser.
# These centralize the messy heuristics needed because the modem's HTML
# often puts all channel values inside a single <th> text node.
# ---------------------------------------------------------------------------


def _extract_values_from_row(th, tds) -> list[str]:
    """
    Extract the list of string values from a table row.

    The modem sometimes puts the label + all values in the <th> (with newlines
    or spaces as separators) and leaves the <td>s empty. Other times the values
    live in <td><div> elements. This helper normalizes both cases.
    """
    if th is None:
        return []

    # Primary path: values live in <td><div>
    values: list[str] = []
    for td in tds:
        for div in td.find_all("div"):
            text = div.get_text(strip=True)
            if text:
                values.append(text)

    if values:
        return values

    # Fallback: everything is crammed into the <th> text after the first line
    full_text = th.get_text(" ", strip=True)
    if "\n" in full_text:
        # Keep only the part after the first line (the label)
        parts = full_text.split("\n", 1)
        if len(parts) > 1:
            return [p.strip() for p in parts[1].split() if p.strip()]

    # Last resort: split the entire th text on whitespace
    return [p for p in full_text.split() if p]


def _split_concatenated_ids(text: str) -> list[str]:
    """
    Handle the 'giant concatenated number' case that appears in Channel ID
    and error rows (e.g. "201234567..." instead of separate values).

    The heuristic tries to split every 1-3 digits when the number is suspiciously long.
    """
    if not text or len(text) <= 3:
        return [text] if text else []

    # Only apply the splitting heuristic when we see a single very long token
    if len(text) > 3 and text.isdigit():
        ids: list[str] = []
        i = 0
        while i < len(text):
            # Try 2-digit first if it looks like a reasonable channel id (< 100)
            if i + 2 < len(text) and int(text[i : i + 3]) < 100:
                ids.append(text[i : i + 2])
                i += 2
            else:
                ids.append(text[i])
                i += 1
        return ids

    return [text]
