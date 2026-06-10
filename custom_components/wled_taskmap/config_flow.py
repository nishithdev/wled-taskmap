"""Config & options flow for WLED Task Map."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ALERT_STATES,
    CONF_COLOR,
    CONF_ENTITY_ID,
    CONF_HOST,
    CONF_LED,
    CONF_LED_COUNT,
    CONF_MAPPINGS,
    CONF_SEGMENT,
    DEFAULT_ALERT_STATES,
    DEFAULT_COLOR,
    DEFAULT_SEGMENT,
    DOMAIN,
)

COMMON_ALERT_STATES = [
    "unavailable",
    "unknown",
    "error",
    "problem",
    "on",
    "off",
    "open",
    "disconnected",
    "failed",
    "idle",
]


def _hex_to_rgb(value: str) -> list[int]:
    value = value.lstrip("#")
    try:
        return [int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)]
    except (ValueError, IndexError):
        return [255, 0, 0]


def _rgb_to_hex(rgb: list[int] | tuple[int, ...]) -> str:
    return "".join(f"{int(c):02X}" for c in rgb[:3])


def _mapping_label(m: dict) -> str:
    start = int(m[CONF_LED])
    count = max(1, int(m.get(CONF_LED_COUNT, 1)))
    leds = f"LED {start}" if count == 1 else f"LEDs {start}-{start + count - 1}"
    return f"{leds}: {m[CONF_ENTITY_ID]}"


def _mapping_schema(mapping: dict | None = None) -> vol.Schema:
    m = mapping or {}
    states_default = [
        s.strip()
        for s in m.get(CONF_ALERT_STATES, DEFAULT_ALERT_STATES).split(",")
        if s.strip()
    ]
    return vol.Schema(
        {
            vol.Required(
                CONF_ENTITY_ID, default=m.get(CONF_ENTITY_ID, vol.UNDEFINED)
            ): selector.EntitySelector(),
            vol.Required(CONF_LED, default=m.get(CONF_LED, 0)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=1024, mode="box")
            ),
            vol.Required(
                CONF_LED_COUNT, default=m.get(CONF_LED_COUNT, 1)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=1024, mode="box")
            ),
            vol.Required(
                CONF_COLOR, default=_hex_to_rgb(m.get(CONF_COLOR, DEFAULT_COLOR))
            ): selector.ColorRGBSelector(),
            vol.Required(
                CONF_ALERT_STATES, default=states_default
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=COMMON_ALERT_STATES,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _mapping_from_input(user_input: dict[str, Any]) -> dict:
    return {
        CONF_ENTITY_ID: user_input[CONF_ENTITY_ID],
        CONF_LED: int(user_input[CONF_LED]),
        CONF_LED_COUNT: int(user_input[CONF_LED_COUNT]),
        CONF_COLOR: _rgb_to_hex(user_input[CONF_COLOR]),
        CONF_ALERT_STATES: ",".join(user_input[CONF_ALERT_STATES]),
    }


class WledTaskMapConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup: point at a WLED device."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            session = async_get_clientsession(self.hass)
            try:
                async with session.get(f"http://{host}/json/info", timeout=10) as resp:
                    if resp.status != 200:
                        errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            if not errors:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"WLED Task Map ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_SEGMENT: user_input.get(CONF_SEGMENT, DEFAULT_SEGMENT),
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_SEGMENT, default=DEFAULT_SEGMENT): int,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WledTaskMapOptionsFlow:
        return WledTaskMapOptionsFlow()


class WledTaskMapOptionsFlow(OptionsFlow):
    """Manage entity -> LED mappings."""

    _edit_index: int | None = None

    @property
    def _mappings(self) -> list[dict]:
        return list(self.config_entry.options.get(CONF_MAPPINGS, []))

    def _save(self, mappings: list[dict]) -> ConfigFlowResult:
        return self.async_create_entry(
            title="", data={**self.config_entry.options, CONF_MAPPINGS: mappings}
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        menu = ["add_mapping"]
        if self._mappings:
            menu += ["edit_select", "remove_mapping"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_add_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            mappings = self._mappings
            mappings.append(_mapping_from_input(user_input))
            return self._save(mappings)
        return self.async_show_form(
            step_id="add_mapping", data_schema=_mapping_schema()
        )

    async def async_step_edit_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        labels = [_mapping_label(m) for m in self._mappings]
        if user_input is not None:
            self._edit_index = labels.index(user_input["mapping"])
            return await self.async_step_edit_mapping()
        return self.async_show_form(
            step_id="edit_select",
            data_schema=vol.Schema(
                {
                    vol.Required("mapping"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=labels)
                    )
                }
            ),
        )

    async def async_step_edit_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        mappings = self._mappings
        if user_input is not None and self._edit_index is not None:
            mappings[self._edit_index] = _mapping_from_input(user_input)
            return self._save(mappings)
        return self.async_show_form(
            step_id="edit_mapping",
            data_schema=_mapping_schema(mappings[self._edit_index]),
        )

    async def async_step_remove_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        mappings = self._mappings
        if user_input is not None:
            keep = [
                m for m in mappings if _mapping_label(m) not in user_input["remove"]
            ]
            return self._save(keep)
        labels = [_mapping_label(m) for m in mappings]
        return self.async_show_form(
            step_id="remove_mapping",
            data_schema=vol.Schema(
                {
                    vol.Required("remove", default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=labels, multiple=True)
                    )
                }
            ),
        )
