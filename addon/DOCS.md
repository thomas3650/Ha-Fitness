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

| Port       | What it is                                                                 |
| ---------- | -------------------------------------------------------------------------- |
| `8765/tcp` | The HA Fitness API: REST at `/api/v1/` for the integration, MCP at `/mcp`. |

Check that the add-on runs: `http://<your-home-assistant>:8765/api/v1/health` answers with the server version.

Keep port 8765 on your local network. Don't expose it to the internet, for example through a tunnel.

## Discovery

At every start the add-on tells Home Assistant where its API is (Supervisor discovery). Home Assistant then offers to
set up the HA Fitness integration, with the right address, so you never type a URL. If the message can't be sent, the
add-on writes a warning to its log and keeps running; the next start tries again.

## Timezone

The add-on follows Home Assistant's timezone (*Settings → System → General*). It decides which date a training day
belongs to and when midnight is. A changed timezone takes effect when the add-on restarts. There is no option to set.

## Making programs with Claude

Claude reaches the add-on over MCP at `http://<your-home-assistant>:8765/mcp`. Add it to Claude Code under the name
`ha-fitness-house`, in local scope, from a folder **outside** the HA Fitness repository (for example your home
folder):

```bash
claude mcp add --transport http ha-fitness-house http://<your-home-assistant>:8765/mcp
```

Sessions in the repository then never see your real data.

## The add-on's page

The add-on has a small status page (Ingress): its version, the exercise library, the people and the programs. Open it
from the add-on's page with *Open web UI*, or turn on *Show in sidebar* to get *HA Fitness* in the sidebar. The page is
in Danish when your browser prefers Danish, otherwise in English.

## The exercise library

The exercise data is built into the add-on. The GIFs and thumbnails (about 72 MB) are downloaded into the add-on's
data folder in the background at every start, when any are missing. A failed file is tried again at the next start.
The status page shows how many are there.

## Backups

Backups run while the add-on runs (hot backups). Before each backup the add-on writes a consistent copy of its
database to `backup/snapshot.db` in its data folder. The backup holds that copy, not the live database files, and not
the downloaded media. After a restore the add-on starts from the copy, and downloads the media again.
A backup taken while the add-on is stopped holds the last snapshot only, because the Supervisor runs the snapshot
command only in a running add-on.

## Support

Report problems at <https://github.com/thomas3650/Ha-Fitness/issues>.
