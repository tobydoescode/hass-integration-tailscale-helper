"""State tests for the Connection state binary sensor."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tailscale_helper.const import CONF_THRESHOLD

from .conftest import advance

ENTITY_ID = "binary_sensor.home_router_connection_state"
SOURCE_ID = "sensor.home_router_last_seen"


@pytest.mark.parametrize(
    ("age_seconds", "expected"),
    [
        (0, STATE_ON),
        (42, STATE_ON),
        (299, STATE_ON),
        # The template used a strict `<`, so the boundary itself is off.
        (300, STATE_OFF),
        (400, STATE_OFF),
    ],
)
async def test_state_from_timestamp_age(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
    set_last_seen,
    age_seconds: int,
    expected: str,
) -> None:
    """A parseable timestamp is on or off depending on how old it is."""
    add_tailscale_device("home-router", "abc")
    set_last_seen(SOURCE_ID, dt_util.utcnow() - timedelta(seconds=age_seconds))

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == expected


@pytest.mark.parametrize(
    ("source_state", "expected"),
    [
        # "we do not know" is not the same as "it is offline" -- but a device
        # Tailscale has genuinely never seen is offline, not unknowable.
        ("unknown", STATE_OFF),
        ("", STATE_OFF),
        ("not-a-timestamp", STATE_OFF),
        # A Tailscale API outage must not read as "everything disconnected".
        ("unavailable", STATE_UNAVAILABLE),
    ],
)
async def test_state_from_non_timestamp_source(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
    set_last_seen,
    source_state: str,
    expected: str,
) -> None:
    """Anything that is not a timestamp is off, except unavailable."""
    add_tailscale_device("home-router", "abc")
    set_last_seen(SOURCE_ID, source_state)

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == expected


async def test_missing_source_entity_is_unavailable(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """A source with no state at all is unknowable, not offline."""
    add_tailscale_device("home-router", "abc")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


async def test_goes_offline_as_time_passes_with_no_update(
    hass: HomeAssistant,
    freezer,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
    set_last_seen,
) -> None:
    """The whole point: a device that stops reporting eventually reads off.

    Nothing updates the source here. Only the clock moves, so the flip has to
    come from polling rather than from any event.
    """
    add_tailscale_device("home-router", "abc")
    set_last_seen(SOURCE_ID, dt_util.utcnow())

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    await advance(hass, freezer, 310)

    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_comes_back_online_without_waiting_for_a_poll(
    hass: HomeAssistant,
    freezer,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
    set_last_seen,
) -> None:
    """A device reporting in is reflected at once, not at the next poll."""
    add_tailscale_device("home-router", "abc")
    set_last_seen(SOURCE_ID, dt_util.utcnow() - timedelta(seconds=400))

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_OFF

    # No time advanced and no poll fired -- only the source reporting.
    set_last_seen(SOURCE_ID, dt_util.utcnow())
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_ON


async def test_threshold_option_is_honoured(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
    set_last_seen,
) -> None:
    """A non-default threshold moves the boundary, proving it is wired through."""
    hass.config_entries.async_update_entry(helper_config_entry, options={CONF_THRESHOLD: 600})
    add_tailscale_device("home-router", "abc")
    # Stale against the 300s default, fresh against the configured 600s.
    set_last_seen(SOURCE_ID, dt_util.utcnow() - timedelta(seconds=400))

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_ON
