"""Pause switch for WLED Task Map."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PauseAlertsSwitch(manager, entry)])


class PauseAlertsSwitch(SwitchEntity):
    """Silence all LED alerts (week board and pet keep running)."""

    _attr_icon = "mdi:bell-off-outline"
    _attr_should_poll = False

    def __init__(self, manager, entry: ConfigEntry) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_pause_alerts"
        self._attr_name = f"{entry.title} Pause Alerts"

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
        return self._manager.paused

    async def async_turn_on(self, **kwargs) -> None:
        await self._manager.set_paused(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self._manager.set_paused(False)
        self.async_write_ha_state()
