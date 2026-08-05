# contributions/

Community-submitted mono-transit candidates. One JSON find-record per file,
named `tic<TIC>_s<SECTOR>.json` (exactly what `monohunter run` writes).

**This is a candidate list, not a discovery list.** A record here means "a
human looked at the light curve and thinks the dip is real." Confirming a planet
needs follow-up (radial velocity, more transits) that this repo does not do.

How to add yours: see [CONTRIBUTING.md](../CONTRIBUTING.md) in the repo root.

Records are validated against the `FindRecord` schema (`schema_version`, TIC,
sector, depth, duration, SNR, ...). A future aggregation step will dedupe by
`(tic, sector)` and rank by cross-submitter agreement + novelty.
