# HA Fitness

HA Fitness is circuit training at home, run from Home Assistant. On a training day the kitchen tablet shows that today
is a training day, runs the workout for one or two people with each person's current and next exercise, and keeps
per-person stats (streak, workouts done and missed, time trained). Programs are made by talking to Claude, not by
fiddling with settings screens.

**Status:** in development.

## Install

HA Fitness has two parts, both from this repository: an add-on (the server) and a custom integration with its cards.

1. **Add-on:** in Home Assistant go to *Settings → Add-ons → Add-on store → ⋮ → Repositories* and add
   `https://github.com/thomas3650/Ha-Fitness`. Then install *HA Fitness* from the store.
2. **Integration:** in HACS open *⋮ → Custom repositories*, add `https://github.com/thomas3650/Ha-Fitness` with the
   type *Integration*, then download *HA Fitness* and restart Home Assistant.
3. **Set up:** Home Assistant shows *HA Fitness* under *Settings → Devices & services → Discovered*. Add it; the add-on
   tells the integration its address. Without the add-on's discovery you can add it by hand with the add-on's URL.

## Docs

See [`docs/README.md`](docs/README.md) for the map of all docs.

## License

The code is under the [MIT License](LICENSE). The mockup GIFs in `docs/mockups/gifs/` and every exercise GIF are
© Gym visual (via [`hasaneyldrm/exercises-dataset`](https://github.com/hasaneyldrm/exercises-dataset)), for personal
use only, and are not covered by the LICENSE.
