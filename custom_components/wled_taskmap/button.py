"""Resync button for WLED Task Map."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ResyncButton(manager, entry)])


class ResyncButton(ButtonEntity):
    """Repaint every LED on the strip (alerts, week board, pet)."""

    _attr_icon = "mdi:sync"

    def __init__(self, manager, entry: ConfigEntry) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_resync"
        self._attr_name = f"{entry.title} Resync"

    async def async_press(self) -> None:
        await self._manager.resync()
