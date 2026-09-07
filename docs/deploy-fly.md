# Deploy the watcher on Fly.io

Run monohunter's 24/7 fresh-data watcher on [Fly.io](https://fly.io) instead of a homelab
box. It's a **worker** app — no web server, no ports — a single machine looping
`monohunter watch-loop` (auto-detect the newest TESS sector → scan a resumable cycle →
prune corrupt cached FITS → sleep → repeat), with all state and outputs on a persistent
volume at `/data`.

Everything is pre-wired in [`fly.toml`](../fly.toml); it builds from the repo
[`Dockerfile`](../Dockerfile).

## Prerequisites

- A Fly.io account and `flyctl` installed (`https://fly.io/docs/flyctl/install/`), then
  `fly auth login`.
- This repository checked out locally (Fly builds the image from source).

## One-time setup

```bash
# 1. Pick a unique app name + a region near you, then create the app WITHOUT deploying.
#    (Or edit `app` and `primary_region` in fly.toml first and run `fly launch --copy-config`.)
fly apps create monohunter-watcher            # name must be globally unique

# 2. Create the persistent volume the watcher writes to (same name as fly.toml's mount).
#    Match the region to primary_region. 3 GB holds state + a working FITS cache.
fly volumes create monohunter_data --size 3 --region iad --app monohunter-watcher
```

## Deploy

```bash
fly deploy --app monohunter-watcher
```

Fly builds the image, attaches the volume at `/data`, and starts one machine running the
watcher. The entrypoint chowns the (root-owned) Fly volume and drops to the unprivileged
user before running — so the container still runs non-root at runtime.

Keep it to **one** machine — two would race the same sector (state dedups, but it wastes
MAST budget and is impolite to the archive):

```bash
fly scale count 1 --app monohunter-watcher
```

## Operate

```bash
fly logs --app monohunter-watcher            # follow the watcher (per-star progress + cycle summaries)
fly status --app monohunter-watcher          # machine + volume state
fly machine restart <id> --app monohunter-watcher   # force a fresh cycle now

# Inspect / pull results from the volume via a throwaway SSH session:
fly ssh console --app monohunter-watcher -C "ls -la /data /data/candidates"
fly ssh console --app monohunter-watcher -C "cat /data/sweep.csv" > sweep.csv
```

Candidates land in `/data/candidates`, the variability summaries in `/data/summaries`, the
per-star scan log in `/data/sweep.csv`, and resume state in `/data/watch_state.json`.

## Tuning

Edit the `watcher` process line in [`fly.toml`](../fly.toml) and re-`fly deploy`:

| Flag | Default | Meaning |
|------|---------|---------|
| `--hint` | `90` | start probing for the newest sector here — set at/below the current newest |
| `--max` | `200` | stars scanned per cycle (incremental; resumable) |
| `--workers` | `3` | parallel MAST downloads — keep modest (3–8), MAST-polite |
| `--max-hours` | `4` | per-cycle watchdog: force-exit a wedged cycle (the machine then relaunches, resuming) |
| `--sleep` | `10800` | seconds between cycles (3 h) |

The same command runs locally (`monohunter watch-loop …`) and under
[`docker-compose.yml`](../docker-compose.yml) on a homelab — Fly is just another host for it.

## Cheaper: a scheduled machine (pay per cycle, not 24/7)

The always-on machine above stays allocated (and billed) even while it sleeps between
cycles. If you don't need near-real-time freshness, run a **scheduled** machine instead:
it wakes on a schedule, runs ONE cycle, and exits — so you pay only for the few minutes
each cycle actually runs (roughly **1/5–1/8** the always-on compute cost).

Use [`fly.scheduled.toml`](../fly.scheduled.toml) (runs `watch-loop --cycles 1`, which
scans one resumable cycle, prunes corrupt FITS, then exits; `restart = "no"` so Fly
doesn't relaunch it into a 24/7 loop). fly.toml has no schedule field — set it on the
machine after deploy:

```bash
fly deploy -c fly.scheduled.toml --app monohunter-watcher
fly machine list --app monohunter-watcher                 # copy the machine id
fly machine update <id> --schedule hourly --app monohunter-watcher
```

Fly's schedule presets are `hourly | daily | weekly | monthly`. `hourly` at `--max 200`
(~200 stars/hr) roughly matches throughput; use `daily` for a lighter, cheaper touch. The
`--max-hours 0.75` cap keeps a wedged cycle from overlapping the next hourly trigger. State
persists on the same volume, so cycles pick up where the last left off.

To switch back to always-on, deploy the default config again: `fly deploy -c fly.toml`.

## Costs & housekeeping

- One `shared-cpu-1x` / 1 GB machine plus a small volume is inexpensive, but **not free** —
  it runs continuously. Stop it any time with `fly scale count 0` (state persists on the
  volume) and resume with `fly scale count 1`.
- The FITS cache grows over time. `watch-loop` prunes *corrupt* stubs each cycle, but good
  downloads accumulate; if the volume fills, extend it (`fly volumes extend <id> --size N`)
  or clear the cache via `fly ssh console -C "rm -rf /data/.cache/lightkurve/mastDownload"`.

## Teardown

```bash
fly apps destroy monohunter-watcher          # removes the app + its machines
fly volumes list --app monohunter-watcher    # then destroy the volume if it lingers
```
