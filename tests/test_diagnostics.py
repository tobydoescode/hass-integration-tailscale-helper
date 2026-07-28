"""Tests for the Tailscale Helper diagnostics dump."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import CoreState, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.tailscale_helper.const import CONF_THRESHOLD
from custom_components.tailscale_helper.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_reports_the_default_threshold(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
) -> None:
    """With nothing configured the dump states the shipped default."""
    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await async_get_config_entry_diagnostics(hass, helper_config_entry) == {
        "threshold_seconds": 300,
        "devices": [],
    }


async def test_reports_the_configured_threshold(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
) -> None:
    """A threshold set in the options flow is what the dump reports."""
    hass.config_entries.async_update_entry(helper_config_entry, options={CONF_THRESHOLD: 600})

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, helper_config_entry)

    assert result["threshold_seconds"] == 600


async def test_healthy_device_shows_the_whole_derivation(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device: Callable[..., object],
    set_last_seen: Callable[[str, str], None],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Every step from source state to our state is visible and checkable.

    The expected numbers are the worked example from the ticket, not a
    recomputation: 12:04:53.2 minus 12:04:11 is 42.2s, which is under the 300s
    threshold, so we are on.
    """
    freezer.move_to("2026-07-28T12:04:53.200000+00:00")
    add_tailscale_device("home-router", "nODdc3")
    set_last_seen("sensor.home_router_last_seen", "2026-07-28T12:04:11+00:00")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, helper_config_entry)

    assert result["devices"] == [
        {
            "device_id": REDACTED,
            "source": "sensor.home_router_last_seen",
            "source_state": "2026-07-28T12:04:11+00:00",
            "age_seconds": 42.2,
            "is_on": True,
        }
    ]


@pytest.mark.parametrize("source_state", ["unknown", "", "not-a-timestamp"])
async def test_unparseable_source_has_no_age(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device: Callable[..., object],
    set_last_seen: Callable[[str, str], None],
    source_state: str,
) -> None:
    """A state that is not a timestamp has a null age, and we report off."""
    add_tailscale_device("old-phone", "pQ81xa")
    set_last_seen("sensor.old_phone_last_seen", source_state)

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, helper_config_entry)

    assert result["devices"] == [
        {
            "device_id": REDACTED,
            "source": "sensor.old_phone_last_seen",
            "source_state": source_state,
            "age_seconds": None,
            "is_on": False,
        }
    ]


async def test_unavailable_device_is_still_reported(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device: Callable[..., object],
    set_last_seen: Callable[[str, str], None],
) -> None:
    """An unavailable source is the interesting case, so it must not be dropped.

    Our own sensor is unavailable too, which is neither on nor off, so ``is_on``
    is null rather than a misleading ``false``.
    """
    add_tailscale_device("dead-laptop", "zZ99aa")
    set_last_seen("sensor.dead_laptop_last_seen", "unavailable")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, helper_config_entry)

    assert result["devices"] == [
        {
            "device_id": REDACTED,
            "source": "sensor.dead_laptop_last_seen",
            "source_state": "unavailable",
            "age_seconds": None,
            "is_on": None,
        }
    ]


async def test_source_with_no_state_at_all(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device: Callable[..., object],
) -> None:
    """A registered source that has never reported is reported as null."""
    add_tailscale_device("ghost", "gH05t0")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, helper_config_entry)

    assert result["devices"] == [
        {
            "device_id": REDACTED,
            "source": "sensor.ghost_last_seen",
            "source_state": None,
            "age_seconds": None,
            "is_on": None,
        }
    ]


