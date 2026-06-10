"""Active alerts sensor for WLED Task Map."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTITY_ID, CONF_LED, DOMAIN, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ActiveAlertsSensor(manager, entry)])


class ActiveAlertsSensor(SensorEntity):
    """Counts items currently lighting an LED."""

    _attr_icon = "mdi:led-strip-variant"
    _attr_should_poll = False
    _attr_native_unit_of_measurement = "alerts"

    def __init__(self, manager, entry: ConfigEntry) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_active_alerts"
        self._attr_name = f"{entry.title} Active Alerts"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATE}_{self._manager.entry.entry_id}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return len(self._manager.active_alerts)

    @property
    def extra_state_attributes(self) -> dict:
        alerting_entities = [
            e for e, alerting in self._manager.entity_alerts.items() if alerting
        ]
        return {
            "alerting_entities": alerting_entities,
            "manual_leds": sorted(self._manager.manual_alerts),
            "watched": [
                {"entity": m[CONF_ENTITY_ID], "led": m[CONF_LED]}
                for m in self._manager.mappings
            ],
        }
