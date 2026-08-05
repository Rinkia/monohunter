# contributions/

Community-submitted mono-transit candidates, one JSON find-record per file
under your own submitter folder:

```
contributions/<your-github-username>/tic<TIC>_s<SECTOR>.json
```

The filename is exactly what `monohunter run` writes; the username subfolder is
what lets the leaderboard count independent submitters per candidate.

**This is a candidate list, not a discovery list.** A record here means "a
human looked at the light curve and thinks the dip is real." Confirming a planet
needs follow-up (radial velocity, more transits) that this repo does not do.

How to add yours: see [CONTRIBUTING.md](../CONTRIBUTING.md) in the repo root.

Records are validated against the `FindRecord` schema (`schema_version`, TIC,
sector, depth, duration, SNR, ...). A future aggregation step will dedupe by
`(tic, sector)` and rank by cross-submitter agreement + novelty.
