"""Config flow tests for Tailscale Helper."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tailscale_helper.const import DOMAIN


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """A single submit with no input creates the config entry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Tailscale Helper"


async def test_single_instance_only(hass: HomeAssistant) -> None:
    """A second entry is refused -- one entry already covers every device."""
    MockConfigEntry(domain=DOMAIN, title="Tailscale Helper").add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
