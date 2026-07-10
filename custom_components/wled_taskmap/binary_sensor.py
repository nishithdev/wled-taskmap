"""Per-rule binary sensors for WLED Task Map."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_EFFECT,
    CONF_ENTITY_ID,
    CONF_LEDS,
    CONF_NAME_,
    DOMAIN,
    SIGNAL_UPDATE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for idx, rule in enumerate(manager.rules):
        if rule[CONF_EFFECT] == "fill" or not rule[CONF_ENTITY_ID]:
            continue  # fill bars and static lights aren't on/off alerts
        entities.append(RuleBinarySensor(manager, entry, idx))
    async_add_entities(entities)


class RuleBinarySensor(BinarySensorEntity):
    """On while its LED alert rule is firing."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_should_poll = False

    def __init__(self, manager, entry: ConfigEntry, idx: int) -> None:
        self._manager = manager
        self._idx = idx
        rule = manager.rules[idx]
        label = rule.get(CONF_NAME_) or rule[CONF_ENTITY_ID]
        self._attr_unique_id = f"{entry.entry_id}_rule_{idx}"
        self._attr_name = f"{entry.title} Alert: {label}"

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
    def is_on(self) -> bool:
        return bool(self._manager.rule_alerts.get(self._idx))

    @property
    def extra_state_attributes(self) -> dict:
        if self._idx >= len(self._manager.rules):
            return {}
        rule = self._manager.rules[self._idx]
        return {
            "watched_entity": rule[CONF_ENTITY_ID],
            "leds": rule[CONF_LEDS],
            "acknowledged": self._idx in self._manager.acked,
        }
