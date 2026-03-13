"""Veltium EV Charger Integration."""
import logging
import re
from collections import defaultdict

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_START
from homeassistant.core import HomeAssistant, CoreState, callback
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

    # Set up sensor entities
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register websocket commands
    async_register_websockets(hass)

    # Schedule backfill AFTER Home Assistant is fully started (like edata).
    # This ensures the recorder is fully running and processing jobs.
    @callback
    def _schedule_backfill(*_args):
        """Schedule the backfill task once HA is fully started."""
        hass.async_create_task(_async_backfill_historical_data(hass, coordinator))

    if hass.state == CoreState.running:
        _schedule_backfill()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _schedule_backfill)

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
        _LOGGER.info("Veltium backfill: device_id=%s, records=%d", device_id, len(records) if records else 0)

        if not records:
            _LOGGER.info("Veltium backfill: no records available, skipping.")
            return

        # External statistics format: "domain:name" (same pattern as edata)
        # Sanitize device_id: HA only allows lowercase alphanumeric + underscores in statistic_ids
        safe_id = re.sub(r"[^a-z0-9_]", "_", device_id.lower()).strip("_")
        statistic_id = f"{DOMAIN}:{safe_id}_total_energy"
        _LOGGER.info("Veltium backfill: statistic_id=%s (raw device_id=%s)", statistic_id, device_id)

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

        # Check for existing statistics — resilient to API signature changes
        last_timestamp = 0
        running_sum = 0.0
        try:
            last_stats = await db.async_add_executor_job(
                get_last_statistics, hass, 1, statistic_id, True, {"sum", "state"}
            )
            if statistic_id in last_stats and last_stats[statistic_id]:
                last_stat = last_stats[statistic_id][0]
                last_timestamp = last_stat.get("start", 0)
                running_sum = last_stat.get("sum", 0.0)
                _LOGGER.info("Veltium backfill: resuming from last_timestamp=%s, running_sum=%s", last_timestamp, running_sum)
            else:
                _LOGGER.info("Veltium backfill: no existing statistics found, starting fresh.")
        except Exception:
            _LOGGER.warning("Veltium backfill: get_last_statistics failed (API signature change?), starting fresh.")
            last_timestamp = 0
            running_sum = 0.0

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
            _LOGGER.info("Veltium backfill: no new records to inject (last at %s).", last_timestamp)
            return

        _LOGGER.info("Veltium backfill: %d new records to process.", len(new_records))

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
                "Veltium backfill: injecting %d hourly statistics (statistic_id=%s, final_sum=%.3f kWh).",
                len(statistics),
                statistic_id,
                running_sum,
            )
            async_add_external_statistics(hass, metadata, statistics)
            _LOGGER.info("Veltium backfill: async_add_external_statistics called successfully.")

    except Exception:
        _LOGGER.exception("Veltium backfill: FAILED to backfill historical energy data.")
