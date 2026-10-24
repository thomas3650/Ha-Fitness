"""Constants for the HA Fitness integration."""

from typing import Final

DOMAIN: Final = "ha_fitness"

# The Lovelace cards bundle (built by the cards project into frontend/) and the URL it is served under.
CARDS_FILE: Final = "ha-fitness-cards.js"
FRONTEND_URL_BASE: Final = "/ha_fitness_frontend"

# Every entry has this unique id: there is one add-on, so one entry.
UNIQUE_ID: Final = "ha_fitness"

# The add-on's address in the fast loop; also what a version 1 entry is migrated to.
DEFAULT_URL: Final = "http://localhost:8765"

# The device's name; the product's name, so not translated.
DEVICE_NAME: Final = "HA Fitness"

# The add-on's training-day events this version knows; each fires ha_fitness_training_day_<event>.
TRAINING_DAY_EVENTS: Final = ("due", "skipped", "missed", "done")
EVENT_PREFIX: Final = f"{DOMAIN}_training_day_"

# The add-on's session events this version knows; each fires ha_fitness_<event>.
SESSION_EVENTS: Final = (
    "session_started",
    "session_completed",
    "session_ended",
    "phase_changed",
)

# Sent on the dispatcher whenever what the add-on holds changes, or the entry loads or unloads.
SIGNAL_UPDATE: Final = f"{DOMAIN}_update"
