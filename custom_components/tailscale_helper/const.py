"""Constants for the Tailscale Helper integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Final

DOMAIN: Final = "tailscale_helper"
NAME: Final = "Tailscale Helper"

LOGGER: Final = logging.getLogger(__package__)

# How often HA polls our entities. The state depends on the passage of time, not
# only on source updates, so polling is what makes a device go quiet -> off.
SCAN_INTERVAL: Final = timedelta(seconds=30)

# A device is considered connected if its last_seen is more recent than this.
CONF_THRESHOLD: Final = "threshold"
DEFAULT_THRESHOLD: Final = 300

# The Tailscale integration we read from. Its last_seen sensors carry a
# unique_id of "<device_id>_last_seen" and are the only thing we key off.
TAILSCALE_DOMAIN: Final = "tailscale"
LAST_SEEN_SUFFIX: Final = "_last_seen"
