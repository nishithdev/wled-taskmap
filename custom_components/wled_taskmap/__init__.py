"""WLED Task Map - light up LEDs when tasks/entities need attention."""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ATTR_COLOR,
    ATTR_LED,
    CARD_URL,
    CONF_ALERT_STATES,
    CONF_COLOR,
    CONF_ENTITY_ID,
    CONF_HOST,
    CONF_LED,
    CONF_LED_COUNT,
    CONF_LEDS,
    CONF_MAPPINGS,
    CONF_SEGMENT,
    DEFAULT_ALERT_STATES,
    DEFAULT_COLOR,
    DEFAULT_SEGMENT,
    DOMAIN,
    OFF_COLOR,
    SERVICE_CLEAR_ALERT,
    SERVICE_CLEAR_ALL,
    SERVICE_SET_ALERT,
    SIGNAL_UPDATE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

SET_ALERT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_LED): cv.positive_int,
        vol.Optional(ATTR_COLOR, default=DEFAULT_COLOR): cv.string,
    }
)
CLEAR_ALERT_SCHEMA = vol.Schema({vol.Required(ATTR_LED): cv.positive_int})


def normalize_rule(rule: dict) -> dict:
    """Return a rule in current format, migrating legacy led/led_count."""
    if CONF_LEDS in rule:
        leds = sorted({int(x) for x in rule[CONF_LEDS]})
    else:
        start = int(rule.get(CONF_LED, 0))
        count = max(1, int(rule.get(CONF_LED_COUNT, 1)))
        leds = list(range(start, start + count))
    return {
        CONF_ENTITY_ID: rule[CONF_ENTITY_ID],
        CONF_LEDS: leds,
        CONF_COLOR: str(rule.get(CONF_COLOR, DEFAULT_COLOR)).lstrip("#").upper(),
        CONF_ALERT_STATES: rule.get(CONF_ALERT_STATES, DEFAULT_ALERT_STATES),
    }


