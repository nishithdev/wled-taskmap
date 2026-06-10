"""WLED Task Map - light up LEDs when tasks/entities need attention."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.util import dt as dt_util

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import (
    ATTR_COLOR,
    ATTR_LED,
    BLINK_INTERVAL,
    CARD_URL,
    CONF_ALERT_STATES,
    CONF_COLOR,
    CONF_EFFECT,
    CONF_ENTITY_ID,
    CONF_HOST,
    CONF_LED,
    CONF_LED_COUNT,
    CONF_LEDS,
    CONF_MAPPINGS,
    CONF_QUIET_END,
    CONF_QUIET_MODE,
    CONF_QUIET_START,
    CONF_SEGMENT,
    DEFAULT_ALERT_STATES,
    DEFAULT_COLOR,
    DEFAULT_EFFECT,
    DEFAULT_SEGMENT,
    DIM_FACTOR,
    DOMAIN,
    EFFECTS,
    OFF_COLOR,
    PULSE_LOW_FACTOR,
    QUIET_MODES,
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

COMPARATORS = (">=", "<=", "!=", ">", "<", "=")


def normalize_rule(rule: dict) -> dict:
    """Return a rule in current format, migrating legacy led/led_count."""
    if CONF_LEDS in rule:
        leds = sorted({int(x) for x in rule[CONF_LEDS]})
    else:
        start = int(rule.get(CONF_LED, 0))
        count = max(1, int(rule.get(CONF_LED_COUNT, 1)))
        leds = list(range(start, start + count))
    effect = rule.get(CONF_EFFECT, DEFAULT_EFFECT)
    if effect not in EFFECTS:
        effect = DEFAULT_EFFECT
    return {
        CONF_ENTITY_ID: rule[CONF_ENTITY_ID],
        CONF_LEDS: leds,
        CONF_COLOR: str(rule.get(CONF_COLOR, DEFAULT_COLOR)).lstrip("#").upper(),
        CONF_ALERT_STATES: rule.get(CONF_ALERT_STATES, DEFAULT_ALERT_STATES),
        CONF_EFFECT: effect,
    }


def _dim(color: str, factor: float) -> str:
    try:
        r, g, b = (int(color[i : i + 2], 16) for i in (0, 2, 4))
        return f"{int(r * factor):02X}{int(g * factor):02X}{int(b * factor):02X}"
    except (ValueError, IndexError):
        return color


def _match_condition(token: str, value: str) -> bool:
    """Match one condition token: a state string or a numeric comparison."""
    token = token.strip()
    for op in COMPARATORS:
        if token.startswith(op):
            try:
                threshold = float(token[len(op) :].strip())
                num = float(value)
            except (ValueError, TypeError):
                return False
            return {
                ">": num > threshold,
                "<": num < threshold,
                ">=": num >= threshold,
                "<=": num <= threshold,
                "=": num == threshold,
                "!=": num != threshold,
            }[op]
    return value.lower() == token.lower()


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
        self.led_count: int = 30
        self.rule_alerts: dict[int, bool] = {}
        self.manual_alerts: dict[int, str] = {}
        # snapshot of the strip (led -> hex) taken before we started painting
        self.snapshot: dict[int, str] | None = None
        self._phase = True  # blink phase
        self._was_quiet: bool | None = None
        self._unsub_state = None
        self._unsub_blink = None
        self._unsub_minute = None
        self._lock = asyncio.Lock()

    # ---------- quiet hours ----------

    @property
    def quiet_mode(self) -> str:
        mode = self.entry.options.get(CONF_QUIET_MODE, "off")
        return mode if mode in QUIET_MODES else "off"

    def _in_quiet(self) -> bool:
        if self.quiet_mode == "off":
            return False
        start = self.entry.options.get(CONF_QUIET_START) or ""
        end = self.entry.options.get(CONF_QUIET_END) or ""
        try:
            sh, sm = (int(x) for x in start.split(":"))
            eh, em = (int(x) for x in end.split(":"))
        except (ValueError, AttributeError):
            return False
        now = dt_util.now().time()  # HA-configured timezone, not server OS clock
        s = sh * 60 + sm
        e = eh * 60 + em
        n = now.hour * 60 + now.minute
        if s == e:
            return False
        if s < e:
            return s <= n < e
        return n >= s or n < e  # window crosses midnight

    # ---------- alert evaluation ----------

    def _is_alert(self, rule: dict, state) -> bool:
        if state is None:
            return False
        value = state.state
        tokens = [
            t.strip()
            for t in rule.get(CONF_ALERT_STATES, DEFAULT_ALERT_STATES).split(",")
            if t.strip()
        ]
        if rule[CONF_ENTITY_ID].startswith("todo."):
            # Numeric tokens (e.g. ">3") override the default "any pending item"
            numeric = [t for t in tokens if t.startswith(COMPARATORS)]
            if numeric:
                return any(_match_condition(t, value) for t in numeric)
            try:
                return int(float(value)) > 0
            except (ValueError, TypeError):
                return value in ("unavailable", "unknown")
        return any(_match_condition(t, value) for t in tokens)

    def refresh_entity(self, entity_id: str) -> None:
        state = self.hass.states.get(entity_id)
        for idx, rule in enumerate(self.rules):
            if rule[CONF_ENTITY_ID] == entity_id:
                self.rule_alerts[idx] = self._is_alert(rule, state)

    def refresh_all(self) -> None:
        for entity_id in {r[CONF_ENTITY_ID] for r in self.rules}:
            self.refresh_entity(entity_id)

    @property
    def active_alerts(self) -> dict[int, tuple[str, str]]:
        """Return led -> (color, effect) for everything currently alerting."""
        leds: dict[int, tuple[str, str]] = {}
        for idx, rule in enumerate(self.rules):
            if not self.rule_alerts.get(idx):
                continue
            for led in rule[CONF_LEDS]:
                leds[led] = (rule[CONF_COLOR], rule[CONF_EFFECT])
        for led, color in self.manual_alerts.items():
            leds[led] = (color, "solid")
        return leds

    @property
    def all_leds(self) -> set[int]:
        leds: set[int] = set()
        for rule in self.rules:
            leds.update(rule[CONF_LEDS])
        leds.update(self.manual_alerts)
        if self.snapshot:
            leds.update(self.snapshot)
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

    async def _take_snapshot(self) -> None:
        """Remember what mapped LEDs showed before we start painting."""
        if self.snapshot is not None:
            return
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"http://{self.host}/json/live", timeout=10
            ) as resp:
                data = await resp.json()
                colors = data.get("leds", [])
                self.snapshot = {
                    led: colors[led] for led in self.all_leds if led < len(colors)
                }
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("No live snapshot from %s: %s", self.host, err)
            self.snapshot = {}

    def _background(self, led: int) -> str:
        if self.snapshot and led in self.snapshot:
            return self.snapshot[led]
        return OFF_COLOR

    async def _send(self, i_array: list, turn_on: bool = False) -> None:
        if not i_array:
            return
        payload: dict = {"seg": [{"id": self.segment, "i": i_array}]}
        if turn_on:
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

    async def push(self) -> None:
        """Reconcile the strip with the current alert state."""
        async with self._lock:
            active = self.active_alerts
            quiet = self._in_quiet()
            hidden = quiet and self.quiet_mode == "hide"

            if active and not hidden:
                await self._take_snapshot()
                i_array: list = []
                for led in sorted(self.all_leds):
                    if led in active:
                        color, effect = active[led]
                        if quiet and self.quiet_mode == "dim":
                            color = _dim(color, DIM_FACTOR)
                        if effect == "blink" and not self._phase:
                            color = self._background(led)
                        elif effect == "pulse" and not self._phase:
                            color = _dim(color, PULSE_LOW_FACTOR)
                    else:
                        color = self._background(led)
                    i_array.extend([led, color])
                await self._send(i_array, turn_on=True)
                self._manage_blink(
                    any(e != "solid" for _, e in active.values())
                )
            else:
                # No visible alerts: restore whatever the strip showed before
                if self.snapshot is not None:
                    i_array = []
                    for led in sorted(self.all_leds):
                        i_array.extend([led, self._background(led)])
                    await self._send(i_array)
                    self.snapshot = None
                self._manage_blink(False)

        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    async def flash(self, leds: list[int], color: str, times: int = 3) -> None:
        """Briefly flash specific LEDs so the user can locate them."""
        await self._take_snapshot()
        for _ in range(times):
            await self._send(
                [v for led in leds for v in (led, color)], turn_on=True
            )
            await asyncio.sleep(0.35)
            await self._send(
                [v for led in leds for v in (led, self._background(led))]
            )
            await asyncio.sleep(0.2)
        await self.push()

    # ---------- timers ----------

    def _manage_blink(self, needed: bool) -> None:
        if needed and self._unsub_blink is None:

            @callback
            def _tick(_now) -> None:
                self._phase = not self._phase
                self.hass.async_create_task(self.push())

            self._unsub_blink = async_track_time_interval(
                self.hass, _tick, timedelta(seconds=BLINK_INTERVAL)
            )
        elif not needed and self._unsub_blink is not None:
            self._unsub_blink()
            self._unsub_blink = None
            self._phase = True

    # ---------- lifecycle ----------

    async def async_start(self) -> None:
        await self.fetch_info()
        entity_ids = sorted({r[CONF_ENTITY_ID] for r in self.rules})
        if entity_ids:

            @callback
            def _state_changed(event: Event) -> None:
                self.refresh_entity(event.data["entity_id"])
                self.hass.async_create_task(self.push())

            self._unsub_state = async_track_state_change_event(
                self.hass, entity_ids, _state_changed
            )

        if self.quiet_mode != "off":

            @callback
            def _minute(_now) -> None:
                quiet = self._in_quiet()
                if quiet != self._was_quiet:
                    self._was_quiet = quiet
                    self.hass.async_create_task(self.push())

            self._was_quiet = self._in_quiet()
            self._unsub_minute = async_track_time_interval(
                self.hass, _minute, timedelta(seconds=60)
            )

        self.refresh_all()
        await self.push()

    async def async_stop(self) -> None:
        for unsub in (self._unsub_state, self._unsub_blink, self._unsub_minute):
            if unsub:
                unsub()
        self._unsub_state = self._unsub_blink = self._unsub_minute = None


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
                "active": {led: c for led, (c, _e) in manager.active_alerts.items()},
                "quiet": {
                    "start": manager.entry.options.get(CONF_QUIET_START, ""),
                    "end": manager.entry.options.get(CONF_QUIET_END, ""),
                    "mode": manager.quiet_mode,
                },
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
                vol.Optional(CONF_EFFECT, default=DEFAULT_EFFECT): vol.In(EFFECTS),
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


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save_settings",
        vol.Required("entry_id"): str,
        vol.Required(CONF_QUIET_START): str,
        vol.Required(CONF_QUIET_END): str,
        vol.Required(CONF_QUIET_MODE): vol.In(QUIET_MODES),
    }
)
@websocket_api.async_response
async def ws_save_settings(hass, connection, msg) -> None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_QUIET_START: msg[CONF_QUIET_START],
            CONF_QUIET_END: msg[CONF_QUIET_END],
            CONF_QUIET_MODE: msg[CONF_QUIET_MODE],
        },
    )
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/test_rule",
        vol.Required("entry_id"): str,
        vol.Required(CONF_LEDS): [int],
        vol.Required(CONF_COLOR): str,
    }
)
@websocket_api.async_response
async def ws_test_rule(hass, connection, msg) -> None:
    manager = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    if manager is None:
        connection.send_error(msg["id"], "not_found", "Device not found")
        return
    await manager.flash(
        [int(x) for x in msg[CONF_LEDS]], msg[CONF_COLOR].lstrip("#").upper()
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
    websocket_api.async_register_command(hass, ws_save_settings)
    websocket_api.async_register_command(hass, ws_test_rule)


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
