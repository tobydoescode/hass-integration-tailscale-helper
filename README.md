<img src="custom_components/tailscale_helper/brand/logo.png" alt="Tailscale Helper" height="72">

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tobydoescode&repository=hass-integration-tailscale-helper&category=integration)

Adds a **Connection state** binary sensor to every device from the Home Assistant
[Tailscale](https://www.home-assistant.io/integrations/tailscale/) integration.

## Why

Tailscale's integration tells you when a device was **last seen**. It does not
tell you whether that device is up *now* — and a timestamp is awkward to use in
an automation.

This adds the missing sensor:

```
Devices > Tailscale > home-router
  Last seen         2026-07-28 12:04:11
  IP                100.64.0.3
  Connection state  Connected          <- added by Tailscale Helper
```

Each sensor is `device_class: connectivity`, so it reads **Connected** /
**Disconnected** and works anywhere Home Assistant expects a connectivity
sensor.

## How it works

A device is **Connected** when its `last_seen` is more recent than the threshold,
**Disconnected** when it is not.

Sensors appear for every Tailscale device automatically — there is nothing to
pick or configure. Devices joining your tailnet later get one without a restart,
and devices leaving take theirs with them.

No credentials are needed. This integration reads the sensors the Tailscale
integration already publishes; it never talks to the Tailscale API, so there is
no second API key and no extra polling.

## Install

**HACS**

1. HACS → **Custom repositories**
2. Add `https://github.com/tobydoescode/hass-integration-tailscale-helper` with category **Integration**
3. Install **Tailscale Helper**, restart Home Assistant

**Manual** — copy `custom_components/tailscale_helper` into your `config/custom_components/` and restart.

Then set up the **Tailscale** integration if you have not already, and add
**Tailscale Helper** from **Settings → Devices & Services → Add Integration**.
It is a single Submit; there is nothing to fill in.

## The threshold

**Settings → Devices & Services → Tailscale Helper → Configure.**

Default is **300 seconds**. A device that has not checked in to Tailscale for
longer than this reads Disconnected.

Raise it for devices that sleep — phones and laptops can go quiet for minutes at
a time while perfectly healthy. Lower it for always-on machines where you want
faster alerting. Below about 120 seconds is not advisable: Tailscale's
integration only refreshes once a minute, so a tight threshold turns ordinary
polling jitter into false disconnects.

Changing the threshold reloads the integration and applies to every device.

### How quickly it notices

Worst case is roughly **six and a half minutes** from a device going quiet to the
sensor turning off:

| | |
|---|---|
| the threshold itself | up to 300s |
| Tailscale's own refresh | up to 60s |
| this integration's poll | up to 30s |

Coming back online is near-instant — the sensor reacts to the Tailscale sensor
updating rather than waiting for its next poll.

## Troubleshooting

**Download diagnostics** from the three-dot menu on the Tailscale Helper entry.
It shows the whole derivation for every device — the source sensor, its raw
value, the computed age, and the resulting state — so you can check the
arithmetic yourself:

```json
{
  "threshold_seconds": 300,
  "devices": [
    {
      "device_id": "nODdc3",
      "source": "sensor.home_router_last_seen",
      "source_state": "2026-07-28T12:04:11+00:00",
      "age_seconds": 42.2,
      "is_on": true
    }
  ]
}
```

Two things in there that look wrong but are not:

- **`age_seconds` past the threshold while `is_on` is still `true`.** `is_on` is
  read from the published sensor rather than recomputed, so between polls the age
  can cross the line before the state catches up. That means *stale*, not
  *wrong*.
- **A negative `age_seconds`.** The device's clock is ahead of yours, so its
  `last_seen` is in the future. It counts as connected.

**A device has no Connection state sensor.** Its `Last seen` sensor is probably
disabled — we derive from that sensor, so there is nothing to work with. Enable
it and the Connection state sensor appears.

**Tailscale Helper is not listed on the device page.** That is deliberate. The
sensor is attached to the Tailscale device without taking ownership of it, which
is what keeps Home Assistant from treating it as a device shared between two
integrations. Manage the integration from its own entry instead.

## Development

Requires [uv](https://docs.astral.sh/uv/), [Task](https://taskfile.dev) and
[Docker](https://www.docker.com).

| Command | Description |
|---|---|
| `task sync` | Install Python dependencies |
| `task lint` | Run ruff linter and format check |
| `task lint:fix` | Auto-fix lint and formatting issues |
| `task test` | Run pytest |
| `task dev` | Start Home Assistant in Docker on :8123 |
| `task dev:stop` | Stop Home Assistant |
| `task dev:restart` | Restart Home Assistant after code changes |
| `task dev:logs` | Tail Home Assistant logs |

The dev instance mounts `custom_components/tailscale_helper` read-only, so
`task dev:restart` picks up code changes. Add the Tailscale integration to it
with an API key and tailnet name to test against real devices.

Brand artwork is generated, not hand-drawn — `uv run --with pillow python
scripts/make_brand_assets.py`.

## License

[MIT](LICENSE)
