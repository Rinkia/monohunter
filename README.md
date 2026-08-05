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

Python 3.10+. Pulls in lightkurve, wotan, astroquery, scipy, matplotlib.

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
# S19: depth=4.09ppt dur=24h SNR=165.3  [known TOI-2180.01] -> candidates/tic298663873_s19.json
```

### Options

| Flag | Default | Meaning |
|------|---------|---------|
| `--tic <id>` | required | TESS Input Catalog id to search |
| `--sectors <n...>` | all | restrict to specific sector numbers (faster) |
| `--window <days>` | `3.0` | detrend window; must be **several × the transit duration** or flattening eats the dip |
| `--outdir <path>` | `candidates` | where JSON + PNG are written |
| `--no-plot` | off | skip PNG generation |

### Reading a result

Each candidate is one JSON file:

```json
{
  "schema_version": 2,
  "tic": 298663873,
  "sector": 19,
  "cadence_s": 120,
  "event_time_btjd": 1830.77,
  "depth_ppt": 4.09,
  "duration_hr": 23.8,
  "ingress_hr": 2.29,
  "snr": 165.3,
  "detrend_method": "biweight",
  "detrend_window_d": 3.0,
  "tool_version": "0.1.0",
  "known_toi_match": true,
  "known_toi_id": "TOI-2180.01",
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
           edge-guarded against sector-boundary ramps
   |
characterize   trapezoid fit -> true depth, duration, ingress
   |
cross-match    flag known TESS Objects of Interest (NASA Exoplanet Archive)
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
# bump version in pyproject.toml first
git tag v0.1.0
git push --tags
```

## License

MIT.
