# monohunter

Find single long-period **mono-transits** in public TESS light curves — the
single-transit events that periodic pipelines (SPOC/QLP, which fold on a period)
structurally under-find. Built so many people can each search under-covered
targets and combine machine-readable finds.

[![PyPI](https://img.shields.io/pypi/v/monohunter)](https://pypi.org/project/monohunter/)

## Why

Automated TESS pipelines run periodic searches (BLS/TLS) over every target.
A single transit has no period to fold on, so those searches miss it. Real
long-period planets have been co-discovered exactly here (e.g. TOI-2180 b, found
from one ~24-hour transit). monohunter targets that gap.

## Install

```bash
pip install monohunter
```

Python 3.10+. Pulls in lightkurve, wotan, astroquery, scipy, matplotlib. The
ASAS-SN ground cross-check needs one extra: `pip install monohunter[ground]`.

## Usage

Search one target by its TESS Input Catalog (TIC) id:

```bash
monohunter run --tic 298663873
```

This searches every available sector, and for each candidate writes a JSON
find-record + a diagnostic PNG into `candidates/`. Example (TOI-2180, the
canonical mono-transit — restrict to its sector to keep it quick):

```bash
monohunter run --tic 298663873 --sectors 19
# S19: depth=4.09ppt dur=24h SNR=39.4  [known TOI-2180.01] -> candidates/tic298663873_s19.json
```

### Options

| Flag | Default | Meaning |
|------|---------|---------|
| `--tic <id>` | required | TESS Input Catalog id to search |
| `--sectors <n...>` | all | restrict to specific sector numbers (faster) |
| `--window <days>` | `3.0` | detrend window; must be **several × the transit duration** or flattening eats the dip |
| `--outdir <path>` | `candidates` | where JSON + PNG are written |
| `--no-plot` | off | skip PNG generation |
| `--ffi` | off | extract from the Full-Frame Images via TESScut — reaches stars with **no** pre-made SPOC/QLP light curve |

### Reading a result

Each candidate is one JSON file:

```json
{
  "schema_version": 6,
  "tic": 298663873,
  "sector": 19,
  "cadence_s": 120,
  "event_time_btjd": 1830.77,
  "depth_ppt": 4.09,
  "duration_hr": 23.8,
  "ingress_hr": 2.29,
  "snr": 39.4,
  "tool_version": "0.2.0",
  "known_toi_match": true,
  "known_toi_id": "TOI-2180.01",
  "likely_eb": false,
  "period_constrained": true,
  "p_best_d": 856.0,
  "p_lo_d": 396.0,
  "p_hi_d": 1946.0,
  "next_window_btjd": [3200.0, 3245.0, 3290.0],
  "n_sectors_observed": 1,
  "recurring_dip": false,
  "measured_period_d": null,
  "plot_path": "candidates/tic298663873_s19.png"
}
```

| Field | Meaning |
|-------|---------|
| `event_time_btjd` | dip center, TESS Barycentric Julian Date |
| `depth_ppt` | transit depth (parts per thousand), trapezoid flat-bottom |
| `duration_hr` | total transit duration (first-to-last contact) |
| `ingress_hr` | ingress/egress time from the trapezoid fit (`null` if uncharacterized) |
| `snr` | detection signal-to-noise; the tool reports candidates at SNR ≥ 7 |
| `known_toi_match` / `known_toi_id` | whether the target is an existing TESS Object of Interest |
| `likely_eb` | too deep / V-shaped for a planet — flagged as a likely eclipsing binary (labelled, not rejected) |
| `p_best_d`, `p_lo_d`, `p_hi_d` | single-transit period estimate + range (see Next-transit ephemeris) |
| `n_sectors_observed`, `recurring_dip` | multi-sector context: dips in >1 sector flag a periodic/variable star |
| `measured_period_d` | exact period fitted from multiple transit times, when the target recurs across sectors |

**Always look at the PNG.** SNR alone lies — confirm the marked dip is a real,
centered transit, not a sector-edge ramp, a data gap, or a single bad cadence.
Re-run with a different `--window`; a real dip survives, an artifact moves or
vanishes. A `known_toi_match: false` is the interesting case (potentially
unsearched); `true` still validates the tool.

**A candidate is not a discovery.** It means a human thinks the dip is real.
Confirming a planet needs follow-up (radial velocity, more transits) beyond this
tool.

## How it works

```
fetch      search TESS, dedup sectors (prefer 2-min), quality-mask (hard),
           stream one sector at a time
   |
detrend    wotan biweight; window must be >> transit or the dip is flattened away
   |
detect     matched-filter box scan (non-periodic — finds a SINGLE transit),
           red-noise-aware SNR + 7 false-positive guards (edge / gap / scatter /
           momentum-dump ramps)
   |
characterize   trapezoid fit -> true depth, duration, ingress; EB flag
   |
cross-match    flag known TESS Objects of Interest (NASA Exoplanet Archive)
   |
ephemeris      period + next-transit window (single-transit, or exact from
           multiple sectors); multi-sector recurrence flag
   |
FindRecord     versioned + validated JSON  ->  candidates/
```

The `Detector` interface is a seam: v1 is the box scan; a GP-based detector
(`nuance`) can plug in later without touching the pipeline. The versioned
`FindRecord` JSON is the contract a future aggregation server consumes.

## Reuse, not reinvention

Stands on [lightkurve](https://docs.lightkurve.org),
[wotan](https://github.com/hippke/wotan), scipy, and astroquery. monohunter is
orchestration + the single-transit gap + result aggregation, not a new detection
engine.

## Fresh-data watcher (be first)

Institutional pipelines take weeks-to-months to vet a new TESS sector. Run the
watcher on a schedule and you process a sector within hours of its release — and
a single transit you flag comes with a next-transit window (see below) an
observer can still act on.

```bash
monohunter watch --sector 90 --max 100 --out watch_out --state watch_state.json
```

Each run scans the next `--max` un-processed targets of the sector and prints any
not-yet-known candidates. It's **resumable**: state tracks which TICs are done,
so scheduled runs continue where the last stopped and a crash loses nothing.

Schedule it to keep chewing through the sector:

```bash
# Linux/macOS cron — every 2 hours
0 */2 * * * cd /path/to/monohunter && monohunter watch --sector 90 --max 200

# Windows: Task Scheduler → run the same command on a trigger
```

Point `--sector` at the newest released sector. Candidates land in `watch_out/`;
vet each with `monohunter run --tic <id> --sectors <N>` to get its PNG, then
submit the good ones (see Contributing).

## Next-transit ephemeris

When a candidate's target has a catalog stellar density, monohunter estimates the
period from the transit duration and predicts when the next transit could occur:

```
S19: depth=4.09ppt dur=24h SNR=39.4  [known TOI-2180.01]
    P~856d (396-1946d, P_min 15d), next transit ~2027-08-07
```

Single-transit periods are inherently uncertain (a range, not a precise value) —
the output is a targeting window for follow-up, not a confirmed ephemeris. If the
stellar density is missing or too uncertain, monohunter reports the period as
unconstrained rather than guessing.

**Multi-sector sharpens both.** A target that dips in more than one sector is
flagged `recurring_dip` (periodic/variable, not a clean mono-transit), and once
it transits in ≥3 sectors the exact period is fitted from the transit times
(`measured_period_d`) — vastly tighter than the single-transit range.

## More commands

**Anomaly detection** — flares (brightenings) and dippers (aperiodic multi-dip
young stars), on the same light curves:

```bash
monohunter anomaly --tic 441420236     # AU Mic: flares detected
```

**FFI reach** — extract from the Full-Frame Images to search stars with no
pre-made light curve. One target (`run --ffi`), or a whole cutout at once:

```bash
monohunter ffi-batch --tic <center> --sector 14   # every catalog star in one cutout
```

**Ground cross-check** — is a candidate's host quiet over years, or a variable
star / eclipsing binary? Confirm against ZTF or ASAS-SN:

```bash
monohunter ground --tic 198382838 --survey ztf     # or --survey asassn
```

**Faster sweeps** — `watch` (and the sweep scripts) take `--workers N` for
parallel MAST downloads (network-bound; keep it modest, 4-8).

**Crowd vetting + triage** — turn a pile of candidates into a labelled queue,
then rank future survivors by how much they deserve a human's eyes:

```bash
monohunter vet --candidates candidates --out _vet      # static page: PNGs + label buttons
monohunter triage-train --labels labels/seed_labels.csv --sweeps sweeps
monohunter triage --candidates candidates              # ranks by P(worth vetting)
```

The vetting page exports labels as JSON; those labels train the triage model,
which then puts the real finds at the top of the next sweep's queue.

## Community leaderboard (swarm)

Submitted candidates are aggregated into one ranked list — deduped by
`(tic, sector)`, ranked by novelty (not a known TOI), cross-submitter agreement,
and SNR. Live at **https://rinkia.github.io/monohunter/**, rebuilt automatically
on every merged contribution.

Build it yourself from a `contributions/` tree:

```bash
monohunter aggregate --contributions contributions --out _site
# writes _site/index.html + _site/leaderboard.json
```

This is phase 1 of the swarm: pure aggregation over the PR flow, no backend. A
live coordination server (handing out targets so no two people search the same
star) is a later increment, worth building only once there's real contention.

One-time to publish: repo **Settings → Pages → Source = "GitHub Actions"**
(the `pages.yml` workflow does the rest).

## Contributing

Found a candidate, or want to improve the detector? See
[CONTRIBUTING.md](CONTRIBUTING.md). Candidate submissions go to
[`contributions/<username>/`](contributions/) via the
[candidate PR template](https://github.com/Rinkia/monohunter/compare?template=candidate.md).

## Development

```bash
git clone https://github.com/Rinkia/monohunter
cd monohunter
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
pytest -q                 # fast, offline unit tests
pytest --runslow          # + live real-data regression (hits MAST)
```

## Releasing to PyPI

CI (`.github/workflows/ci.yml`) runs the tests on every push. Publishing
(`.github/workflows/release.yml`) fires on a version tag and uses **Trusted
Publishing** — no token in GitHub.

One-time PyPI setup (before the first release):

1. On PyPI: Account → Publishing → **Add a pending publisher**:
   - PyPI project name: `monohunter`
   - Owner: `Rinkia`  ·  Repository: `monohunter`
   - Workflow: `release.yml`  ·  Environment: leave blank (Any)
2. (Optional) For a manual approval gate, create a GitHub Environment, set it
   as the pending-publisher Environment, and add `environment: <name>` back to
   the `publish` job in `release.yml`.

Then release:

```bash
# bump version in pyproject.toml + monohunter/__init__.py, update CHANGELOG.md
git tag vX.Y.Z
git push origin vX.Y.Z
```

## License

MIT.
