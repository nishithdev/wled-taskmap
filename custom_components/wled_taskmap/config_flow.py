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
    CONF_MAPPINGS,
    CONF_SEGMENT,
    DEFAULT_ALERT_STATES,
    DEFAULT_COLOR,
    DEFAULT_SEGMENT,
    DOMAIN,
)


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

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["add_mapping", "remove_mapping"]
        )

    async def async_step_add_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            mappings = list(self.config_entry.options.get(CONF_MAPPINGS, []))
            mappings.append(
                {
                    CONF_ENTITY_ID: user_input[CONF_ENTITY_ID],
                    CONF_LED: int(user_input[CONF_LED]),
                    CONF_COLOR: user_input[CONF_COLOR].lstrip("#"),
                    CONF_ALERT_STATES: user_input[CONF_ALERT_STATES],
                }
            )
            return self.async_create_entry(
                title="",
                data={**self.config_entry.options, CONF_MAPPINGS: mappings},
            )
        return self.async_show_form(
            step_id="add_mapping",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENTITY_ID): selector.EntitySelector(),
                    vol.Required(CONF_LED, default=0): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, max=1024, mode="box")
                    ),
                    vol.Required(CONF_COLOR, default=DEFAULT_COLOR): str,
                    vol.Required(
                        CONF_ALERT_STATES, default=DEFAULT_ALERT_STATES
                    ): str,
                }
            ),
        )

    async def async_step_remove_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        mappings = list(self.config_entry.options.get(CONF_MAPPINGS, []))
        if user_input is not None:
            keep = [
                m
                for m in mappings
                if f"{m[CONF_ENTITY_ID]} → LED {m[CONF_LED]}"
                not in user_input["remove"]
            ]
            return self.async_create_entry(
                title="",
                data={**self.config_entry.options, CONF_MAPPINGS: keep},
            )
        labels = [f"{m[CONF_ENTITY_ID]} → LED {m[CONF_LED]}" for m in mappings]
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
