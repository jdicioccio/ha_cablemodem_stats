"""Constants for the Arris/Motorola Cable Modem Stats integration."""

DOMAIN = "ha_cablemodem_stats"

# Supported modem models
SUPPORTED_MODELS = ["MB8600", "CGM4331COM", "CGM4981COM"]

# Default values
DEFAULT_NAME = "Cable Modem"

# Sensor types
ATTR_CHANNEL = "channel"
ATTR_LOCK_STATUS = "lock_status"
ATTR_MODULATION = "modulation"
ATTR_CHANNEL_ID = "channel_id"
ATTR_FREQUENCY = "frequency"
ATTR_POWER = "power"
ATTR_SNR = "snr"
ATTR_CORRECTED_ERRORS = "corrected_errors"
ATTR_UNCORRECTED_ERRORS = "uncorrected_errors"
ATTR_SYMBOL_RATE = "symbol_rate"

# Unit constants
FREQUENCY_MHZ = "MHz"
POWER_DBMV = "dB"
SNR_DB = "dB"
SYMBOL_RATE_KSPS = "Ksps" 
