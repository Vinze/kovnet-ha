"""Constants for KOVnet."""
from datetime import timedelta

DOMAIN = "kovnet"
CONF_CODE = "code"
CONF_RESEND = "resend"
CONF_TWO_FACTOR = "two_factor"  # token was obtained with an e-mailed code
CONF_TOKEN = "token"
CONF_USER_ID = "user_id"
CONF_CONTRACT_IDS = "contract_ids"
CONF_CONTRACT_ID = "contract_id"  # config entry v1 only
UPDATE_INTERVAL = timedelta(hours=1)
PLATFORMS = ["binary_sensor", "calendar", "sensor"]
