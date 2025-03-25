"""Test script for the Arris/Motorola Cable Modem Stats integration."""
import asyncio
import logging
import sys
import re
from datetime import timedelta

import aiohttp
from bs4 import BeautifulSoup

from . import ArrisModemDataUpdateCoordinator

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
    if len(sys.argv) < 4:
        print("Usage: python -m custom_components.ha_cablemodem_stats host model username [password] [ssl]")
        print("Example: python -m custom_components.ha_cablemodem_stats 192.168.1.1 CGM4331COM admin password true")
        return

    host = sys.argv[1]
    model = sys.argv[2]
    username = sys.argv[3]
    password = sys.argv[4] if len(sys.argv) > 4 else None
    use_ssl = sys.argv[5].lower() == "true" if len(sys.argv) > 5 else True
    
    print(f"Testing connection to {model} at {host}")
    print(f"Using SSL: {use_ssl}, Username: {username}, Password: {'*'*len(password) if password else None}")

    async with aiohttp.ClientSession() as session:
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
                
                async with session.post(login_url, data=payload, headers=headers, allow_redirects=False) as response:
                    if response.status in (301, 302):
                        print("Authentication successful")
                        # Get session cookie
                        cookies = response.cookies
                        
                        # Get data
                        data_url = f"{protocol}://{host}/network_setup.jst"
                        async with session.get(data_url, cookies=cookies) as data_response:
                            if data_response.status == 200:
                                html = await data_response.text()
                                print(f"Got HTML response of {len(html)} bytes")
                                
                                # Analyze the HTML structure
                                print("\n===== HTML ANALYSIS =====")
                                await analyze_html(html, host)
                                print("=========================\n")
                    else:
                        print(f"Authentication failed with status {response.status}")
            
            # Now try the full data parsing
            print("\n===== FULL DATA PARSING =====")
            data = await coordinator._async_update_data()
            print("Successfully fetched data from modem")
            print(f"Data structure: {list(data.keys())}")
            
            if "downstream" in data:
                print(f"Downstream channels: {list(data['downstream'].keys())}")
                for channel in data["downstream"]:
                    print(f"Downstream channel {channel}: {data['downstream'][channel]}")
            
            if "upstream" in data:
                print(f"Upstream channels: {list(data['upstream'].keys())}")
                for channel in data["upstream"]:
                    print(f"Upstream channel {channel}: {data['upstream'][channel]}")
            
            print("===========================")
                    
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error fetching data: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 
