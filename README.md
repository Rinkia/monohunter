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

## License

MIT.
