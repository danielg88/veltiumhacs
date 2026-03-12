"""DataUpdateCoordinator for Veltium EV Charger."""
from datetime import timedelta, datetime
import logging
import base64

import requests

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .const import DOMAIN, DATABASE_URL, UPDATE_INTERVAL_HOURS

_LOGGER = logging.getLogger(__name__)

def decode_act_to_wh(act_base64: str) -> float:
    """Decode base64 act payload to Watt-hours."""
    if not act_base64:
        return 0.0
    try:
        raw = base64.b64decode(act_base64)
        total_wh = 0
        for i in range(0, len(raw), 2):
            if i + 1 < len(raw):
                total_wh += (raw[i] << 8) | raw[i + 1]
        return float(total_wh)
    except Exception:
        return 0.0

class VeltiumDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Veltium data from single endpoint."""

    def __init__(self, hass: HomeAssistant, email: str, password: str, api_key: str, local_id: str):
        """Initialize."""
        self.email = email
        self.password = password
        self.api_key = api_key
        self.local_id = local_id
        self.id_token = None
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=UPDATE_INTERVAL_HOURS),
        )

    async def _async_update_data(self):
        """Fetch data from Veltium Firebase."""
        try:
            return await self.hass.async_add_executor_job(self._fetch_data)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    def _authenticate(self):
        """Authenticate with Firebase and get a fresh token."""
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.api_key}"
        payload = {
            "email": self.email,
            "password": self.password,
            "returnSecureToken": True
        }
        res = requests.post(url, json=payload, timeout=10)
        data = res.json()
        if "error" in data:
            raise Exception(f"Auth failed: {data['error']['message']}")
            
        self.id_token = data["idToken"]

    def _fetch_data(self):
        """Synchronous data fetcher."""
        if not self.id_token:
            self._authenticate()

        # Try to fetch device data
        # First fetch user to get device ID
        user_url = f"{DATABASE_URL}/prod/users/{self.local_id}.json?auth={self.id_token}"
        user_res = requests.get(user_url, timeout=10)
        
        if user_res.status_code == 401:
            self._authenticate() # Token expired
            user_url = f"{DATABASE_URL}/prod/users/{self.local_id}.json?auth={self.id_token}"
            user_res = requests.get(user_url, timeout=10)

        user_data = user_res.json()
        if not user_data or "devices" not in user_data:
            raise UpdateFailed("No devices found for user.")
            
        device_id = list(user_data["devices"].keys())[0]
        
        # Fetch device full data
        dev_url = f"{DATABASE_URL}/prod/devices/{device_id}.json?auth={self.id_token}"
        dev_res = requests.get(dev_url, timeout=10)
        device_data = dev_res.json()
        
        if not device_data:
            raise UpdateFailed("No device data returned.")

        return self._process_data(device_data, device_id)

    def _process_data(self, device_data, device_id):
        """Calculate aggregating statistics from historical charge records."""
        records = device_data.get("records", {})
        
        lifetime_kwh = 0.0
        yearly_kwh = 0.0
        monthly_kwh = 0.0
        daily_kwh = 0.0
        
        now = dt_util.now()
        current_year = now.year
        current_month = now.month
        current_day = now.day

        # We will inject historical statistics via async_import_statistics later 
        # For now, calculate the sensors' primary states natively.
        for rid, record in records.items():
            wh = decode_act_to_wh(record.get("act", ""))
            kwh = wh / 1000.0
            lifetime_kwh += kwh
            
            end_ts = record.get("dis", 0)
            if end_ts > 0:
                end_dt = dt_util.utc_from_timestamp(end_ts)
                local_dt = dt_util.as_local(end_dt)
                
                if local_dt.year == current_year:
                    yearly_kwh += kwh
                    if local_dt.month == current_month:
                        monthly_kwh += kwh
                        if local_dt.day == current_day:
                            daily_kwh += kwh
                        
        device_name = device_data.get("name", f"Charger {device_id}")

        return {
            "device_id": device_id,
            "device_name": device_name,
            "lifetime_energy": round(lifetime_kwh, 3),
            "daily_energy": round(daily_kwh, 3),
            "monthly_energy": round(monthly_kwh, 3),
            "yearly_energy": round(yearly_kwh, 3),
            "records": records
        }
