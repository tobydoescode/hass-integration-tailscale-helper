"""Connection state binary sensors for Tailscale devices."""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Iterable
from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device import async_entity_id_to_device
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .const import (
    CONF_THRESHOLD,
    DEFAULT_THRESHOLD,
    DOMAIN,
    LAST_SEEN_SUFFIX,
    LOGGER,
    SCAN_INTERVAL,
    TAILSCALE_DOMAIN,
)
from .discovery import (
    TailscaleSource,
    device_id_from_entry,
    is_last_seen_sensor,
    iter_sources,
    source_from_entry,
)

__all__ = ["SCAN_INTERVAL"]

UNIQUE_ID_SUFFIX = "_connection_state"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tailscale Helper binary sensors."""
    threshold = timedelta(seconds=entry.options.get(CONF_THRESHOLD, DEFAULT_THRESHOLD))
    tracker = _SourceTracker(hass, async_add_entities, threshold)
    entry.async_on_unload(async_at_started(hass, tracker.async_start(entry)))


class _SourceTracker:
    """Keeps the set of sensors in step with the Tailscale entity registry."""

    def __init__(
        self,
        hass: HomeAssistant,
        async_add_entities: AddConfigEntryEntitiesCallback,
        threshold: timedelta,
    ) -> None:
        """Initialise the tracker."""
        self._hass = hass
        self._async_add_entities = async_add_entities
        self._threshold = threshold
        self._known: set[str] = set()

    def async_start(
        self, entry: ConfigEntry
    ) -> Callable[[HomeAssistant], Coroutine[Any, Any, None]]:
        """Return the start callback for ``async_at_started``."""

        async def _start(_: HomeAssistant) -> None:
            # Subscribe before scanning so a device joining mid-scan is not lost.
            entry.async_on_unload(
                self._hass.bus.async_listen(
                    er.EVENT_ENTITY_REGISTRY_UPDATED, self._async_registry_updated
                )
            )
            self._async_add(iter_sources(self._hass))

        return _start

    @callback
    def _async_add(self, sources: Iterable[TailscaleSource]) -> None:
        """Add sensors for sources not already tracked.

        Skipping the ones we have keeps a scan/event race from re-adding a
        device, which Home Assistant would reject as a duplicate unique_id --
        correctly, but with an ERROR in the user's log.
        """
        new = [source for source in sources if source.device_id not in self._known]
        if not new:
            return
        self._known.update(source.device_id for source in new)
        self._async_add_entities(
            (TailscaleConnectionState(self._hass, source, self._threshold) for source in new),
            # Without this the sensor sits at "unknown" until the first poll,
            # up to a full scan interval after it appears.
            update_before_add=True,
        )

    @callback
    def _async_remove(self, device_id: str) -> None:
        """Drop the sensor for a device that has gone away.

        Removing our registry entry is what makes the entity platform tear the
        entity down. We cannot wait for the device removal to do it: Home
        Assistant only deletes entities whose own config entry owned that
        device, and ours does not, so it would detach ours and leave it behind.
        """
        if device_id not in self._known:
            return
        self._known.discard(device_id)

        registry = er.async_get(self._hass)
        entity_id = registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{device_id}{UNIQUE_ID_SUFFIX}"
        )
        if entity_id is not None:
            LOGGER.debug("Removing %s, its Tailscale source is gone", entity_id)
            registry.async_remove(entity_id)

    @callback
    def _async_registry_updated(self, event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        """React to Tailscale entities appearing, disappearing or changing."""
        registry = er.async_get(self._hass)

        if event.data["action"] == "remove":
            self._async_drop_vanished(registry)
            return

        entry = registry.async_get(event.data["entity_id"])
        if entry is None:
            return

        if (source := source_from_entry(entry)) is not None:
            self._async_add([source])
        elif is_last_seen_sensor(entry):
            # It is one of the sensors we derive from, but no longer derivable
            # -- disabled, or detached from its device. Testing for the sensor
            # specifically matters: any other Tailscale entity would otherwise
            # yield a bogus device id here and delete a healthy sensor.
            self._async_remove(device_id_from_entry(entry))

    @callback
    def _async_drop_vanished(self, registry: er.EntityRegistry) -> None:
        """Remove sensors whose source no longer exists.

        A remove event carries no unique_id, so the tracked devices are checked
        against the registry instead.
        """
        for device_id in list(self._known):
            source_exists = registry.async_get_entity_id(
                "sensor", TAILSCALE_DOMAIN, f"{device_id}{LAST_SEEN_SUFFIX}"
            )
            if source_exists is None:
                self._async_remove(device_id)


class TailscaleConnectionState(BinarySensorEntity):
    """Whether a Tailscale device has checked in recently enough."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "connection_state"
    # The state depends on the passage of time, not only on source updates: a
    # device that stops reporting produces no event at all. Polling is what
    # notices that silence.
    _attr_should_poll = True

    def __init__(self, hass: HomeAssistant, source: TailscaleSource, threshold: timedelta) -> None:
        """Initialise the sensor for one Tailscale device."""
        self._source_entity_id = source.source_entity_id
        self._threshold = threshold
        self._attr_unique_id = f"{source.device_id}{UNIQUE_ID_SUFFIX}"

        # Attach to the Tailscale device without claiming it. Assigning
        # device_entry directly -- and never defining a device_info property --
        # keeps our config entry off their device, so no composite device is
        # formed. Core's own derivative integration attaches the same way.
        self.device_entry = async_entity_id_to_device(hass, source.source_entity_id)

    async def async_added_to_hass(self) -> None:
        """Track the source so coming back online is reflected immediately.

        Polling alone would leave a device offline for up to a poll interval
        after it has plainly returned.
        """
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source_entity_id], self._async_source_changed
            )
        )

    @callback
    def _async_source_changed(self, _: Event[EventStateChangedData]) -> None:
        """Re-evaluate as soon as the source reports."""
        self.async_schedule_update_ha_state(force_refresh=True)

    async def async_update(self) -> None:
        """Recompute from the source's last_seen and the current time."""
        state = self.hass.states.get(self._source_entity_id)

        # No state, or an explicitly unavailable source, means we cannot tell.
        # Reporting "disconnected" here would fire connectivity automations
        # during a Tailscale outage.
        if state is None or state.state == STATE_UNAVAILABLE:
            self._attr_available = False
            return

        self._attr_available = True

        # Anything that is not a timestamp -- "unknown", "", or junk -- means
        # Tailscale has not seen this device, which is disconnected rather than
        # unknowable.
        last_seen = dt_util.parse_datetime(state.state)
        if last_seen is None:
            self._attr_is_on = False
            return

        self._attr_is_on = (dt_util.utcnow() - last_seen) < self._threshold
