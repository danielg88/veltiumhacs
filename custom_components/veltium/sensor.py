"""Sensors for Veltium EV Charger."""
import logging
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Veltium sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = [
        VeltiumLifetimeSensor(coordinator),
        VeltiumMonthlySensor(coordinator),
        VeltiumDailySensor(coordinator),
    ]
    async_add_entities(sensors)

class VeltiumBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Veltium sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_id = coordinator.data["device_id"]
        
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self.device_id)},
            "name": coordinator.data["device_name"],
            "manufacturer": "Veltium",
        }

class VeltiumLifetimeSensor(VeltiumBaseSensor):
    """Lifetime Energy Sensor."""

    _attr_name = "Total Energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def unique_id(self):
        """Return unique ID."""
        return f"{self.device_id}_total_energy"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data["lifetime_energy"]

class VeltiumMonthlySensor(VeltiumBaseSensor):
    """Monthly Energy Sensor."""

    _attr_name = "Monthly Energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def unique_id(self):
        """Return unique ID."""
        return f"{self.device_id}_monthly_energy"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data["monthly_energy"]

class VeltiumDailySensor(VeltiumBaseSensor):
    """Daily Energy Sensor."""

    _attr_name = "Daily Energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def unique_id(self):
        """Return unique ID."""
        return f"{self.device_id}_daily_energy"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data["daily_energy"]
