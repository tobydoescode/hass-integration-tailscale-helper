"""Config flow for the Tailscale Helper integration."""

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
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import CONF_THRESHOLD, DEFAULT_THRESHOLD, DOMAIN, NAME


class TailscaleHelperConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tailscale Helper."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step.

        There is nothing to configure at setup time -- every Tailscale device is
        discovered automatically -- so this is a bare confirmation.
        """
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(step_id="user")

        return self.async_create_entry(title=NAME, data={})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return TailscaleHelperOptionsFlow()


class TailscaleHelperOptionsFlow(OptionsFlow):
    """Handle the Tailscale Helper options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the threshold."""
        if user_input is not None:
            # NumberSelector yields a float; store a whole number of seconds.
            return self.async_create_entry(data={CONF_THRESHOLD: int(user_input[CONF_THRESHOLD])})

        current = self.config_entry.options.get(CONF_THRESHOLD, DEFAULT_THRESHOLD)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_THRESHOLD, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=30,
                            max=86400,
                            step=1,
                            unit_of_measurement="seconds",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
