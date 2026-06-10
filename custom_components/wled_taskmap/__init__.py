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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store

from .const import (
    ATTR_COLOR,
    ATTR_LED,
    BLINK_INTERVAL,
    CARD_URL,
    CONF_ALERT_STATES,
    CONF_COLOR,
    CONF_COLOR2,
    CONF_EFFECT,
    CONF_ENTITY_ID,
    CONF_FILL_MAX,
    CONF_FILL_MIN,
    CONF_FOR_MINUTES,
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
    try:
        for_minutes = max(0.0, float(rule.get(CONF_FOR_MINUTES, 0) or 0))
    except (ValueError, TypeError):
        for_minutes = 0.0

    def _num(key, default):
        try:
            return float(rule.get(key, default))
        except (ValueError, TypeError):
            return default

    fill_min = _num(CONF_FILL_MIN, 0.0)
    fill_max = _num(CONF_FILL_MAX, 100.0)
    if fill_max <= fill_min:
        fill_max = fill_min + 1.0
    color2 = str(rule.get(CONF_COLOR2, "") or "").lstrip("#").upper()
    if color2 != "RAINBOW" and len(color2) != 6:
        color2 = ""
    return {
        CONF_FILL_MIN: fill_min,
        CONF_FILL_MAX: fill_max,
        CONF_COLOR2: color2,
        CONF_ENTITY_ID: rule[CONF_ENTITY_ID],
        CONF_LEDS: leds,
        CONF_COLOR: str(rule.get(CONF_COLOR, DEFAULT_COLOR)).lstrip("#").upper(),
        CONF_ALERT_STATES: rule.get(CONF_ALERT_STATES, DEFAULT_ALERT_STATES),
        CONF_EFFECT: effect,
        CONF_FOR_MINUTES: for_minutes,
    }


def _dim(color: str, factor: float) -> str:
    try:
        r, g, b = (int(color[i : i + 2], 16) for i in (0, 2, 4))
        return f"{int(r * factor):02X}{int(g * factor):02X}{int(b * factor):02X}"
    except (ValueError, IndexError):
        return color


def _lerp_color(c1: str, c2: str, t: float) -> str:
    """Blend two hex colors through hue space, so red->green passes through
    orange and yellow instead of muddy olive."""
    import colorsys

    try:
        a = [int(c1[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        b = [int(c2[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    except (ValueError, IndexError):
        return c1
    h1, s1, v1 = colorsys.rgb_to_hsv(*a)
    h2, s2, v2 = colorsys.rgb_to_hsv(*b)
    if s1 < 0.05 or v1 < 0.05:  # gray/black endpoints: plain RGB blend
        r, g, bl = (a[i] + (b[i] - a[i]) * t for i in range(3))
    elif s2 < 0.05 or v2 < 0.05:
        r, g, bl = (a[i] + (b[i] - a[i]) * t for i in range(3))
    else:
        dh = h2 - h1  # take the shortest way around the hue wheel
        if dh > 0.5:
            dh -= 1.0
        elif dh < -0.5:
            dh += 1.0
        r, g, bl = colorsys.hsv_to_rgb(
            (h1 + dh * t) % 1.0, s1 + (s2 - s1) * t, v1 + (v2 - v1) * t
        )
    return f"{round(r * 255):02X}{round(g * 255):02X}{round(bl * 255):02X}"


def _rainbow(t: float) -> str:
    import colorsys

    r, g, b = colorsys.hsv_to_rgb(0.75 * t, 1.0, 1.0)  # red -> green -> blue/violet
    return f"{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"


def _rule_color_at(rule: dict, pos: int, total: int) -> str:
    """Color for the LED at position pos of total in this rule's block."""
    color2 = rule.get(CONF_COLOR2, "")
    if not color2:
        return rule[CONF_COLOR]
    t = pos / (total - 1) if total > 1 else 0.0
    if color2 == "RAINBOW":
        return _rainbow(t)
    return _lerp_color(rule[CONF_COLOR], color2, t)


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
        # LEDs currently holding an alert color; persisted so reloads/restarts
        # can clean up LEDs that no current rule covers anymore
        self._painted: set[int] = set()
        self._store = Store(hass, 1, f"{DOMAIN}.painted_{entry.entry_id}")
        self._phase = True  # blink phase
        self._was_quiet: bool | None = None
        self._strip_was_on = True  # strip power state before strip_off quiet
        self._unsub_state = None
        self._unsub_blink = None
        self._unsub_minute = None
        self._unsub_registry = None
        self._offline = False  # avoid log spam while WLED is unreachable
        # rule idx -> cancel callback for a pending "for N minutes" timer
        self._pending: dict[int, callback] = {}
        # rule idx -> last alert state written to the logbook
        self._last_logged: dict[int, bool] = {}
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
        if rule.get(CONF_EFFECT) == "fill":
            # Fill rules are "on" whenever the entity reports a number
            try:
                float(value)
                return True
            except (ValueError, TypeError):
                return False
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

    def _cancel_pending(self, idx: int) -> None:
        if idx in self._pending:
            self._pending.pop(idx)()

    def refresh_entity(self, entity_id: str) -> None:
        state = self.hass.states.get(entity_id)
        for idx, rule in enumerate(self.rules):
            if rule[CONF_ENTITY_ID] != entity_id:
                continue
            raw = self._is_alert(rule, state)
            if not raw:
                self._cancel_pending(idx)
                self.rule_alerts[idx] = False
                continue
            if self.rule_alerts.get(idx):
                continue  # already alerting
            delay = rule.get(CONF_FOR_MINUTES, 0)
            if delay <= 0:
                self.rule_alerts[idx] = True
            elif idx not in self._pending:
                self._pending[idx] = async_call_later(
                    self.hass, delay * 60, self._make_delayed(idx)
                )

    def _make_delayed(self, idx: int):
        @callback
        def _fire(_now) -> None:
            self._pending.pop(idx, None)
            if idx >= len(self.rules):
                return
            rule = self.rules[idx]
            state = self.hass.states.get(rule[CONF_ENTITY_ID])
            if self._is_alert(rule, state):  # still true after the delay
                self.rule_alerts[idx] = True
                self.hass.async_create_task(self.push())

        return _fire

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
            if rule[CONF_EFFECT] == "fill":
                state = self.hass.states.get(rule[CONF_ENTITY_ID])
                try:
                    val = float(state.state) if state else None
                except (ValueError, TypeError):
                    val = None
                if val is None:
                    continue
                lo, hi = rule[CONF_FILL_MIN], rule[CONF_FILL_MAX]
                frac = max(0.0, min(1.0, (val - lo) / (hi - lo)))
                block = sorted(rule[CONF_LEDS])
                lit = round(frac * len(block))
                for pos, led in enumerate(block[:lit]):
                    leds[led] = (_rule_color_at(rule, pos, len(block)), "solid")
                continue
            block = sorted(rule[CONF_LEDS])
            for pos, led in enumerate(block):
                leds[led] = (
                    _rule_color_at(rule, pos, len(block)),
                    rule[CONF_EFFECT],
                )
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
                # LEDs we previously painted hold alert colors, not the user's
                # lighting — snapshot those as black, not as "background".
                self.snapshot = {
                    led: (OFF_COLOR if led in self._painted else colors[led])
                    for led in self.all_leds
                    if led < len(colors)
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
                elif self._offline:
                    self._offline = False
                    _LOGGER.info("WLED at %s is reachable again", self.host)
        except Exception as err:  # noqa: BLE001
            # Warn once, then stay quiet until the device recovers
            log = _LOGGER.debug if self._offline else _LOGGER.warning
            log("Could not reach WLED at %s: %s", self.host, err)
            self._offline = True

    async def push(self) -> None:
        """Reconcile the strip with the current alert state."""
        self._log_alert_changes()
        async with self._lock:
            active = self.active_alerts
            quiet = self._in_quiet()
            hidden = quiet and self.quiet_mode in ("hide", "strip_off")

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
                await self._update_painted(set(active))
            else:
                # No visible alerts: restore whatever the strip showed before
                if self.snapshot is not None:
                    i_array = []
                    for led in sorted(self.all_leds):
                        i_array.extend([led, self._background(led)])
                    await self._send(i_array)
                    self.snapshot = None
                elif self._painted:
                    # No snapshot (e.g. after restart) but LEDs still hold
                    # alert colors from before: turn them off explicitly.
                    await self._send(
                        [v for led in sorted(self._painted) for v in (led, OFF_COLOR)]
                    )
                self._manage_blink(False)
                await self._update_painted(set())

        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    async def _set_strip_power(self, on: bool) -> None:
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                f"http://{self.host}/json/state", json={"on": on}, timeout=10
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "WLED at %s returned HTTP %s", self.host, resp.status
                    )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not reach WLED at %s: %s", self.host, err)

    async def _get_strip_power(self) -> bool:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"http://{self.host}/json/state", timeout=10
            ) as resp:
                return bool((await resp.json()).get("on", True))
        except Exception:  # noqa: BLE001
            return True

    async def _apply_quiet_transition(self, entering: bool) -> None:
        """Handle strip power for the strip_off quiet mode."""
        if self.quiet_mode != "strip_off":
            return
        if entering:
            self._strip_was_on = await self._get_strip_power()
            await self._set_strip_power(False)
        elif self._strip_was_on:
            await self._set_strip_power(True)

    async def _update_painted(self, painted: set[int]) -> None:
        if painted != self._painted:
            self._painted = painted
            await self._store.async_save({"leds": sorted(painted)})

    async def flash(self, leds: list[int], color: str, times: int = 3) -> None:
        """Briefly flash specific LEDs so the user can locate them."""
        strip_off_quiet = self._in_quiet() and self.quiet_mode == "strip_off"
        was_on = await self._get_strip_power() if strip_off_quiet else True
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
        if strip_off_quiet and not was_on:
            await self._set_strip_power(False)  # back to quiet-hours darkness

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

    # ---------- logbook ----------

    def _log_alert_changes(self) -> None:
        """Write a logbook entry whenever a rule starts or stops alerting."""
        try:
            from homeassistant.components.logbook import async_log_entry
        except ImportError:
            return
        if "logbook" not in self.hass.config.components:
            return
        for idx, rule in enumerate(self.rules):
            if rule[CONF_EFFECT] == "fill":
                continue  # fill bars track values continuously; logging would spam
            now = bool(self.rule_alerts.get(idx))
            before = self._last_logged.get(idx)
            if before is None or before == now:
                self._last_logged[idx] = now
                continue
            self._last_logged[idx] = now
            entity_id = rule[CONF_ENTITY_ID]
            state = self.hass.states.get(entity_id)
            name = (
                state.attributes.get("friendly_name") if state else None
            ) or entity_id
            leds = rule[CONF_LEDS]
            leds_txt = (
                f"LED {leds[0]}" if len(leds) == 1 else f"LEDs {leds[0]}-{leds[-1]}"
            )
            if now:
                message = (
                    f"lit {leds_txt} ({state.state if state else 'unknown'})"
                )
            else:
                message = f"cleared {leds_txt}"
            async_log_entry(
                self.hass, name, message, DOMAIN, entity_id
            )

    # ---------- repairs & renames ----------

    def _check_missing_entities(self) -> None:
        """Raise a Repairs issue for rules watching entities that don't exist."""
        registry = er.async_get(self.hass)
        watched = {r[CONF_ENTITY_ID] for r in self.rules}
        for entity_id in watched:
            issue_id = f"missing_{self.entry.entry_id}_{entity_id}"
            missing = (
                self.hass.states.get(entity_id) is None
                and registry.async_get(entity_id) is None
            )
            if missing:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="missing_entity",
                    translation_placeholders={
                        "entity_id": entity_id,
                        "host": self.host,
                    },
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def _setup_rename_listener(self) -> None:
        """Rewrite rules automatically when a watched entity is renamed."""

        @callback
        def _registry_updated(event: Event) -> None:
            if event.data.get("action") == "remove":
                # A watched entity was deleted: surface a Repairs issue now
                if any(
                    r[CONF_ENTITY_ID] == event.data.get("entity_id")
                    for r in self.rules
                ):
                    self._check_missing_entities()
                return
            if event.data.get("action") != "update":
                return
            old = event.data.get("old_entity_id")
            new = event.data.get("entity_id")
            if not old or not new or old == new:
                return
            if not any(r[CONF_ENTITY_ID] == old for r in self.rules):
                return
            rules = [
                {**r, CONF_ENTITY_ID: new} if r[CONF_ENTITY_ID] == old else r
                for r in self.rules
            ]
            _LOGGER.info("Watched entity renamed %s -> %s; updating rules", old, new)
            self.hass.config_entries.async_update_entry(
                self.entry, options={**self.entry.options, CONF_MAPPINGS: rules}
            )  # triggers reload via update listener

        self._unsub_registry = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, _registry_updated
        )

    # ---------- lifecycle ----------

    async def async_start(self) -> None:
        await self.fetch_info()
        data = await self._store.async_load() or {}
        self._painted = {int(x) for x in data.get("leds", [])}
        # LEDs painted by a previous incarnation (deleted rules, restarts)
        # that no current rule covers: turn them off now.
        stale = self._painted - self.all_leds
        if stale:
            await self._send(
                [v for led in sorted(stale) for v in (led, OFF_COLOR)]
            )
            await self._update_painted(self._painted - stale)
        self._check_missing_entities()
        self._setup_rename_listener()
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

                    async def _transition() -> None:
                        await self._apply_quiet_transition(quiet)
                        await self.push()

                    self.hass.async_create_task(_transition())

            self._was_quiet = self._in_quiet()
            self._unsub_minute = async_track_time_interval(
                self.hass, _minute, timedelta(seconds=60)
            )
            # If HA (re)starts inside a strip_off quiet window, apply it now
            if self._was_quiet and self.quiet_mode == "strip_off":
                await self._set_strip_power(False)

        self.refresh_all()
        await self.push()

    async def async_stop(self) -> None:
        for unsub in (
            self._unsub_state,
            self._unsub_blink,
            self._unsub_minute,
            self._unsub_registry,
        ):
            if unsub:
                unsub()
        self._unsub_state = self._unsub_blink = None
        self._unsub_minute = self._unsub_registry = None
        for idx in list(self._pending):
            self._cancel_pending(idx)


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
                vol.Optional(CONF_FOR_MINUTES, default=0): vol.Coerce(float),
                vol.Optional(CONF_FILL_MIN, default=0): vol.Coerce(float),
                vol.Optional(CONF_FILL_MAX, default=100): vol.Coerce(float),
                vol.Optional(CONF_COLOR2, default=""): str,
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
        vol.Optional(CONF_SEGMENT): vol.Coerce(int),
    }
)
@websocket_api.async_response
async def ws_save_settings(hass, connection, msg) -> None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return
    options = {
        **entry.options,
        CONF_QUIET_START: msg[CONF_QUIET_START],
        CONF_QUIET_END: msg[CONF_QUIET_END],
        CONF_QUIET_MODE: msg[CONF_QUIET_MODE],
    }
    if CONF_SEGMENT in msg:
        options[CONF_SEGMENT] = msg[CONF_SEGMENT]
    hass.config_entries.async_update_entry(entry, options=options)
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
