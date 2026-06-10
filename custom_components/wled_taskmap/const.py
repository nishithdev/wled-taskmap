"""Constants for the WLED Task Map integration."""

DOMAIN = "wled_taskmap"

CONF_HOST = "host"
CONF_SEGMENT = "segment"
CONF_MAPPINGS = "mappings"

# Per-mapping keys
CONF_ENTITY_ID = "entity_id"
CONF_LED = "led"
CONF_COLOR = "color"
CONF_ALERT_STATES = "alert_states"

DEFAULT_SEGMENT = 0
DEFAULT_COLOR = "FF0000"
DEFAULT_ALERT_STATES = "unavailable,unknown,error,problem"
OFF_COLOR = "000000"

SERVICE_SET_ALERT = "set_alert"
SERVICE_CLEAR_ALERT = "clear_alert"
SERVICE_CLEAR_ALL = "clear_all"

ATTR_LED = "led"
ATTR_COLOR = "color"

SIGNAL_UPDATE = f"{DOMAIN}_update"
