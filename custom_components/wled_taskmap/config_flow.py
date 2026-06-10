"""Config flow for WLED Task Map.

Devices are auto-discovered via zeroconf; manual setup just needs the IP.
All alert rules are managed visually in the WLED Task Map Lovelace card.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:  # HA 2025.x+
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # older cores
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

from .const import CONF_HOST, CONF_SEGMENT, DEFAULT_SEGMENT, DOMAIN


async def _probe(hass, host: str) -> dict | None:
    """Check a WLED device is reachable; return its /json/info or None."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(f"http://{host}/json/info", timeout=10) as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except Exception:  # noqa: BLE001
        return None


class WledTaskMapConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up against a WLED device, discovered or manual."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._name: str | None = None

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a WLED device found on the network."""
        host = discovery_info.host
        mac = (discovery_info.properties or {}).get("mac")
        await self.async_set_unique_id(mac or host)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._host = host
        self._name = discovery_info.name.split(".")[0]
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered device."""
        if user_input is not None:
            if await _probe(self.hass, self._host) is None:
                return self.async_abort(reason="cannot_connect")
            return self.async_create_entry(
                title=f"WLED Task Map ({self._name or self._host})",
                data={CONF_HOST: self._host, CONF_SEGMENT: DEFAULT_SEGMENT},
            )
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._name or "",
                "host": self._host or "",
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            info = await _probe(self.hass, host)
            if info is None:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.get("mac") or host)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=f"WLED Task Map ({info.get('name') or host})",
                    data={CONF_HOST: host, CONF_SEGMENT: DEFAULT_SEGMENT},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )
