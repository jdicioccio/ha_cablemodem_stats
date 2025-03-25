# Cable Modem Stats Integration for Home Assistant

This integration allows you to monitor your Arris/Motorola and Xfinity cable modem statistics in Home Assistant. It provides sensors for downstream and upstream channels, including signal levels, SNR, errors, and more.

## Supported Models

- Arris/Motorola MB8600
- Xfinity XB7 (CGM4331COM)
- Xfinity XB8 (CGM4981COM)

## Installation

1. Copy this folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant
3. Go to Settings -> Devices & Services
4. Click "Add Integration"
5. Search for "Xfinity Cable Modem Stats"
6. Follow the configuration steps

## Configuration

The integration can be configured through the UI. You'll need:

- Host: The IP address of your cable modem
- Model: Select your modem model from the list
- Username (optional): Required for CGM4331COM and CGM4981COM models
- Password (optional): Required for CGM4331COM and CGM4981COM models
- Use SSL: Whether to use HTTPS for connecting to the modem (default: true)

## Available Sensors

### Downstream Channels

For each downstream channel:
- Frequency (MHz)
- Power Level (dBmV)
- Signal to Noise Ratio (dB)
- Corrected Errors
- Uncorrected Errors
- Lock Status
- Modulation

### Upstream Channels

For each upstream channel:
- Frequency (MHz)
- Power Level (dBmV)
- Symbol Rate (Ksps)
- Lock Status
- Modulation

### System Information

- System Uptime

## Troubleshooting

1. Make sure you can access your modem's web interface using the same IP address
2. For CGM4331COM and CGM4981COM models, verify your username and password
3. If you have connection issues, try disabling SSL
4. Check the Home Assistant logs for detailed error messages

## Credits

This integration is based on the [cablemodem_stats](https://github.com/jdicioccio/cablemodem_stats) project. 
