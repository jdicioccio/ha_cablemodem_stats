"""Support for Arris/Motorola Cable Modem sensors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS,
    UnitOfFrequency,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import ArrisModemDataUpdateCoordinator
from .const import (
    DOMAIN,
    FREQUENCY_MHZ,
    POWER_DBMV,
    SNR_DB,
    SYMBOL_RATE_KSPS,
)

_LOGGER = logging.getLogger(__name__)

@dataclass
class ArrisModemSensorEntityDescription(SensorEntityDescription):
    """Class describing Arris Modem sensor entities."""

    value_fn: Callable[[dict[str, Any], str, int], StateType] | None = None

def get_downstream_value(
    data: dict[str, Any], key: str, channel: int
) -> StateType:
    """Get value from downstream data."""
    try:
        if not data or not isinstance(data, dict):
            _LOGGER.warning("Invalid data structure: %s", data)
            return None

        if "downstream" not in data:
            _LOGGER.warning("No downstream key in data: %s", list(data.keys()))
            return None

        if channel not in data["downstream"]:
            # This is normal - not all channels will exist
            return None

        if key not in data["downstream"][channel]:
            _LOGGER.warning("Key %s not found in downstream channel %d data: %s", 
                          key, channel, list(data["downstream"][channel].keys()))
            return None

        return data["downstream"][channel][key]
    except Exception as e:
        _LOGGER.exception("Error getting downstream value for channel %d, key %s: %s", 
                         channel, key, e)
        return None

def get_upstream_value(
    data: dict[str, Any], key: str, channel: int
) -> StateType:
    """Get value from upstream data."""
    try:
        if not data or not isinstance(data, dict):
            _LOGGER.warning("Invalid data structure: %s", data)
            return None

        if "upstream" not in data:
            _LOGGER.warning("No upstream key in data: %s", list(data.keys()))
            return None

        if channel not in data["upstream"]:
            # This is normal - not all channels will exist
            return None

        if key not in data["upstream"][channel]:
            _LOGGER.warning("Key %s not found in upstream channel %d data: %s", 
                          key, channel, list(data["upstream"][channel].keys()))
            return None

        return data["upstream"][channel][key]
    except Exception as e:
        _LOGGER.exception("Error getting upstream value for channel %d, key %s: %s", 
                         channel, key, e)
        return None

DOWNSTREAM_SENSORS = [
    ArrisModemSensorEntityDescription(
        key="frequency",
        name="Frequency",
        native_unit_of_measurement=FREQUENCY_MHZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=get_downstream_value,
    ),
    ArrisModemSensorEntityDescription(
        key="power",
        name="Power",
        native_unit_of_measurement=POWER_DBMV,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=get_downstream_value,
    ),
    ArrisModemSensorEntityDescription(
        key="snr",
        name="SNR",
        native_unit_of_measurement=SNR_DB,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=get_downstream_value,
    ),
    ArrisModemSensorEntityDescription(
        key="corrected_errors",
        name="Corrected Errors",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=get_downstream_value,
    ),
    ArrisModemSensorEntityDescription(
        key="uncorrected_errors",
        name="Uncorrected Errors",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=get_downstream_value,
    ),
]

UPSTREAM_SENSORS = [
    ArrisModemSensorEntityDescription(
        key="frequency",
        name="Frequency",
        native_unit_of_measurement=FREQUENCY_MHZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=get_upstream_value,
    ),
    ArrisModemSensorEntityDescription(
        key="power",
        name="Power",
        native_unit_of_measurement=POWER_DBMV,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=get_upstream_value,
    ),
    ArrisModemSensorEntityDescription(
        key="symbol_rate",
        name="Symbol Rate",
        native_unit_of_measurement=SYMBOL_RATE_KSPS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=get_upstream_value,
    ),
]

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Arris Modem sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    
    _LOGGER.debug("Setting up sensor entities, data available: %s", coordinator.data is not None)
    
    if coordinator.data:
        downstream_channels = list(coordinator.data.get("downstream", {}).keys())
        upstream_channels = list(coordinator.data.get("upstream", {}).keys())
        _LOGGER.debug("Found downstream channels: %s", downstream_channels)
        _LOGGER.debug("Found upstream channels: %s", upstream_channels)
    
    # Add downstream channel sensors
    for channel in range(1, 33):  # Support up to 32 channels
        for description in DOWNSTREAM_SENSORS:
            entities.append(
                ArrisModemSensor(
                    coordinator,
                    description,
                    channel,
                    "Downstream",
                )
            )

    # Add upstream channel sensors
    for channel in range(1, 9):  # Support up to 8 channels
        for description in UPSTREAM_SENSORS:
            entities.append(
                ArrisModemSensor(
                    coordinator,
                    description,
                    channel,
                    "Upstream",
                )
            )

    _LOGGER.debug("Adding %d sensor entities", len(entities))
    async_add_entities(entities)

class ArrisModemSensor(CoordinatorEntity, SensorEntity):
    """Implementation of an Arris Modem sensor."""

    entity_description: ArrisModemSensorEntityDescription

    def __init__(
        self,
        coordinator: ArrisModemDataUpdateCoordinator,
        description: ArrisModemSensorEntityDescription,
        channel: int,
        direction: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._channel = channel
        self._direction = direction
        self._attr_name = f"{direction} {description.name} Ch.{channel}"
        self._attr_unique_id = f"{coordinator.host}_{direction}_{description.key}_{channel}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.host)},
            "name": f"Cable Modem {coordinator.model}",
            "manufacturer": "Xfinity",
            "model": coordinator.model,
        }
        _LOGGER.debug("Created sensor %s", self._attr_name)

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            _LOGGER.warning("No data available from coordinator for %s", self._attr_name)
            return None
            
        if self.entity_description.value_fn is None:
            _LOGGER.warning("No value_fn for %s", self._attr_name)
            return None

        value = self.entity_description.value_fn(
            self.coordinator.data,
            self.entity_description.key,
            self._channel,
        )
        
        # Only log if debugging and the value exists (to avoid log spam)
        if _LOGGER.isEnabledFor(logging.DEBUG) and value is not None:
            _LOGGER.debug("%s = %s", self._attr_name, value)
            
        return value

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.coordinator.data is None:
            _LOGGER.debug("Sensor %s unavailable - no data", self._attr_name)
            return False
            
        # Check if this channel exists in the data
        data_key = "downstream" if self._direction == "Downstream" else "upstream"
        
        if data_key not in self.coordinator.data:
            _LOGGER.debug("Sensor %s unavailable - no %s data", self._attr_name, data_key)
            return False
            
        if self._channel not in self.coordinator.data[data_key]:
            # Don't log this as it would generate too many messages
            # Only channels that exist should be marked available
            return False
            
        # If we get here, the entity is available
        return True 