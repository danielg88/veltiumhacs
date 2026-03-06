"""Veltium EV Charger Integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.components.recorder.statistics import async_import_statistics, StatisticData, StatisticMetaData
import homeassistant.util.dt as dt_util
from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD, CONF_API_KEY
from .coordinator import VeltiumDataUpdateCoordinator, decode_act_to_wh
_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Veltium from a config entry."""
    coordinator = VeltiumDataUpdateCoordinator(
        hass, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], entry.data[CONF_API_KEY], entry.unique_id
    )
    
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    # Run the backfill task in the background
    hass.async_create_task(_async_backfill_historical_data(hass, coordinator))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
async def _async_backfill_historical_data(hass: HomeAssistant, coordinator: VeltiumDataUpdateCoordinator):
    """Elegantly inject past charge sessions into HA Long-Term Statistics."""
    device_id = coordinator.data["device_id"]
    records = coordinator.data["records"]
    
    if not records:
        return
        
    # Get exact entity_id from registry to match statistics to the sensor
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)
    unique_id = f"{device_id}_total_energy"
    entity_id = registry.async_get_entity_id(Platform.SENSOR, DOMAIN, unique_id)
    
    if entity_id:
        statistic_id = entity_id
    else:
        statistic_id = f"sensor.veltium_{device_id}_total_energy".lower()
    
    metadata = StatisticMetaData(
        has_mean=False,
        has_sum=True,
        name="Total Energy",
        source="recorder",
        statistic_id=statistic_id,
        unit_of_measurement="kWh",
    )
    
    sorted_records = []
    for rid, record in records.items():
        if record.get("dis", 0) > 0:
            sorted_records.append(record)
            
    sorted_records.sort(key=lambda x: x["dis"])
    
    statistics = []
    running_sum = 0.0
    
    for record in sorted_records:
        kwh = decode_act_to_wh(record.get("act", "")) / 1000.0
        running_sum += kwh
        
        end_ts = record["dis"]
        dt = dt_util.utc_from_timestamp(end_ts)
        dt_hour = dt.replace(minute=0, second=0, microsecond=0)
        
        statistics.append(
            StatisticData(
                start=dt_hour,
                state=running_sum,
                sum=running_sum
            )
        )
        
    if statistics:
        _LOGGER.debug(f"Injecting {len(statistics)} historical sessions into LTS for Veltium.")
        async_import_statistics(hass, metadata, statistics)
