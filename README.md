# monohunter

Find single long-period **mono-transits** in public TESS light curves — the
single-transit events that periodic pipelines (SPOC/QLP, which fold on a period)
structurally under-find. Built so many people can each search under-covered
targets and combine machine-readable finds.

Status: early. Detection core (P1) done and tested; CLI + packaging in progress.

## Why

Automated TESS pipelines run periodic searches (BLS/TLS) over every target.
A single transit has no period to fold on, so those searches miss it. Real
long-period planets have been co-discovered exactly here (e.g. TOI-2180 b, found
from one ~24-hour transit). monohunter targets that gap.

## How it works

```
fetch (dedup sectors, prefer 2-min, stream) ->
detrend (wotan, window >> transit or the dip gets eaten) ->
detect (matched-filter box scan, non-periodic) ->
FindRecord (versioned + validated JSON)  ->  candidates/
```

The `Detector` interface is a seam: v1 is a matched-filter box scan; a
GP-based detector (`nuance`) plugs in later without touching the pipeline.
The versioned `FindRecord` JSON is the contract a future aggregation server
consumes.

## Reuse, not reinvention

Stands on [lightkurve](https://docs.lightkurve.org),
[wotan](https://github.com/hippke/wotan), scipy, and astroquery. monohunter is
orchestration + the single-transit gap + result aggregation, not a new detection
engine.

## Dev

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
pytest -q
```

## Contributing

Found a candidate, or want to improve the detector? See
[CONTRIBUTING.md](CONTRIBUTING.md). Candidate submissions go to
[`contributions/`](contributions/) via the
[candidate PR template](https://github.com/Rinkia/monohunter/compare?template=candidate.md).

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
