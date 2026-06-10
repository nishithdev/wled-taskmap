"""Active alerts sensor for WLED Task Map."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTITY_ID, CONF_LEDS, DOMAIN, SIGNAL_UPDATE


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
        return {
            "pet_mood": self._manager.pet_mood if self._manager.pet_enabled else None,
            "alerting_entities": self._manager.alerting_entities,
            "manual_leds": sorted(self._manager.manual_alerts),
            "watched": [
                {"entity": r[CONF_ENTITY_ID], "leds": r[CONF_LEDS]}
                for r in self._manager.rules
            ],
        }
