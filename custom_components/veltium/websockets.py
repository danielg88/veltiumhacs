"""Websockets related definitions for Veltium EV Charger."""
import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta
from collections import defaultdict

import voluptuous as vol

from homeassistant.components.websocket_api import (
    async_register_command,
    async_response,
    websocket_command,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import decode_act_to_wh

_LOGGER = logging.getLogger(__name__)


def get_db_instance(hass: HomeAssistant):
    """Workaround for older HA versions/recorder access."""
    try:
        return recorder_util.get_instance(hass)
    except AttributeError:
        return hass


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/ws/consumptions",
        vol.Required("device_id"): str,
        vol.Optional("aggr", default="day"): vol.In(
            ["day", "hour", "week", "month", "year"]
        ),
        vol.Optional("records", default=30): int,
    }
)
@async_response
async def ws_get_consumptions(hass: HomeAssistant, connection, msg):
    """Fetch consumptions history directly from coordinator data."""

    device_id = msg["device_id"]
    aggr = msg["aggr"]
    records_count = msg["records"]

    _LOGGER.debug(f"Received websocket request for device {device_id}, aggr {aggr}, {records_count} records")

    # Find the coordinator that matches this device_id
    coordinator = None
    for entry_id in hass.data.get(DOMAIN, {}):
        coord = hass.data[DOMAIN][entry_id]
        if coord.data.get("device_id") == device_id or device_id == "charger": # Basic matching
             coordinator = coord
             break
    
    if not coordinator or not coordinator.data.get("records"):
        _LOGGER.warning(f"No coordinator or records found for device {device_id}")
        connection.send_result(msg["id"], [])
        return

    raw_records = coordinator.data.get("records", {})
    
    # Process aggregation
    aggregated_data = defaultdict(float)
    
    for rid, record in raw_records.items():
        wh = decode_act_to_wh(record.get("act", ""))
        kwh = wh / 1000.0
        
        end_ts = record.get("dis", 0)
        if end_ts == 0:
            continue
            
        dt = dt_util.utc_from_timestamp(end_ts)
        local_dt = dt_util.as_local(dt)
        
        if aggr == "hour":
            key = local_dt.replace(minute=0, second=0, microsecond=0)
        elif aggr == "day":
            key = local_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        elif aggr == "week":
            key = (local_dt - relativedelta(days=local_dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        elif aggr == "month":
            key = local_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif aggr == "year":
            key = local_dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            key = local_dt.replace(hour=0, minute=0, second=0, microsecond=0)

        aggregated_data[key] += kwh
    # Sort and filter by records count
    sorted_keys = sorted(aggregated_data.keys(), reverse=True)
    if records_count > 0:
        sorted_keys = sorted_keys[:records_count]
    
    result = []
    for key in reversed(sorted_keys):
        result.append((
            key.isoformat(),
            round(aggregated_data[key], 3)
        ))

    _LOGGER.debug(f"Sending {len(result)} records to websocket for {device_id}")
    connection.send_result(msg["id"], result)


def async_register_websockets(hass: HomeAssistant):
    """Register websockets into HA API."""
    async_register_command(hass, ws_get_consumptions)