async def test_device_we_have_no_sensor_for_yet(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device: Callable[..., object],
    set_last_seen: Callable[[str, str], None],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A discovered device with no sensor of ours is listed, with a null state.

    Our scan is deferred until Home Assistant has started, so a dump taken
    during startup sees the source but not yet our sensor -- which is precisely
    the "why has this device got no sensor" report we want to be able to read.
    """
    hass.set_state(CoreState.not_running)
    freezer.move_to("2026-07-28T12:04:53.200000+00:00")
    add_tailscale_device("home-router", "nODdc3")
    set_last_seen("sensor.home_router_last_seen", "2026-07-28T12:04:11+00:00")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.home_router_connection_state") is None

    result = await async_get_config_entry_diagnostics(hass, helper_config_entry)

    assert result["devices"] == [
        {
            "device_id": REDACTED,
            "source": "sensor.home_router_last_seen",
            "source_state": "2026-07-28T12:04:11+00:00",
            "age_seconds": 42.2,
            "is_on": None,
        }
    ]


async def test_is_on_is_our_published_state_not_a_recomputation(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device: Callable[..., object],
    set_last_seen: Callable[[str, str], None],
    freezer: FrozenDateTimeFactory,
) -> None:
    """``is_on`` reports what our sensor actually says, however stale that is.

    Between polls the age can cross the threshold while our published state has
    not caught up. Recomputing here would hide exactly that, which is the one
    disagreement a reader most needs to see.
    """
    freezer.move_to("2026-07-28T12:00:00+00:00")
    add_tailscale_device("home-router", "nODdc3")
    set_last_seen("sensor.home_router_last_seen", "2026-07-28T12:00:00+00:00")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    # Time moves, but the poll timer is deliberately not fired, so the sensor
    # still holds the state it computed at setup.
    freezer.tick(timedelta(seconds=400))

    device = (await async_get_config_entry_diagnostics(hass, helper_config_entry))["devices"][0]

    assert device["age_seconds"] == 400.0
    assert device["is_on"] is True
    assert hass.states.get("binary_sensor.home_router_connection_state").state == "on"


async def test_whole_dump_for_a_mixed_tailnet(
    hass: HomeAssistant,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device: Callable[..., object],
    set_last_seen: Callable[[str, str], None],
    freezer: FrozenDateTimeFactory,
) -> None:
    """The dump a user would actually attach to an issue.

    Healthy, unknown and unavailable devices side by side, ordered by device id
    so two dumps of the same tailnet are comparable.
    """
    freezer.move_to("2026-07-28T12:04:53.200000+00:00")
    # Registered out of order, so the expected order below is ours, not the
    # entity registry's.
    add_tailscale_device("dead-laptop", "zZ99aa")
    add_tailscale_device("home-router", "nODdc3")
    add_tailscale_device("old-phone", "pQ81xa")
    set_last_seen("sensor.home_router_last_seen", "2026-07-28T12:04:11+00:00")
    set_last_seen("sensor.old_phone_last_seen", "unknown")
    set_last_seen("sensor.dead_laptop_last_seen", "unavailable")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await async_get_config_entry_diagnostics(hass, helper_config_entry) == {
        "threshold_seconds": 300,
        "devices": [
            {
                "device_id": REDACTED,
                "source": "sensor.home_router_last_seen",
                "source_state": "2026-07-28T12:04:11+00:00",
                "age_seconds": 42.2,
                "is_on": True,
            },
            {
                "device_id": REDACTED,
                "source": "sensor.old_phone_last_seen",
                "source_state": "unknown",
                "age_seconds": None,
                "is_on": False,
            },
            {
                "device_id": REDACTED,
                "source": "sensor.dead_laptop_last_seen",
                "source_state": "unavailable",
                "age_seconds": None,
                "is_on": None,
            },
        ],
    }


async def test_home_assistant_serves_the_dump(
    hass: HomeAssistant,
    hass_client: Callable[..., Any],
    helper_config_entry: MockConfigEntry,
    add_tailscale_device: Callable[..., object],
    set_last_seen: Callable[[str, str], None],
) -> None:
    """The dump is reachable over HTTP and every value survives JSON.

    Calling the function directly would still pass if the module or the function
    were misnamed, since Home Assistant discovers both by convention. This is
    also the only test that proves the payload is serialisable.

    Deliberately not frozen: freezegun invalidates the access token that
    ``hass_client`` mints, so the endpoint answers 401. The arithmetic is
    asserted exactly in the tests above; this one only pins the wiring.
    """
    add_tailscale_device("home-router", "nODdc3")
    set_last_seen("sensor.home_router_last_seen", "2020-01-01T00:00:00+00:00")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    data = await get_diagnostics_for_config_entry(hass, hass_client, helper_config_entry)

    assert data["threshold_seconds"] == 300
    assert len(data["devices"]) == 1
    device = data["devices"][0]
    assert device.keys() == {"device_id", "source", "source_state", "age_seconds", "is_on"}
    assert device["device_id"] == REDACTED
    assert device["source"] == "sensor.home_router_last_seen"
    assert device["source_state"] == "2020-01-01T00:00:00+00:00"
    # Years old, so far past any threshold.
    assert device["age_seconds"] > 0
    assert device["is_on"] is False
