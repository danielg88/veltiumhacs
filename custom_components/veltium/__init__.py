"""Veltium EV Charger Integration."""
import logging
import asyncio
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.components.recorder.statistics import async_import_statistics, get_last_statistics, StatisticData, StatisticMetaData
import homeassistant.util.dt as dt_util
from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD, CONF_API_KEY
from .coordinator import VeltiumDataUpdateCoordinator, decode_act_to_wh
from .websockets import async_register_websockets
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
    
    async_register_websockets(hass)
    
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
        source=DOMAIN,
        statistic_id=statistic_id,
        unit_of_measurement="kWh",
    )
    
    # Check if we already have statistics for this sensor
    # get_last_statistics returns a dict: {statistic_id: [{...}]}
    last_stats = await hass.async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, set()
    )
    
    last_stat = None
    if statistic_id in last_stats and last_stats[statistic_id]:
        last_stat = last_stats[statistic_id][0]
    
    last_timestamp = last_stat["start"] if last_stat else 0
    running_sum = last_stat["sum"] if last_stat and "sum" in last_stat else 0.0
    
    sorted_records = []
    for rid, record in records.items():
        end_ts = record.get("dis", 0)
        # Only process records that finished after our last recorded statistic
        # (Compare as raw timestamps roughly, or exact datetimes. LTS uses unix timestamps in ms usually, 
        # but let's be careful and construct the dt_hour to compare)
        if end_ts > 0:
            dt = dt_util.utc_from_timestamp(end_ts)
            dt_hour = dt.replace(minute=0, second=0, microsecond=0)
            
            # Start is returned as a float timestamp from get_last_statistics
            if not last_timestamp or dt_hour.timestamp() > last_timestamp:
                sorted_records.append(record)
            
    if not sorted_records:
        _LOGGER.debug(f"No new historical sessions to inject into LTS for Veltium (Last at {last_timestamp}).")
        return
        
    sorted_records.sort(key=lambda x: x["dis"])
    
    statistics = []
    
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

