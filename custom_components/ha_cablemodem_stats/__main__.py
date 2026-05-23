"""Test / debug CLI for the ha_cablemodem_stats integration.

Primary use cases:
- Live testing against a real modem (original behavior)
- Fast offline iteration on the HTML/JSON parsers using saved responses
  (especially valuable for the complex CGM4331COM/CGM4981COM scraper)

Examples:
  # Live against modem
  python -m custom_components.ha_cablemodem_stats 192.168.100.1 CGM4331COM admin 'pass' true

  # Offline from a saved HTML capture (great for parser development)
  python -m custom_components.ha_cablemodem_stats --html-file /tmp/network_setup.html CGM4331COM

  # Live run that also saves the HTML for future offline use
  python -m custom_components.ha_cablemodem_stats --save-html /tmp/capture.html 192.168.100.1 CGM4331COM admin 'pass'
"""
import argparse
import asyncio
import logging
import pprint
import re
import sys
from datetime import timedelta

from bs4 import BeautifulSoup

# aiohttp is only needed for live network testing against the modem.
# We import it lazily so that --html-file mode works with just beautifulsoup4.

# The heavy Home Assistant import is deliberately kept out of the top level
# and only performed in the live (network) code path. The offline --html-file
# path imports only from .parser and has no Home Assistant dependency.

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

async def analyze_html(html, host):
    """Analyze HTML structure to help debug parsing issues."""
    soup = BeautifulSoup(html, 'html.parser')
    
    # Find tables
    tables = soup.find_all("tbody")
    print(f"Found {len(tables)} tables")
    
    for i, table in enumerate(tables):
        rows = table.find_all("tr")
        print(f"Table {i} has {len(rows)} rows")
        
        for row in rows:
            th = row.find("th")
            if th:
                full_text = th.text.strip()
                if "\n" in full_text:
                    parts = full_text.split("\n", 1)
                    row_name = parts[0].strip()
                    values_text = parts[1].strip()
                    print(f"Row '{row_name}' has values: {values_text[:50]}...")
                else:
                    print(f"Row has text without values: {full_text}")

