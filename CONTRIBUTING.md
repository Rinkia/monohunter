# Contributing

Two ways to help: **submit candidates** (no coding), or **improve the tool** (code).

## Submit a mono-transit candidate

The whole point of monohunter: many people each search targets the big pipelines
under-cover, and combine finds. Here's the loop.

1. **Install and run** on a target (any TIC id):
   ```bash
   pip install monohunter
   monohunter run --tic 298663873
   ```
   It writes `candidates/tic<TIC>_s<SECTOR>.json` + a `.png` per candidate.

2. **Vet the PNG.** Open it. A real transit is a centered, U/V-shaped dip that
   lasts hours. Reject it if the marker sits on:
   - the **start or end of a sector** (a ramp, not a transit),
   - a **data gap** edge,
   - a **single-point spike** (one bad cadence).

   Re-run with a different `--window` (e.g. `--window 2` and `--window 5`). A
   real dip survives; a detrending artifact moves or vanishes.

3. **Submit one candidate per PR.** Put the JSON in your own submitter folder,
   `contributions/<your-github-username>/tic<TIC>_s<SECTOR>.json` (the subfolder
   is what lets the leaderboard count independent submitters per candidate).
   Open a PR using the candidate template:

   https://github.com/Rinkia/monohunter/compare?template=candidate.md

   Attach the PNG in the PR and fill the checklist. Once merged, the
   [community leaderboard](https://rinkia.github.io/monohunter/) rebuilds
   automatically — a candidate flagged by more people, not already a known TOI,
   with higher SNR, ranks higher.

**A candidate is not a discovery.** It means the dip looks real to a human.
Confirming a planet needs follow-up (radial velocity, more transits) beyond this
repo. `known_toi_match: true` is fine to submit — it validates the tool; a
`false` is the interesting case (potentially unsearched).

### What gets merged

- JSON validates against the `FindRecord` schema (the tool guarantees this).
- PNG shows a plausible, non-edge, non-gap transit.
- SNR ≥ 7.
- Filed under your own `contributions/<username>/` folder. Two people
  independently submitting the same `(tic, sector)` is good — that's consensus,
  and the leaderboard ranks it higher. Don't submit the same candidate twice
  yourself.

## Improve the tool

```bash
git clone https://github.com/Rinkia/monohunter
cd monohunter
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
pytest -q
```

Keep the tests green. New detection logic needs a test (recovery + a
noise/edge rejection). See `tests/` for the pattern.
