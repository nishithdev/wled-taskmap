"""WLED Task Map - light up individual LEDs when tasks/entities need attention."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ATTR_COLOR,
    ATTR_LED,
    CONF_ALERT_STATES,
    CONF_COLOR,
    CONF_ENTITY_ID,
    CONF_HOST,
    CONF_LED,
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


class TaskMapManager:
    """Watches entities and drives individual WLED LEDs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.host: str = entry.data[CONF_HOST]
        self.segment: int = entry.options.get(
            CONF_SEGMENT, entry.data.get(CONF_SEGMENT, DEFAULT_SEGMENT)
        )
        self.mappings: list[dict] = entry.options.get(CONF_MAPPINGS, [])
        # entity_id -> mapping dict
        self._by_entity = {m[CONF_ENTITY_ID]: m for m in self.mappings}
        # led index -> color, for service-driven (manual / external app) alerts
        self.manual_alerts: dict[int, str] = {}
        # entity_id -> bool currently alerting
        self.entity_alerts: dict[str, bool] = {}
        self._unsub = None

    # ---------- alert evaluation ----------

    def _is_alert(self, mapping: dict, state) -> bool:
        if state is None:
            return False
        entity_id = mapping[CONF_ENTITY_ID]
        value = state.state
        # To-do lists report the number of pending items as their state.
        if entity_id.startswith("todo."):
            try:
                return int(float(value)) > 0
            except (ValueError, TypeError):
                return value in ("unavailable", "unknown")
        alert_states = [
            s.strip().lower()
            for s in mapping.get(CONF_ALERT_STATES, DEFAULT_ALERT_STATES).split(",")
            if s.strip()
        ]
        return value.lower() in alert_states

    def refresh_entity(self, entity_id: str) -> None:
        mapping = self._by_entity.get(entity_id)
        if mapping is None:
            return
        state = self.hass.states.get(entity_id)
        self.entity_alerts[entity_id] = self._is_alert(mapping, state)

    def refresh_all_entities(self) -> None:
        for entity_id in self._by_entity:
            self.refresh_entity(entity_id)

    @property
    def active_alerts(self) -> dict[int, str]:
        """Return led -> color for everything currently alerting."""
        leds: dict[int, str] = {}
        for entity_id, alerting in self.entity_alerts.items():
            mapping = self._by_entity.get(entity_id)
            if mapping is None:
                continue
            if alerting:
                leds[int(mapping[CONF_LED])] = mapping.get(CONF_COLOR, DEFAULT_COLOR)
        leds.update(self.manual_alerts)
        return leds

    @property
    def all_leds(self) -> set[int]:
        leds = {int(m[CONF_LED]) for m in self.mappings}
        leds.update(self.manual_alerts)
        return leds

    # ---------- WLED control ----------

    async def push(self) -> None:
        """Push current alert state to the WLED strip (individual LED control)."""
        active = self.active_alerts
        i_array: list = []
        for led in sorted(self.all_leds):
            i_array.extend([led, active.get(led, OFF_COLOR)])
        if not i_array:
            return
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
        entity_ids = list(self._by_entity)
        if entity_ids:

            @callback
            def _state_changed(event: Event) -> None:
                self.refresh_entity(event.data["entity_id"])
                self.hass.async_create_task(self.push())

            self._unsub = async_track_state_change_event(
                self.hass, entity_ids, _state_changed
            )
        self.refresh_all_entities()
        await self.push()

    async def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager = TaskMapManager(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    await manager.async_start()

    async def _get_manager(call: ServiceCall) -> TaskMapManager:
        # Single-entry oriented; if multiple WLED hosts are configured the
        # first loaded entry handles service calls unless extended later.
        return manager

    async def handle_set_alert(call: ServiceCall) -> None:
        mgr = await _get_manager(call)
        mgr.manual_alerts[int(call.data[ATTR_LED])] = call.data[ATTR_COLOR].lstrip("#")
        await mgr.push()

    async def handle_clear_alert(call: ServiceCall) -> None:
        mgr = await _get_manager(call)
        mgr.manual_alerts.pop(int(call.data[ATTR_LED]), None)
        await mgr.push()

    async def handle_clear_all(call: ServiceCall) -> None:
        mgr = await _get_manager(call)
        mgr.manual_alerts.clear()
        await mgr.push()

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
