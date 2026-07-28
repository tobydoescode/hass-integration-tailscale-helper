"""Options flow tests for Tailscale Helper."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.tailscale_helper as tailscale_helper
from custom_components.tailscale_helper.const import (
    CONF_THRESHOLD,
    DEFAULT_THRESHOLD,
    DOMAIN,
)


async def test_threshold_defaults_when_unset(hass: HomeAssistant) -> None:
    """A fresh entry carries no options and falls back to the default."""
    entry = MockConfigEntry(domain=DOMAIN, title="Tailscale Helper")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.options.get(CONF_THRESHOLD, DEFAULT_THRESHOLD) == 300


async def test_options_flow_sets_threshold_and_reloads(hass: HomeAssistant) -> None:
    """Submitting the options form persists the threshold and reloads the entry."""
    entry = MockConfigEntry(domain=DOMAIN, title="Tailscale Helper")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(
        tailscale_helper,
        "async_setup_entry",
        wraps=tailscale_helper.async_setup_entry,
    ) as mock_setup:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_THRESHOLD: 600}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

    assert entry.options[CONF_THRESHOLD] == 600
    # NumberSelector hands back a float. Normalise at the boundary so options
    # persist as 600 rather than 600.0, and diagnostics read cleanly.
    assert isinstance(entry.options[CONF_THRESHOLD], int)
    # Changing the threshold must re-run setup, or existing entities keep the
    # old value.
    assert mock_setup.call_count == 1
