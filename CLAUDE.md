# CLAUDE.md

This file provides guidance to Claude Code when working on this repository.

## Project Overview

Home Assistant custom integration that adds a connectivity binary sensor to every
device created by the built-in Tailscale integration. Tailscale ships a `last_seen`
timestamp sensor per tailnet device but no connectivity sensor; this integration
derives one from it.

Built and validated against a real tailnet. The design was decided up front; the
decisions that matter are summarised under *Key Design Decisions* below. Several
look arbitrary until you know what they are avoiding, so the reasoning is given
inline rather than assumed.

## Commands

```bash
# Install dependencies
uv sync --extra dev

# Run linter
uv run ruff check custom_components/ tests/

# Fix lint and formatting
uv run ruff check --fix custom_components/ tests/
uv run ruff format custom_components/ tests/

# Run type checker
uv run pyright custom_components/tailscale_helper/

# Run tests
uv run python -m pytest tests/ -v

# Run tests with coverage
uv run python -m pytest tests/ -v --cov=custom_components.tailscale_helper --cov-report=term-missing

# Start dev Home Assistant instance
docker compose up -d
```

`Taskfile.yml` wraps all of these (`task sync`, `task lint`, `task lint:fix`,
`task test`, `task dev`).

## Architecture

```
custom_components/tailscale_helper/
  __init__.py          # Config entry setup/teardown, platform forwarding, reload listener
  binary_sensor.py     # _SourceTracker (discovery wiring) + TailscaleConnectionState
  config_flow.py       # Single-submit config flow + options flow (threshold)
  const.py             # DOMAIN, CONF_THRESHOLD, DEFAULT_THRESHOLD = 300, SCAN_INTERVAL = 30s
  diagnostics.py       # Per-device derivation dump
  discovery.py         # Pure predicates + entity-registry scan (no HA plumbing)
  strings.json         # Translation strings (source of truth)
  translations/en.json # English translations (must match strings.json)
  manifest.json        # domain tailscale_helper, after_dependencies: ["tailscale"]
  brand/               # Generated artwork; see scripts/make_brand_assets.py
```

The split between `discovery.py` and `binary_sensor.py` is by testability, not by
subject. `discovery.py` is pure — predicates and a registry walk, no HA plumbing,
trivially unit-testable. The event wiring has to live in `binary_sensor.py` because
`async_add_entities` only exists inside platform setup.

### Key Design Decisions

Each of these was verified against Home Assistant's source rather than assumed —
the device-registry ones against the `dev` branch, since the behaviour changes in
2026.8.

- **Single config entry, no subentries.** Every Tailscale device already has a
  `last_seen` sensor and there is nothing to ask the user, so one entry
  auto-creates a sensor per device with zero clicks. (Battery Notes uses
  `ConfigSubentry` per device; we deliberately do not.)
- **Entity registry is both the device list and the data source.** One pass over
  the entity registry for `platform == "tailscale"` and
  `unique_id.endswith("_last_seen")` yields the tailnet device id, the source
  `entity_id`, and the HA device to attach to. We never call the Tailscale API and
  never read `hass.data["tailscale"]` internals.
- **Attach via `entity.device_entry`, never `device_info`.** Resolve the
  `DeviceEntry` with `homeassistant.helpers.device.async_entity_id_to_device` and
  assign `self.device_entry` directly. Defining a `device_info` property would make
  `entity_platform` call `async_get_or_create` and form a *composite device*, which
  is what HA is deprecating. With no `device_info`, `entity_platform` just takes
  `entity.device_entry` and no config entry is added to the Tailscale device. HA
  core's `derivative` integration does exactly this
  (`add_helper_config_entry_to_device=False`). **Never add a `device_info` property
  to our entities.** `via_device` is rejected for the same reason.
- **Platform polling, no coordinator.** `_attr_should_poll = True` with
  `SCAN_INTERVAL = timedelta(seconds=30)` in `binary_sensor.py`, plus a state
  listener so the off→on transition is instant. HA owns all scheduling, so there
  are no timers to leak. The source only refreshes once a minute, so a 30s lag on
  the off transition is immaterial.
- **Threshold is a single global option, default 300s.** The config flow has no
  fields; the options flow exposes one number in seconds and reloads the entry on
  change.
- **Unknown vs unavailable are split.** Source `unavailable` (Tailscale API down,
  entity disabled or missing) → ours **unavailable**. Source `unknown` or
  unparseable → ours **off**. An automation on `connectivity → off` must not fire
  because Tailscale itself broke.
