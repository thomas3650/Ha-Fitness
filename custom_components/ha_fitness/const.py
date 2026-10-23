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
