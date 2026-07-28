"""Setup and teardown tests for Tailscale Helper."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tailscale_helper.const import DOMAIN

from .conftest import track_entity_registry_actions

ENTITY_ID = "binary_sensor.home_router_connection_state"
SOURCE_ID = "sensor.home_router_last_seen"


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    """The entry loads and unloads cleanly."""
    entry = MockConfigEntry(domain=DOMAIN, title="Tailscale Helper")
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_without_tailscale(hass: HomeAssistant) -> None:
    """The entry still loads when the Tailscale integration is absent.

    after_dependencies orders us after Tailscale when it is present, but must
    not require it -- an install with no Tailscale should sit idle, not fail.
    """
    entry = MockConfigEntry(domain=DOMAIN, title="Tailscale Helper")
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_unload_detaches_the_registry_listener(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """An unloaded entry must stop reacting to the tailnet.

    The registry subscription outlives the platform unless it is registered with
    ``async_on_unload``, and a stale one would go on adding entities through a
    platform that is no longer there.
    """
    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    add_tailscale_device("phone", "ghi")
    await hass.async_block_till_done()

    assert entity_registry.async_get("binary_sensor.phone_connection_state") is None
    assert hass.states.get("binary_sensor.phone_connection_state") is None


async def test_entities_survive_a_reload_unchanged(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
    set_last_seen,
) -> None:
    """Reloading -- which is what a restart looks like -- must not churn entities.

    Identity has to be stable across a reload: same entity_id, same unique_id,
    same device, and no second copy suffixed ``_2``. Anything that made the
    unique_id vary per run would surface here as a duplicate.
    """
    router_device, _ = add_tailscale_device("home-router", "abc")
    laptop_device, _ = add_tailscale_device("laptop", "def")
    set_last_seen(SOURCE_ID, dt_util.utcnow())

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    before = {
        entry.entity_id: (entry.unique_id, entry.device_id)
        for entry in entity_registry.entities.values()
        if entry.platform == DOMAIN
    }
    assert before == {
        ENTITY_ID: ("abc_connection_state", router_device.id),
        "binary_sensor.laptop_connection_state": ("def_connection_state", laptop_device.id),
    }
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    # A reload that tore the registry entry down and rebuilt it would still end
    # up in the same place, so watch the journey and not only the destination.
    actions = track_entity_registry_actions(hass, ENTITY_ID)

    await hass.config_entries.async_reload(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    after = {
        entry.entity_id: (entry.unique_id, entry.device_id)
        for entry in entity_registry.entities.values()
        if entry.platform == DOMAIN
    }
    assert after == before
    assert actions == []
    # And it is live again straight away, not sitting at unknown until the
    # first poll.
    assert hass.states.get(ENTITY_ID).state == STATE_ON
