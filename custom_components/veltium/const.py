"""Constants for the Veltium EV Charger integration."""
import logging

DOMAIN = "veltium"
LOGGER = logging.getLogger(__package__)

DATABASE_URL = "https://veltiumbackend.firebaseio.com"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_API_KEY = "api_key"

# Update once a day
UPDATE_INTERVAL_HOURS = 24
