"""Discovery tests for Tailscale Helper."""

from __future__ import annotations

import pytest
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tailscale_helper.const import DOMAIN

ROUTER_ENTITY_ID = "binary_sensor.home_router_connection_state"


async def test_initial_scan_finds_existing_devices(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """Devices already present when we load each get a Connection state sensor."""
    router_device, _ = add_tailscale_device("home-router", "abc")
    laptop_device, _ = add_tailscale_device("laptop", "def")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    router = entity_registry.async_get("binary_sensor.home_router_connection_state")
    laptop = entity_registry.async_get("binary_sensor.laptop_connection_state")
    assert router is not None
    assert laptop is not None

    # Each is attached to the Tailscale device it derives from.
    assert router.device_id == router_device.id
    assert laptop.device_id == laptop_device.id


async def test_attaching_does_not_create_a_composite_device(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """Our entry must never be added to the Tailscale device.

    Regression test for decision 8. If anyone adds a ``device_info`` property to
    the entity, ``async_get_or_create`` would fold our config entry into their
    device and form a composite -- the shape HA 2026.8 splits apart.
    """
    router_device, _ = add_tailscale_device("home-router", "abc")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    router_device = device_registry.async_get(router_device.id)
    assert helper_config_entry.entry_id not in router_device.config_entries


async def test_device_joining_later_is_picked_up(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """A device joining the tailnet after setup gets a sensor, without a reload."""
    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get("binary_sensor.phone_connection_state") is None

    phone_device, _ = add_tailscale_device("phone", "ghi")
    await hass.async_block_till_done()

    phone = entity_registry.async_get("binary_sensor.phone_connection_state")
    assert phone is not None
    assert phone.device_id == phone_device.id


async def test_source_entity_removed_removes_ours(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """Removing the Tailscale last_seen sensor removes our sensor too."""
    _, source = add_tailscale_device("phone", "ghi")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get("binary_sensor.phone_connection_state") is not None

    entity_registry.async_remove(source.entity_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get("binary_sensor.phone_connection_state") is None


async def test_device_removed_removes_ours_rather_than_orphaning(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """Removing the Tailscale device must not leave our sensor stranded.

    HA only deletes entities whose own config entry owned the removed device.
    Ours does not, so left alone HA would set our device_id to None and keep the
    entity. Their last_seen sensor *is* deleted though, and that is the signal
    we act on.
    """
    phone_device, _ = add_tailscale_device("phone", "ghi")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get("binary_sensor.phone_connection_state") is not None

    device_registry.async_remove_device(phone_device.id)
    await hass.async_block_till_done()

    assert entity_registry.async_get("binary_sensor.phone_connection_state") is None


async def test_ignores_entities_we_cannot_derive_from(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    tailscale_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """Only enabled, device-attached Tailscale last_seen sensors count."""
    # A Tailscale sensor that is not last_seen.
    entity_registry.async_get_or_create(
        "sensor", "tailscale", "abc_ip", config_entry=tailscale_config_entry
    )
    # A last_seen sensor from a different integration entirely.
    entity_registry.async_get_or_create("sensor", "some_other_integration", "xyz_last_seen")
    # A Tailscale last_seen sensor with no device to attach to.
    entity_registry.async_get_or_create(
        "sensor",
        "tailscale",
        "nodevice_last_seen",
        config_entry=tailscale_config_entry,
        suggested_object_id="orphan_last_seen",
    )
    # A disabled one.
    add_tailscale_device("sleepy", "jkl", disabled_by=er.RegistryEntryDisabler.USER)

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    ours = [entry for entry in entity_registry.entities.values() if entry.platform == DOMAIN]
    assert ours == []


async def test_create_event_for_known_source_is_ignored_quietly(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """The initial scan racing a create event must not re-add the device.

    Home Assistant would catch a duplicate anyway, by rejecting the second
    entity for reusing a unique_id -- but it does so with an ERROR in the log.
    Tracking what we have already added is what keeps that out of the log, so
    the absence of the error is the thing worth asserting.
    """
    _, source = add_tailscale_device("home-router", "abc")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    caplog.clear()
    hass.bus.async_fire(
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        {"action": "create", "entity_id": source.entity_id},
    )
    await hass.async_block_till_done()

    ours = [entry for entry in entity_registry.entities.values() if entry.platform == DOMAIN]
    assert len(ours) == 1
    assert "does not generate unique IDs" not in caplog.text


async def test_removing_one_source_leaves_the_others_alone(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """One device leaving the tailnet must not take the rest down with it.

    A remove event names no device, so every tracked device is re-checked
    against the registry. Re-checking is what stops that sweep from clearing
    everything.
    """
    _, router_source = add_tailscale_device("home-router", "abc")
    add_tailscale_device("laptop", "def")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_registry.async_remove(router_source.entity_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get("binary_sensor.home_router_connection_state") is None
    assert entity_registry.async_get("binary_sensor.laptop_connection_state") is not None
    assert hass.states.get("binary_sensor.laptop_connection_state") is not None


async def test_tailscales_other_entities_do_not_disturb_ours(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    tailscale_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """Tailscale's non-last_seen entities are traffic we must ignore.

    Every Tailscale entity registry event reaches our listener, and a device has
    several entities besides last_seen. Those arriving -- or changing later --
    must leave our sensor exactly where it was.
    """
    device, _ = add_tailscale_device("home-router", "abc")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    ip_sensor = entity_registry.async_get_or_create(
        "sensor",
        "tailscale",
        "abc_ip",
        config_entry=tailscale_config_entry,
        device_id=device.id,
    )
    entity_registry.async_get_or_create(
        "binary_sensor",
        "tailscale",
        "abc_client_supports_hair_pinning",
        config_entry=tailscale_config_entry,
        device_id=device.id,
    )
    entity_registry.async_update_entity(ip_sensor.entity_id, name="Tailscale address")
    await hass.async_block_till_done()

    ours = [entry for entry in entity_registry.entities.values() if entry.platform == DOMAIN]
    assert [entry.entity_id for entry in ours] == ["binary_sensor.home_router_connection_state"]


async def test_source_gone_before_we_handle_its_event_is_ignored(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """A source can vanish between its event firing and our handling of it.

    Registry listeners all run inside the one dispatch, in registration order,
    so an integration that cleans up on registry events can delete an entity
    before our handler ever looks at it. Home Assistant's own
    ``EntityRegistry.async_remove`` documents that race. Reaching for the
    already-gone entry would raise inside the event bus, which swallows it into
    an "Error running job" traceback rather than failing anything visibly -- so
    the absence of that traceback is what is worth asserting.
    """

    @callback
    def remove_on_sight(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        if event.data["action"] == "create" and event.data["entity_id"].endswith("_last_seen"):
            entity_registry.async_remove(event.data["entity_id"])

    # Registered before ours, so it runs first within the same dispatch.
    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, remove_on_sight)

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()
    caplog.clear()

    add_tailscale_device("phone", "ghi")
    await hass.async_block_till_done()

    assert "Error running job" not in caplog.text
    assert entity_registry.async_get("binary_sensor.phone_connection_state") is None


async def test_re_enabling_the_source_restores_ours(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """Re-enabling the Tailscale sensor brings our sensor back, under its old id."""
    _, source = add_tailscale_device("home-router", "abc")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_registry.async_update_entity(source.entity_id, disabled_by=er.RegistryEntryDisabler.USER)
    await hass.async_block_till_done()
    assert entity_registry.async_get("binary_sensor.home_router_connection_state") is None

    entity_registry.async_update_entity(source.entity_id, disabled_by=None)
    await hass.async_block_till_done()

    restored = entity_registry.async_get("binary_sensor.home_router_connection_state")
    assert restored is not None
    assert restored.unique_id == "abc_connection_state"


async def test_disabling_the_source_removes_ours(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """Disabling the Tailscale sensor removes the sensor derived from it."""
    _, source = add_tailscale_device("home-router", "abc")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get("binary_sensor.home_router_connection_state") is not None

    entity_registry.async_update_entity(source.entity_id, disabled_by=er.RegistryEntryDisabler.USER)
    await hass.async_block_till_done()

    assert entity_registry.async_get("binary_sensor.home_router_connection_state") is None


async def test_unrelated_tailscale_entity_cannot_delete_our_sensor(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    tailscale_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """A Tailscale entity whose unique_id collides with a device id is harmless.

    The removal path strips the ``_last_seen`` suffix to recover a device id,
    and ``removesuffix`` is a no-op when the suffix is absent -- so an entity
    whose unique_id is *exactly* a device id would be handed straight through
    as though it were one, silently deleting that device's sensor.
    """
    add_tailscale_device("home-router", "abc")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get(ROUTER_ENTITY_ID) is not None

    entity_registry.async_get_or_create(
        "sensor",
        "tailscale",
        "abc",
        config_entry=tailscale_config_entry,
        suggested_object_id="home_router_something_else",
    )
    await hass.async_block_till_done()

    assert entity_registry.async_get(ROUTER_ENTITY_ID) is not None


async def test_non_sensor_last_seen_entity_cannot_delete_our_sensor(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    tailscale_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """Only a *sensor* named ``<device_id>_last_seen`` is one of ours.

    A Tailscale entity in another domain whose unique_id happens to end
    ``_last_seen`` is not derivable, and must not be mistaken for one of ours
    going away.
    """
    add_tailscale_device("home-router", "abc")

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get(ROUTER_ENTITY_ID) is not None

    entity_registry.async_get_or_create(
        "binary_sensor",
        "tailscale",
        "abc_last_seen",
        config_entry=tailscale_config_entry,
        suggested_object_id="home_router_recently_seen",
    )
    await hass.async_block_till_done()

    assert entity_registry.async_get(ROUTER_ENTITY_ID) is not None


async def test_update_to_a_source_we_never_tracked_is_harmless(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    helper_config_entry: MockConfigEntry,
    add_tailscale_device,
) -> None:
    """A last_seen sensor disabled before we ever saw it can still be updated.

    It is one of ours by shape but was never tracked, so the removal path is
    asked to drop a device it does not hold. That must be a no-op rather than
    disturbing the sensors we do hold.
    """
    add_tailscale_device("home-router", "abc")
    _, never_seen = add_tailscale_device("sleepy", "jkl", disabled_by=er.RegistryEntryDisabler.USER)

    assert await hass.config_entries.async_setup(helper_config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get(ROUTER_ENTITY_ID) is not None
    assert entity_registry.async_get("binary_sensor.sleepy_connection_state") is None

    entity_registry.async_update_entity(never_seen.entity_id, name="Renamed")
    await hass.async_block_till_done()

    assert entity_registry.async_get(ROUTER_ENTITY_ID) is not None
    assert entity_registry.async_get("binary_sensor.sleepy_connection_state") is None
