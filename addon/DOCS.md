# HA Fitness

The HA Fitness add-on is the server behind the HA Fitness integration. It stores the programs and workouts in the
add-on's own data folder, so they are part of Home Assistant backups, and computes the stats from them.

## Installation

Install the integration first, then accept the Discovered card.

1. Install the HA Fitness integration from HACS (see the repository's README), and restart Home Assistant.
2. In Home Assistant go to *Settings → Add-ons → Add-on store → ⋮ → Repositories* and add
   `https://github.com/thomas3650/Ha-Fitness`.
3. Install *HA Fitness* from the store and start it.
4. Go to *Settings → Devices & services*. Under *Discovered* there is a card *HA Fitness*. Choose *Add*, and confirm
   *HA Fitness app found*. The integration gets the add-on's address from the add-on itself: there is no URL to type.

If the add-on started before the integration was installed, the Discovered card appears after Home Assistant has
restarted with the integration. There is only one HA Fitness entry: when the add-on's address changes, the next
discovery updates the entry.

When one part needs a newer version of the other, Home Assistant shows a repair issue that says which part to update.
While the add-on is stopped or updating, the HA Fitness entities are unavailable and the card says that HA Fitness
can't be reached.

## Configuration

The options are on the add-on's *Configuration* tab. A changed option takes effect at the add-on's next start.

| Option | Default | What it does |
| --- | --- | --- |
| `late_days` | `2` | How many days after its date a late training can still be done, from 0 to 6. It closes earlier when the same program trains again. With 0 it closes at midnight. |

A training that closes this way counts as missed. A training closed already never reopens. When you lower the
number, open trainings past the new limit close as missed at the next start.

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

## The website

The add-on has a website (Ingress). Open it from the add-on's page with *Open web UI*, or turn on *Show in sidebar*
to get *HA Fitness* in the sidebar. It is in English, and for administrators.

- **Programs:** make, edit, switch on or off and delete programs.
- **Library:** browse every exercise, with its picture and instructions.
- **Setup:** choose the equipment you have, the people who train, your favourite playlists and a default speaker.
  Claude reads the setup when it suggests exercises and music.
- **Status:** the version, the exercise library, the people and the programs.

## The exercise library

The exercise data is built into the add-on. The GIFs and thumbnails (about 137 MB) are downloaded into the add-on's
data folder in the background at every start, when any are missing. A failed file is tried again at the next start.
The Status page shows how many are there.

## Backups

Backups run while the add-on runs (hot backups). Before each backup the add-on writes a consistent copy of its
database to `backup/snapshot.db` in its data folder. The backup holds that copy, not the live database files, and not
the downloaded media. After a restore the add-on starts from the copy, and downloads the media again.
The add-on also writes the snapshot when it stops, so a backup taken while it is stopped holds the data as of the
stop. Only after a crash does such a backup hold an older snapshot: the Supervisor runs the snapshot command only in a
running add-on.

## Workouts

Stopping or updating the add-on pauses a running workout; resume it on the tablet afterwards. A workout that stays
paused for 30 minutes ends.

## Support

Report problems at <https://github.com/thomas3650/Ha-Fitness/issues>.
