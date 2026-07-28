"""Fixtures for Tailscale Helper tests.

The Tailscale integration is never actually set up: a bare ``MockConfigEntry``
with its domain is enough to own devices, so no API key or network is needed.
This mirrors ``tests/components/derivative/conftest.py`` in Home Assistant core,
which fakes a source integration the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_entity_registry_updated_event
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.tailscale_helper.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:  # noqa: ARG001
    """Enable custom integrations for all tests."""


@pytest.fixture
def tailscale_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry standing in for the Tailscale integration."""
    entry = MockConfigEntry(domain="tailscale", title="Tailscale")
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def add_tailscale_device(
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    tailscale_config_entry: ConfigEntry,
) -> Callable[..., tuple[dr.DeviceEntry, er.RegistryEntry]]:
    """Return a factory creating a Tailscale device plus its last_seen sensor."""

    def _add(
        name: str = "home-router",
        device_id: str = "device-abc123",
        **entity_kwargs: object,
    ) -> tuple[dr.DeviceEntry, er.RegistryEntry]:
        device = device_registry.async_get_or_create(
            config_entry_id=tailscale_config_entry.entry_id,
            identifiers={("tailscale", device_id)},
            manufacturer="Tailscale Inc.",
            name=name,
            entry_type=dr.DeviceEntryType.SERVICE,
        )
        entity = entity_registry.async_get_or_create(
            "sensor",
            "tailscale",
            f"{device_id}_last_seen",
            config_entry=tailscale_config_entry,
            device_id=device.id,
            original_name="Last seen",
            original_device_class="timestamp",
            suggested_object_id=f"{name}_last_seen",
            **entity_kwargs,
        )
        return device, entity

    return _add


@pytest.fixture
def set_last_seen(hass: HomeAssistant) -> Callable[[str, datetime | str], None]:
    """Set a source last_seen entity's state."""

    def _set(entity_id: str, value: datetime | str) -> None:
        state = value.isoformat() if isinstance(value, datetime) else value
        hass.states.async_set(entity_id, state, {"device_class": "timestamp"})

    return _set


@pytest.fixture
def helper_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Our own config entry, added but not yet set up."""
    entry = MockConfigEntry(domain=DOMAIN, title="Tailscale Helper")
    entry.add_to_hass(hass)
    return entry


def track_entity_registry_actions(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Record the registry actions an entity goes through, in order.

    Lifted from ``tests/components/derivative/test_init.py`` in Home Assistant
    core. Useful where the interesting thing is what did *not* happen: a reload
    that churns the registry shows up here as ``["remove", "create"]``, which no
    end-state assertion would notice.
    """
    events: list[str] = []

    @callback
    def add_event(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        events.append(event.data["action"])

    async_track_entity_registry_updated_event(hass, entity_id, add_event)
    return events


async def advance(hass: HomeAssistant, freezer, seconds: float) -> None:
    """Move frozen time forward and let scheduled work run.

    Both halves matter: the freezer controls what ``now()`` returns inside the
    entity, while ``async_fire_time_changed`` is what makes Home Assistant
    actually run the polling timer.
    """
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