async def main():
    """Run the test script."""
    parser = argparse.ArgumentParser(
        prog="python -m custom_components.ha_cablemodem_stats",
        description="Test and debug tool for the ha_cablemodem_stats integration.",
    )
    parser.add_argument(
        "--html-file",
        metavar="FILE",
        help="Parse a previously captured HTML response offline (CGM models). "
             "This is the fastest way to iterate on the HTML parser.",
    )
    parser.add_argument(
        "--save-html",
        metavar="FILE",
        help="During a live CGM run, also write the fetched HTML to this file "
             "so you can use --html-file for fast offline iteration later.",
    )
    parser.add_argument(
        "host",
        nargs="?",
        help="Modem IP or hostname (required unless --html-file is used)",
    )
    parser.add_argument(
        "model",
        metavar="model",
        choices=["MB8600", "CGM4331COM", "CGM4981COM"],
        help="Modem model to test",
    )
    parser.add_argument("username", nargs="?", default=None, help="Username for CGM models")
    parser.add_argument("password", nargs="?", default=None)
    parser.add_argument(
        "ssl",
        nargs="?",
        default="true",
        help="Use HTTPS (true/false). Default: true",
    )

    args = parser.parse_args()

    # ===================== OFFLINE / HTML FILE MODE =====================
    if args.html_file:
        print(f"=== OFFLINE MODE: loading {args.html_file} ===\n")
        try:
            with open(args.html_file, encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            print(f"ERROR: Failed to read {args.html_file}: {exc}")
            return

        print(f"Loaded {len(content)} bytes")

        if args.model in ["CGM4331COM", "CGM4981COM"]:
            print("\n===== HTML STRUCTURE ANALYSIS =====")
            await analyze_html(content, "file")
            print("===================================\n")

            print("===== PARSED RESULT (real production parser) =====")

            # Load parser.py directly via importlib so we completely bypass
            # the package's __init__.py (which still imports Home Assistant things).
            # This lets the offline mode run with *only* beautifulsoup4 installed.
            import importlib.util
            from pathlib import Path

            parser_path = Path(__file__).parent / "parser.py"
            spec = importlib.util.spec_from_file_location("ha_cablemodem_parser", parser_path)
            parser_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(parser_mod)

            result = parser_mod.parse_cgm4331com_html(content)
            print(f"Downstream channels: {list(result.get('downstream', {}).keys())}")
            print(f"Upstream channels:   {list(result.get('upstream', {}).keys())}")
            if result.get("system_uptime") is not None:
                print(f"System uptime (seconds): {result['system_uptime']}")
            print("\nFull data:")
            pprint.pprint(result)
            print("==================================================")
        else:
            print("Offline --html-file mode is only implemented for the CGM* models (HTML scraping).")
            print("For MB8600 you can still use live mode against the modem.")
        return

    # ===================== LIVE MODE (original behavior) =====================
    if not args.host:
        parser.error("host is required when not using --html-file")

    import aiohttp

    host = args.host
    model = args.model
    username = args.username
    password = args.password
    use_ssl = str(args.ssl).lower() == "true"

    print(f"Testing connection to {model} at {host}")
    pw_display = "*" * len(password) if password else None
    print(f"Using SSL: {use_ssl}, Username: {username}, Password: {pw_display}")
    if use_ssl:
        print("  (SSL certificate verification is disabled — normal for cable modems on LAN IPs)")

    # Use a connector that allows self-signed / invalid certificates.
    # Cable modems almost always serve self-signed certs on their LAN IP,
    # so strict verification would make --save-html captures unusable.
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        # NOTE: We no longer create the coordinator here.
        # It is only instantiated later, right before we call _async_update_data()
        # on it. This lets the CGM --save-html capture path (manual login + fetch
        # + direct parser call) run without Home Assistant installed.

        try:
            # First, try to get raw HTML for analysis if it's a CGM model
            if model in ["CGM4331COM", "CGM4981COM"]:
                protocol = "https" if use_ssl else "http"
                print(f"Getting raw HTML from {protocol}://{host}/network_setup.jst for analysis")

                # First authenticate
                login_url = f"{protocol}://{host}/check.jst"
                payload = {
                    "username": username,
                    "password": password,
                }
                headers = {
                    "Content-Type": "application/x-www-form-urlencoded",
                }

                async with session.post(
                    login_url, data=payload, headers=headers, allow_redirects=False
                ) as response:
                    if response.status in (301, 302):
                        print("Authentication successful")
                        cookies = response.cookies

                        data_url = f"{protocol}://{host}/network_setup.jst"
                        async with session.get(data_url, cookies=cookies) as data_response:
                            if data_response.status == 200:
                                html = await data_response.text()
                                print(f"Got HTML response of {len(html)} bytes")

                                if args.save_html:
                                    try:
                                        with open(args.save_html, "w", encoding="utf-8") as f:
                                            f.write(html)
                                        print(f"(saved raw HTML to {args.save_html} for future --html-file use)")
                                    except Exception as save_err:
                                        print(f"Warning: failed to save HTML: {save_err}")

                                print("\n===== HTML ANALYSIS =====")
                                await analyze_html(html, host)
                                print("=========================\n")

                                # Run the real parser on the just-captured HTML so the user
                                # gets the parsed result immediately (no HA required).
                                try:
                                    from .parser import parse_cgm4331com_html
                                    parsed = parse_cgm4331com_html(html)
                                    print("===== PARSED RESULT (from this capture) =====")
                                    print(f"Downstream channels: {list(parsed.get('downstream', {}).keys())}")
                                    print(f"Upstream channels:   {list(parsed.get('upstream', {}).keys())}")
                                    print("==============================================")
                                except Exception as parse_err:
                                    print(f"(Parser on captured HTML failed: {parse_err})")
                    else:
                        print(f"Authentication failed with status {response.status}")

            # Now run the real update path (exercises the production code path).
            # This is the only place we actually need the coordinator object.
            # We create it here (lazily) so that CGM --save-html captures can succeed
            # without Home Assistant being installed.
            print("\n===== FULL DATA PARSING (via _async_update_data) =====")

            from . import ArrisModemDataUpdateCoordinator
            coordinator = ArrisModemDataUpdateCoordinator(
                None,
                host=host,
                username=username,
                password=password,
                use_ssl=use_ssl,
                model=model,
                scan_interval=timedelta(minutes=5),
            )
            coordinator.session = session

            data = await coordinator._async_update_data()
            print("Successfully fetched and parsed data from modem")
            print(f"Data structure: {list(data.keys())}")

            if "downstream" in data:
                print(f"Downstream channels: {list(data['downstream'].keys())}")
                for channel in data["downstream"]:
                    print(f"Downstream channel {channel}: {data['downstream'][channel]}")

            if "upstream" in data:
                print(f"Upstream channels: {list(data['upstream'].keys())}")
                for channel in data["upstream"]:
                    print(f"Upstream channel {channel}: {data['upstream'][channel]}")

            print("=======================================================")

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error fetching data: {e}")


if __name__ == "__main__":
    asyncio.run(main())
