"""Veltium EV Charger Integration."""
import logging
from collections import defaultdict

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
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

    # Set up sensor entities first so they exist in the registry
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register websocket commands
    async_register_websockets(hass)

    # Run the backfill task AFTER entities are set up (avoids race condition)
    hass.async_create_task(_async_backfill_historical_data(hass, coordinator))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _async_backfill_historical_data(hass: HomeAssistant, coordinator: VeltiumDataUpdateCoordinator):
    """Inject past charge sessions into HA Long-Term Statistics (external statistics)."""
    try:
        import homeassistant.components.recorder.util as recorder_util
        from homeassistant.components.recorder.statistics import (
            async_add_external_statistics,
            get_last_statistics,
            StatisticData,
            StatisticMetaData,
        )

        device_id = coordinator.data["device_id"]
        records = coordinator.data["records"]

        if not records:
            _LOGGER.debug("No records available for backfill.")
            return

        # External statistics format: "domain:name" (same pattern as edata)
        statistic_id = f"{DOMAIN}:{device_id}_total_energy"

        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name="Veltium Total Energy",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement="kWh",
        )

        # Get the recorder instance (edata-compatible helper)
        def _get_db_instance():
            try:
                return recorder_util.get_instance(hass)
            except AttributeError:
                return hass

        db = _get_db_instance()

        # Check if we already have statistics — pass correct types set
        last_stats = await db.async_add_executor_job(
            get_last_statistics, hass, 1, statistic_id, True, {"sum", "state"}
        )

        last_stat = None
        if statistic_id in last_stats and last_stats[statistic_id]:
            last_stat = last_stats[statistic_id][0]

        last_timestamp = last_stat["start"] if last_stat else 0
        running_sum = last_stat.get("sum", 0.0) if last_stat else 0.0

        # Filter records that are newer than our last recorded statistic
        new_records = []
        for rid, record in records.items():
            end_ts = record.get("dis", 0)
            if end_ts > 0:
                dt = dt_util.utc_from_timestamp(end_ts)
                dt_hour = dt.replace(minute=0, second=0, microsecond=0)

                if not last_timestamp or dt_hour.timestamp() > last_timestamp:
                    new_records.append(record)

        if not new_records:
            _LOGGER.debug(
                "No new historical sessions to inject into LTS for Veltium (last at %s).",
                last_timestamp,
            )
            return

        # Sort records chronologically
        new_records.sort(key=lambda x: x.get("dis", 0))

        # Pre-aggregate records by hour bucket to avoid duplicate entries
        hourly_buckets: dict[float, float] = defaultdict(float)
        for record in new_records:
            kwh = decode_act_to_wh(record.get("act", "")) / 1000.0
            end_ts = record["dis"]
            dt = dt_util.utc_from_timestamp(end_ts)
            dt_hour = dt.replace(minute=0, second=0, microsecond=0)
            hourly_buckets[dt_hour.timestamp()] += kwh

        # Build statistics: state = per-hour consumption, sum = cumulative total
        # (This matches the edata pattern exactly)
        statistics = []
        for hour_ts in sorted(hourly_buckets.keys()):
            hour_kwh = hourly_buckets[hour_ts]
            running_sum += hour_kwh
            dt_hour = dt_util.utc_from_timestamp(hour_ts)
            statistics.append(
                StatisticData(
                    start=dt_hour,
                    state=hour_kwh,
                    sum=running_sum,
                )
            )

        if statistics:
            _LOGGER.info(
                "Injecting %d hourly statistics into LTS for Veltium (statistic_id=%s).",
                len(statistics),
                statistic_id,
            )
            async_add_external_statistics(hass, metadata, statistics)

    except Exception:
        _LOGGER.exception("Failed to backfill historical energy data for Veltium.")


