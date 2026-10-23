# HA Fitness

The HA Fitness add-on is the server behind the HA Fitness integration. It stores the programs, workouts and stats in
the add-on's own data folder, so they are part of Home Assistant backups.

## Installation

1. In Home Assistant go to *Settings → Add-ons → Add-on store → ⋮ → Repositories* and add
   `https://github.com/thomas3650/Ha-Fitness`.
2. Install *HA Fitness* from the store and start it.
3. Install the HA Fitness integration from HACS (see the repository's README).

## Configuration

The add-on has no options yet.

## Network

| Port       | What it is                                    |
| ---------- | --------------------------------------------- |
| `8765/tcp` | The HA Fitness API, used by the integration. |

Check that the add-on runs: `http://<your-home-assistant>:8765/api/v1/health` answers with the server version.

## Support

Report problems at <https://github.com/thomas3650/Ha-Fitness/issues>.