- **Lifecycle keys off the source entity, not the device.** Removing a Tailscale
  device *orphans* our entity (`device_id=None`) rather than deleting it, so
  cleanup must watch for the source entity's removal from the registry.
  `manifest.json` declares `after_dependencies: ["tailscale"]` so we load after
  Tailscale when present but still set up (with zero entities) when it is absent.
- **Do not use `async_handle_source_entity_changes`.** It assumes one helper config
  entry per source entity and would reload all N of our entities on any single
  source change. Hand-rolled listeners instead.
- **Naming.** Domain `tailscale_helper`, name "Tailscale Helper", `translation_key`
  `connection_state`, display name "Connection state" (sentence case, per HA style).
  Friendly name composes to `home-router Connection state`. Entity ids derive from
  `has_entity_name` + `translation_key` alone — do **not** set `entity_id`
  explicitly; it is unnecessary and was verified against real device names
  containing dots, dashes and apostrophes.
- **`async_add_entities(..., update_before_add=True)` is required.** A polled entity
  otherwise reports `unknown` until its first poll — up to a full 30s after
  appearing, and after every restart.
- **`is_last_seen_sensor` is separate from `source_from_entry` on purpose.** The
  first asks "is this one of the sensors we derive from", the second "is it
  *currently* derivable". The removal path needs the former: using a
  `removesuffix` as a stand-in silently passed unrelated Tailscale entities
  through as device ids, which would delete a healthy sensor. See ticket `14`.

### Data Flow

1. `__init__.py` sets up the single config entry and forwards to `binary_sensor`
2. Behind `async_at_started` (so Tailscale has loaded), scan the entity registry
   for `tailscale` `*_last_seen` entities; each yields one of our entities
3. Subscribe to `EVENT_ENTITY_REGISTRY_UPDATED`: `create` on a matching entity adds
   ours, `remove` removes ours from the registry
4. Each entity resolves its `device_entry` from the source entity and is added
   without `device_info`, so it lands on the Tailscale device
5. `async_update` (every 30s) reads the source state and compares `last_seen` to
   `dt_util.utcnow()` against the threshold; a state listener short-circuits the
   off→on transition

## Testing

Tests use `pytest-homeassistant-custom-component` with `MockConfigEntry`. 48 tests,
100% coverage of the integration's modules; `--cov-fail-under = 95` in
`pyproject.toml` is a floor, not a target — pinning it at 100 only teaches people
to reach for `# pragma: no cover`.

**Mutation-test anything non-obvious.** Several tests here passed for the wrong
reason on first writing: a duplicate-prevention test was measuring HA's own
unique-id dedup rather than our guard, and a sort-order test passed because the
fixture happened to insert in sorted order. Break the mechanism, confirm the test
fails, restore. It has caught something almost every time it was tried.

The harness pattern is copied from HA core's `tests/components/derivative/`:

- A `MockConfigEntry(domain="tailscale")` is added to hass but **never set up**, so
  the real Tailscale integration is never imported and no API key is needed. It
  exists purely to own devices.
- `device_registry.async_get_or_create(identifiers={("tailscale", device_id)}, ...)`
  plus `entity_registry.async_get_or_create("sensor", "tailscale", f"{device_id}_last_seen", ...)`
  fakes a tailnet device. The registry and the state machine are independent —
  tests must also `hass.states.async_set(...)` the timestamp.
- Advancing time needs **both** `freezer.tick(...)` (what `utcnow()` returns) and
  `async_fire_time_changed(hass, dt_util.utcnow())` (what fires the poll).
- Do **not** fake `EVENT_ENTITY_REGISTRY_UPDATED`; mutating the real registry emits
  it, which also exercises our filtering.
- The regression test for the composite-device decision is
  `assert helper_config_entry.entry_id not in tailscale_device.config_entries`.

## CI

GitHub Actions workflow (`.github/workflows/ci.yml`) runs on push to main and on PRs:

1. Ruff lint and format check
2. Pyright type checking
3. Pytest with coverage reporting
4. Coverage summary in GitHub step summary

`.github/workflows/validate.yml` runs HACS validation and hassfest. It passes
`ignore: brands` to the HACS action, because that check queries the
`home-assistant/brands` repo over the network and fails until the domain is
registered there — a separate PR on the HA team's review queue. Artwork is ready in
`custom_components/tailscale_helper/brand/`; **drop the `ignore` once a brands PR
merges.** A local logo does not satisfy the check.

Python is pinned to **3.13** everywhere — `.python-version`, `requires-python`, the
ruff `target-version`, and the CI `setup-python` step. Home Assistant 2026.x
declares `requires-python >= 3.13.2` and its Docker image runs 3.13.
