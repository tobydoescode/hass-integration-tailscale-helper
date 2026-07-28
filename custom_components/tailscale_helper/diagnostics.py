"""Diagnostics for the Tailscale Helper integration.

The dump is the whole derivation chain, one row per discovered device: the
source entity we read, the raw state it held, the age we computed from it, and
the state we published as a result. That is enough for a reader to check our
arithmetic without running anything, which is the only way the characteristic
"why does this say disconnected" report can be answered from a bug tracker.

No credential can reach this dump, having been checked rather than assumed. We
read exactly one sensor per device -- Tailscale's ``*_last_seen``, a timestamp --
and never touch the Tailscale config entry or its coordinator, so the values it
redacts in its own diagnostics (API key, tailnet, addresses, endpoints, machine
and node keys, user) are all out of reach.

The Tailscale device id **is** redacted, matching what Tailscale's own
diagnostics does with it. It identifies a machine on someone's private network
and buys the reader nothing: rows stay distinguishable by ``source``, which is
what you actually match against a misbehaving entity.

Note the entity id in ``source`` still contains the device's hostname. That is
deliberate -- it is the whole basis for matching a row to the entity in front of
you, and without it the dump answers nothing. Anyone posting a dump publicly
should know their hostnames are in it.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .binary_sensor import UNIQUE_ID_SUFFIX
from .const import CONF_THRESHOLD, DEFAULT_THRESHOLD, DOMAIN
from .discovery import TailscaleSource, iter_sources

TO_REDACT = {"device_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    registry = er.async_get(hass)

    return {
        "threshold_seconds": entry.options.get(CONF_THRESHOLD, DEFAULT_THRESHOLD),
        "devices": [
            async_redact_data(_device_diagnostics(hass, registry, source), TO_REDACT)
            for source in sorted(iter_sources(hass), key=lambda source: source.device_id)
        ],
    }


def _device_diagnostics(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    source: TailscaleSource,
) -> dict[str, Any]:
    """Return one device's whole derivation, input through to output."""
    state = hass.states.get(source.source_entity_id)
    source_state = state.state if state is not None else None

    return {
        "device_id": source.device_id,
        "source": source.source_entity_id,
        "source_state": source_state,
        "age_seconds": _age_seconds(source_state),
        "is_on": _our_state(hass, registry, source.device_id),
    }


def _age_seconds(source_state: str | None) -> float | None:
    """Return how old the source timestamp is, or None if it is not one."""
    if source_state is None or (last_seen := dt_util.parse_datetime(source_state)) is None:
        return None
    return round((dt_util.utcnow() - last_seen).total_seconds(), 1)


def _our_state(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    device_id: str,
) -> bool | None:
    """Return what our own sensor is currently reporting for this device.

    Read rather than recomputed: the point of the dump is to show whether our
    published state agrees with the arithmetic beside it.
    """
    entity_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{device_id}{UNIQUE_ID_SUFFIX}"
    )
    if entity_id is None or (state := hass.states.get(entity_id)) is None:
        return None
    return {STATE_ON: True, STATE_OFF: False}.get(state.state)
