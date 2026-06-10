"""Constants for the WLED Task Map integration."""

DOMAIN = "wled_taskmap"

CONF_HOST = "host"
CONF_SEGMENT = "segment"
CONF_MAPPINGS = "mappings"

# Rule keys
CONF_ENTITY_ID = "entity_id"
CONF_LEDS = "leds"
CONF_COLOR = "color"
CONF_COLOR2 = "color2"  # "" = single color, hex = gradient end, "RAINBOW" = hue sweep
CONF_ALERT_STATES = "alert_states"
CONF_EFFECT = "effect"  # solid | blink | pulse
CONF_FOR_MINUTES = "for_minutes"  # flap protection: condition must hold this long
CONF_FILL_MIN = "fill_min"  # fill effect: value mapped to 0% of the LED block
CONF_FILL_MAX = "fill_max"  # fill effect: value mapped to 100% of the LED block

# Quiet hours (entry options)
CONF_QUIET_START = "quiet_start"  # "22:00"
CONF_QUIET_END = "quiet_end"  # "07:00"
CONF_QUIET_MODE = "quiet_mode"  # off | dim | hide

# Legacy rule keys (pre-0.4.0), migrated automatically
CONF_LED = "led"
CONF_LED_COUNT = "led_count"

DEFAULT_SEGMENT = 0
DEFAULT_COLOR = "FF0000"
DEFAULT_ALERT_STATES = "unavailable,unknown,error,problem"
DEFAULT_EFFECT = "solid"
OFF_COLOR = "000000"

EFFECTS = ["solid", "blink", "pulse", "fill"]
QUIET_MODES = ["off", "dim", "hide", "strip_off"]
DIM_FACTOR = 0.25
PULSE_LOW_FACTOR = 0.15
BLINK_INTERVAL = 1.0  # seconds

# LED pet (tamagotchi) — entry options
CONF_PET = "pet"  # {"enabled": bool, "start": int, "size": int, "sources": [...]}

PET_MOODS = {
    # mood: (r, g, b base color, min brightness, breath depth, move every N ticks)
    "happy": ((0, 220, 140), 0.35, 0.65, 1),
    "content": ((60, 140, 255), 0.25, 0.45, 3),
    "grumpy": ((255, 120, 0), 0.15, 0.25, 6),
    "sad": ((110, 110, 110), 0.08, 0.10, 0),  # 0 = doesn't move
}

SERVICE_SET_ALERT = "set_alert"
SERVICE_CLEAR_ALERT = "clear_alert"
SERVICE_CLEAR_ALL = "clear_all"

ATTR_LED = "led"
ATTR_COLOR = "color"

SIGNAL_UPDATE = f"{DOMAIN}_update"

CARD_URL = f"/{DOMAIN}/wled-taskmap-card.js"
