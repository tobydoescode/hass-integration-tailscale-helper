"""Finding Tailscale devices to derive connectivity from.

The Tailscale integration gives every tailnet device a ``last_seen`` sensor with
a unique_id of ``<device_id>_last_seen``. One pass over the entity registry
therefore yields the device list, the sensor to read, and the device to attach
to -- so that registry is our only source of truth. Nothing here is persisted:
device ids are resolved live on every scan, which is what keeps us clear of the
stale-composite-id trap that the HA 2026.8 device split creates for integrations
that store them.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import LAST_SEEN_SUFFIX, TAILSCALE_DOMAIN


@dataclass(frozen=True, slots=True)
class TailscaleSource:
    """A Tailscale device we can derive a connectivity sensor from."""

    device_id: str
    """Tailscale's own device id, taken from the source unique_id."""

    source_entity_id: str
    """The ``sensor.*_last_seen`` entity we read."""

    ha_device_id: str
    """The device registry id of the Tailscale device, which we attach to."""


def is_last_seen_sensor(entry: er.RegistryEntry) -> bool:
    """Whether a registry entry is a Tailscale ``last_seen`` sensor at all.

    Distinct from being *derivable* -- a disabled one, or one detached from its
    device, is still one of these. That distinction matters on the removal
    path: only an entry this returns ``True`` for carries a device id worth
    acting on. Anything else is an unrelated Tailscale entity, and treating it
    as one of ours would delete a sensor that is perfectly healthy.
    """
    return (
        entry.platform == TAILSCALE_DOMAIN
        and entry.domain == "sensor"
        and entry.unique_id.endswith(LAST_SEEN_SUFFIX)
    )


def device_id_from_entry(entry: er.RegistryEntry) -> str:
    """Return the Tailscale device id a ``last_seen`` sensor belongs to.

    Only meaningful for entries ``is_last_seen_sensor`` accepts: the suffix
    strip is a no-op otherwise, which would hand back something that is not a
    device id at all.
    """
    return entry.unique_id.removesuffix(LAST_SEEN_SUFFIX)


def source_from_entry(entry: er.RegistryEntry) -> TailscaleSource | None:
    """Return the source described by a registry entry, if we can derive from it.

    Returns ``None`` for anything we cannot or should not derive from: entities
    belonging to other integrations, Tailscale's other sensors, disabled
    entities, and entities with no device to attach to.
    """
    if not is_last_seen_sensor(entry):
        return None
    if entry.disabled:
        return None
    if entry.device_id is None:
        return None

    return TailscaleSource(
        device_id=device_id_from_entry(entry),
        source_entity_id=entry.entity_id,
        ha_device_id=entry.device_id,
    )


def iter_sources(hass: HomeAssistant) -> Iterator[TailscaleSource]:
    """Yield every Tailscale device currently derivable."""
    registry = er.async_get(hass)
    for entry in registry.entities.values():
        if (source := source_from_entry(entry)) is not None:
            yield source