class TaskMapManager:
    """Watches entities and drives individual WLED LEDs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.host: str = entry.data[CONF_HOST]
        self.segment: int = entry.options.get(
            CONF_SEGMENT, entry.data.get(CONF_SEGMENT, DEFAULT_SEGMENT)
        )
        self.rules: list[dict] = [
            normalize_rule(r) for r in entry.options.get(CONF_MAPPINGS, [])
        ]
        self.led_count: int = 30  # refined from WLED /json/info at start
        # rule index -> currently alerting
        self.rule_alerts: dict[int, bool] = {}
        # led index -> color, for service-driven (manual / external) alerts
        self.manual_alerts: dict[int, str] = {}
        self._unsub = None

    # ---------- alert evaluation ----------

    def _is_alert(self, rule: dict, state) -> bool:
        if state is None:
            return False
        value = state.state
        if rule[CONF_ENTITY_ID].startswith("todo."):
            try:
                return int(float(value)) > 0
            except (ValueError, TypeError):
                return value in ("unavailable", "unknown")
        alert_states = [
            s.strip().lower()
            for s in rule.get(CONF_ALERT_STATES, DEFAULT_ALERT_STATES).split(",")
            if s.strip()
        ]
        return value.lower() in alert_states

    def refresh_entity(self, entity_id: str) -> None:
        state = self.hass.states.get(entity_id)
        for idx, rule in enumerate(self.rules):
            if rule[CONF_ENTITY_ID] == entity_id:
                self.rule_alerts[idx] = self._is_alert(rule, state)

    def refresh_all(self) -> None:
        for entity_id in {r[CONF_ENTITY_ID] for r in self.rules}:
            self.refresh_entity(entity_id)

    @property
    def active_alerts(self) -> dict[int, str]:
        """Return led -> color for everything currently alerting."""
        leds: dict[int, str] = {}
        for idx, rule in enumerate(self.rules):
            if not self.rule_alerts.get(idx):
                continue
            for led in rule[CONF_LEDS]:
                leds[led] = rule[CONF_COLOR]
        leds.update(self.manual_alerts)
        return leds

    @property
    def all_leds(self) -> set[int]:
        leds: set[int] = set()
        for rule in self.rules:
            leds.update(rule[CONF_LEDS])
        leds.update(self.manual_alerts)
        return leds

    @property
    def alerting_entities(self) -> list[str]:
        return sorted(
            {
                self.rules[idx][CONF_ENTITY_ID]
                for idx, alerting in self.rule_alerts.items()
                if alerting and idx < len(self.rules)
            }
        )

    # ---------- WLED control ----------

    async def fetch_info(self) -> None:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"http://{self.host}/json/info", timeout=10
            ) as resp:
                info = await resp.json()
                self.led_count = int(info.get("leds", {}).get("count", 30))
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not fetch WLED info from %s: %s", self.host, err)

    async def push(self) -> None:
        """Push current alert state to the WLED strip (individual LED control)."""
        active = self.active_alerts
        i_array: list = []
        for led in sorted(self.all_leds):
            i_array.extend([led, active.get(led, OFF_COLOR)])
        if i_array:
            payload: dict = {"seg": [{"id": self.segment, "i": i_array}]}
            if active:
                payload["on"] = True
            session = async_get_clientsession(self.hass)
            try:
                async with session.post(
                    f"http://{self.host}/json/state", json=payload, timeout=10
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning(
                            "WLED at %s returned HTTP %s", self.host, resp.status
                        )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Could not reach WLED at %s: %s", self.host, err)
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    # ---------- lifecycle ----------

    async def async_start(self) -> None:
        await self.fetch_info()
        entity_ids = sorted({r[CONF_ENTITY_ID] for r in self.rules})
        if entity_ids:

            @callback
            def _state_changed(event: Event) -> None:
                self.refresh_entity(event.data["entity_id"])
                self.hass.async_create_task(self.push())

            self._unsub = async_track_state_change_event(
                self.hass, entity_ids, _state_changed
            )
        self.refresh_all()
        await self.push()

    async def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None


# ---------- websocket API (used by the Lovelace card) ----------


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_config"})
@callback
def ws_get_config(hass, connection, msg) -> None:
    entries = []
    for entry_id, manager in hass.data.get(DOMAIN, {}).items():
        entries.append(
            {
                "entry_id": entry_id,
                "host": manager.host,
                "segment": manager.segment,
                "led_count": manager.led_count,
                "rules": manager.rules,
                "active": manager.active_alerts,
            }
        )
    connection.send_result(msg["id"], {"entries": entries})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save_rules",
        vol.Required("entry_id"): str,
        vol.Required("rules"): [
            {
                vol.Required(CONF_ENTITY_ID): str,
                vol.Required(CONF_LEDS): [int],
                vol.Required(CONF_COLOR): str,
                vol.Required(CONF_ALERT_STATES): str,
            }
        ],
    }
)
@websocket_api.async_response
async def ws_save_rules(hass, connection, msg) -> None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return
    rules = [normalize_rule(r) for r in msg["rules"]]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_MAPPINGS: rules}
    )
    connection.send_result(msg["id"], {"ok": True})


# ---------- setup ----------


async def _async_setup_shared(hass: HomeAssistant) -> None:
    """One-time setup: card asset + websocket commands."""
    if hass.data.get(f"{DOMAIN}_shared"):
        return
    hass.data[f"{DOMAIN}_shared"] = True

    card_path = Path(__file__).parent / "www" / "wled-taskmap-card.js"
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(card_path), True)]
        )
    except ImportError:
        hass.http.register_static_path(CARD_URL, str(card_path), True)
    add_extra_js_url(hass, CARD_URL)

    websocket_api.async_register_command(hass, ws_get_config)
    websocket_api.async_register_command(hass, ws_save_rules)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _async_setup_shared(hass)

    manager = TaskMapManager(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    await manager.async_start()

    async def handle_set_alert(call: ServiceCall) -> None:
        manager.manual_alerts[int(call.data[ATTR_LED])] = call.data[
            ATTR_COLOR
        ].lstrip("#")
        await manager.push()

    async def handle_clear_alert(call: ServiceCall) -> None:
        manager.manual_alerts.pop(int(call.data[ATTR_LED]), None)
        await manager.push()

    async def handle_clear_all(call: ServiceCall) -> None:
        manager.manual_alerts.clear()
        await manager.push()

    hass.services.async_register(
        DOMAIN, SERVICE_SET_ALERT, handle_set_alert, schema=SET_ALERT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_ALERT, handle_clear_alert, schema=CLEAR_ALERT_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_ALL, handle_clear_all)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_update_listener))
    return True


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager: TaskMapManager = hass.data[DOMAIN].pop(entry.entry_id)
    await manager.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
