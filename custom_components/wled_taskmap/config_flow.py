"""Config flow for WLED Task Map - just point at a WLED device.

All alert rules are managed visually in the WLED Task Map Lovelace card.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_HOST, CONF_SEGMENT, DEFAULT_SEGMENT, DOMAIN


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
                    data={CONF_HOST: host, CONF_SEGMENT: DEFAULT_SEGMENT},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )
