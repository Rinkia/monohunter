# Changelog

## 0.7.0

The long-run safety-net release. Three layers now guard every long / network run from
silent stalls:

- **Per-read timeout (existing):** `socket.setdefaulttimeout(180)` caps every MAST/IRSA
  read, so no single call hangs forever.
- **Per-step progress + stall warning (new):** a shared `ProgressReporter` prints one
  line per star with elapsed/ETA and flags a step slower than `--slow-warn` seconds — a
  stall short of the hard timeout is now visible instead of a silent freeze. Wired into
  `watch` (per-star, previously end-only), `completeness --sample`, and
  `summarize --from-catalog` (previously a single line for the whole batch).
- **Wall-clock watchdog (generalized):** the `watch` force-exit watchdog moved to a
  shared `Watchdog` that now also **soft-warns at 80%** of the cap before firing, and is
  offered to `summarize --from-catalog --max-hours` (resumable, so a hard exit loses
  nothing). Force-exit is intentionally NOT added to `completeness` (it would discard the
  in-memory survey grid); it relies on the socket timeout + per-star stall warning.

New flags: `--slow-warn S` on `watch` / `completeness` / `summarize`; `--max-hours H` on
`summarize --from-catalog`.

## 0.6.2

- **`completeness --sample` now prints per-star progress** (`[i/N] TIC … used/skipped/
  failed`) via a new `progress` callback on `run_completeness_sample`. The injection-
  recovery survey is compute-heavy (stars × grid cells × injections full detect runs) and
  was previously silent for its whole runtime; the progress line makes a long run
  watchable and a stall visible.
- **First published survey-sensitivity curve** — Sector 18 completeness (mean over 10
  quiet stars) is committed as `completeness_s18.png` and embedded in the README: ~50%
  complete at 2–3 ppt for long transits, ~90% by 5 ppt.

## 0.6.1

- **`completeness --plot PNG`** renders the depth × duration recovery-fraction heatmap
  — the publishable survey-sensitivity figure — alongside the existing text grid. Works
  for both single-star and `--sample` survey mode. (`observe`, the other actionability
  gate, shipped in 0.5.2.)

## 0.6.0

Two new data sources for the discovery frontier.

### Novelty — Gaia DR3 as a second source
- **`novelty` now cross-checks Gaia DR3 variability** alongside VSX. A candidate is
  called NOVEL only when it is unknown to BOTH catalogs; a hit in Gaia's
  variability-classifier table (`I/358/vclassre`, which holds only variable sources)
  reports the class (e.g. `RR`, `ECL`). Gaia is complementary, not a superset — it
  catches faint variables VSX lacks, while VSX still catches very bright stars Gaia's
  classifier excludes. `novelty.gaia_variability` / `gaia_novelty` are the new entry
  points; degrades to "unknown" offline like the VSX path.

### FFI — non-SPOC star-pool enumeration
- **`monohunter ffi-pool`** enumerates the FFI-only star pool for a sky region of a
  sector: every TIC in a cone (`--tic`/`--ra`/`--dec` + `--radius`, `--tmag-max`) that is
  NOT in the sector's 2-min SPOC pool — the stars a normal sweep never reaches. Writes a
  TIC list.
- **`watch --target-pool FILE`** scans an explicit TIC list instead of the SPOC pool, so
  `watch --ffi --target-pool ffi_pool.txt` runs a true FFI sweep. `--dry-run` reports
  against the supplied pool too. (Enumeration is over-inclusive — a region star isn't
  guaranteed on-silicon; misses yield no cutout and are skipped. A precise footprint
  check is the upgrade.)

## 0.5.2

The follow-up-planning release.

### Observability
- **`monohunter observe`** — turn a predicted next-transit window into concrete
  "target up + sky dark" clock-time intervals for an observer's latitude/longitude, so
  an amateur knows whether and *when* to point. Takes `--ra/--dec` or a `--tic`
  (RA/Dec fetched from MAST), and a window from `--start/--end` (ISO UTC or raw BTJD) or
  straight from a candidate record's next-transit window via `--record`. Tunable
  `--min-alt` and `--sun-alt` (−18 astronomical / −12 nautical). Astropy only — no new
  dependency. Reports each dark-and-up interval in UTC plus the total observable hours.

## 0.5.1

Quality-of-life CLI release (no breaking API change):
- **`summarize --from-catalog CSV`** — batch-resummarize every `(tic,sector)` in a
  catalog CSV, in parallel (`--workers`). Repopulates fields the CSV can't hold (e.g.
  `subclass`) from the light curves. Resumable when `--outdir` is a directory
  (already-written stars skipped); per-star failures are counted, not fatal.
- **`monohunter clean-cache`** — delete truncated partial FITS (exact-size download
  stubs) from the lightkurve cache in one command; a corrupt stub otherwise raises on
  read and can wedge a sweep. `--dry-run` lists first; `--cache-dir`/`--size` override.
- **`run --dry-run`** lists the sectors available for a TIC, and **`watch --dry-run`**
  reports the sector's target-pool size, how many are done, and how many this run would
  scan — a sanity check before a long sweep, no download.
- **`--summaries …​.jsonl`** — a summaries path ending in `.jsonl` appends one line per
  star to a single file instead of a directory of thousands of tiny JSONs (kills the
  cold-disk per-file open cost when building a catalog). `catalog`/`load_summaries` read
  a `.jsonl` file or a dir containing one.
- **`triage --top N`** — show only the N highest-ranked candidates (the vetting short-list).

## 0.5.0

The always-on deployment release.

### Deployment
- **Docker image + GHCR publish** — `Dockerfile` (python:3.12-slim, `HOME`+`WORKDIR`
  = `/data` so caches and outputs share one volume, `MPLBACKEND=Agg`). A `docker.yml`
  workflow builds and pushes `ghcr.io/rinkia/monohunter` (`:X.Y.Z` + `:latest`) on
  every `v*` tag.
- **24/7 homelab watcher** — `docker-compose.yml` runs a `restart:always` service that
  loops `monohunter watch` on the newest sector (auto-detected), resumable and
  self-healing (errored stars retry next cycle, corrupt FITS pruned), persisting
  everything in `./data`. Tunable via env (`HINT`/`MAX`/`WORKERS`/`SLEEP`/`MAXHOURS`).

### Reliability
- **`watch --max-hours` safety net** — a daemon-timer watchdog force-exits a run that
  wedges on a hung MAST socket a worker thread can't kill. State is saved per star, so
  nothing is lost and the run resumes; hitting the cap is itself the "wedged" signal.
  Disarmed on clean completion. Wired into the compose watcher (default 4h) so a hung
  cycle self-heals via `restart:always`.

### Data
- **Sector 18 published** — 4054-star variability catalog (875 rotators, 492 variable,
  214 flaring, 32 dipper; subclass populated). 4 vetted S18 candidates promoted to the
  leaderboard incl. **TIC 22945095** (novel 2.7% single transit, P~12.5d, next transit
  ~2026-08-23 — tighter follow-up window than TIC 400048097) and NY Cep (`eb` recovered
  P=15.270d vs VSX 15.276d).
- **Triage sharper** — 9 S18 labels retrain the model to 96% leave-one-out;
  `log_baseline_scatter` gains a real negative weight now that training rows carry the
  v7 edge_gap+scatter columns, demoting the noisy-star FP class.

## 0.4.0

The reproducibility + auto-vet release.

### Sweeps
- **`watch` is the sweep tool** — `--csv-log` writes a provenance row per star
  (`none`/`novel`/`error`), matching the old scratchpad-sweep schema. A full
  sector sweep is now one reproducible command instead of a rebuilt script.
- **Errored stars auto-retry:** a transient failure (usually MAST) is logged and
  left un-processed, so re-running the same command retries only the failures — no
  manual clean-and-relaunch.

### Triage (FP auto-vet)
- **Generalized off the S14 hardcode (schema v7):** records now carry
  `edge_gap_dist_d` (distance to the nearest sector edge/gap) and
  `baseline_scatter_ppt` (faint/noisy-star tell), computed from the light curve.
  Triage uses `edge_gap_dist_d` in place of the S14-hardcoded systematic times, so
  it ranks survivors on **any** sector. Old records fall back to the S14 proximity,
  so the 92% leave-one-out model is unchanged.
- **`triage --min-prob P`** hides the sub-threshold junk tail (auto-cut).

### Ephemeris
- **Gaia DR3 stellar-density fallback:** when the TIC has no usable density, derive
  ρ\* = 3g/(4πGR) from Gaia DR3 `logg_gspphot` + `radius_gspphot` (no mass-radius
  assumption; validated against the Sun). Unblocks the period + next-transit window
  for bright, uncatalogued hosts — exactly the best mono-transit targets. Live: TIC
  400048097 went from period-unconstrained to P≈29 d with a next-transit window.

### Eclipsing binaries
- **Cross-sector periods:** `run_eb` now also stitches eclipse times across all
  sectors, so a target with one eclipse per sector — unrecoverable in any single
  sector — gets a period from the combined primaries (the EB analogue of
  `measured_period_d`). Flags the possible integer alias for sparse epochs.

### Adoption
- **Zero-install Colab quickstart** (`notebooks/monohunter_quickstart.ipynb`) with an
  Open-in-Colab badge — run it in a browser, no Python setup.
- **Issue-form candidate submission** (`.github/ISSUE_TEMPLATE/candidate.yml`) so
  non-coders can submit a vetted candidate without git.

## 0.3.2

### Fixed
- **Subclass dropped on the sweep path:** `pipeline._write_summary` (used by
  `run` and sweeps) computed the v0.3.0 sub-classification but never wrote it to
  the summary, so every swept star fell back to `subclass="quiet"`. Now carried
  through; regression-tested.

## 0.3.1

### Fixed
- **Eclipse fragmentation in `eb`:** a shallow/jagged eclipse that briefly rose
  back above the detection threshold was split into several runs, over-counting
  one eclipse as many (TIC 120239458 S16 reported 5 eclipses for a real 2). Merge
  runs whose minima fall within 0.3 d, keeping the deepest.

## 0.3.0

More population science from the same downloads: orbital periods for eclipsing
binaries, a rotation-distribution figure, and a refined variable sub-classification.

### Eclipsing binaries
- **`eb` command + `monohunter.eb`:** recover an EB orbital period from in-sector
  eclipses. Finds eclipse times (deep contiguous dips in the flattened flux),
  splits primary/secondary by depth, and reuses `ephemeris.period_from_transits`
  on the PRIMARY times only — their spacing is exactly one orbit. A lone
  primary+secondary pair is left unrecoverable (an eccentric secondary sits at an
  unknown phase, so the gap is not a period fraction): never a confident wrong
  period. Verified against TIC 271763138 (VSX P=44.8d eccentric EA).

### Rotation
- **`rotation-plot` command + `monohunter.rotation_plot`:** a population figure from
  a catalog CSV — rotation-period distribution (log histogram) + period-amplitude
  relation. Filters to real rotators (finite period, non-systematic).

### Variable classification
- **Sub-classification (`subclass`, summary schema v2):** splits variables into
  `eclipsing` (>=2 eclipse-shaped dips), `pulsator` (near-pure sinusoid, low 2nd-
  harmonic content), and `rotator` (non-sinusoidal spot modulation) via periodogram
  harmonics. Additive optional column; old catalogs still load.

## 0.2.0

The data-frontier + confirmation + triage release. Grows monohunter from a
single-sector SPOC detector into an end-to-end discovery pipeline: reach
un-searched stars, confirm candidates across facilities, and triage survivors
with a model so human vetting goes to the real finds.

### Detection & characterization
- **Scatter-region guard (#7):** rejects the dominant residual false positive —
  a box landing beside a momentum-dump / scattered-light patch — by widening the
  upward-outlier test to the event's ~day-wide neighborhood. Data-driven, general.

### Ephemeris
- **SNR gate on ingress→b:** below SNR 15 the ingress is noise; fall back to a
  blind impact-parameter prior (wider, honest posterior).
- **Cadence-aware ingress gate:** coarse cadence smears the ingress and biases
  the period high; drop to blind-b when the ingress spans too few cadences.
  Fixes the FFI period bias (TOI-2180 1164d → 852d, matching SPOC).
- **Gap-aware p_min:** a sibling transit can hide in a data gap; p_min now
  segments the baseline instead of assuming continuous coverage.
- **Exact period from recurring transits:** when a target transits in ≥3
  sectors, fit an integer-epoch linear ephemeris (TOI-813: 83.896d vs true 83.9d).

### Multi-sector (schema v5)
- **Cross-sector validation:** dips in >1 sector flag a periodic/variable star
  (`recurring_dip`); ephemeris uses the full multi-sector baseline.

### Anomaly detection
- **Flares** (sustained positive excursions) and **dippers** (guarded aperiodic
  multi-dip stars, reusing the FP guard stack minus isolation). `monohunter anomaly`.

### Data frontier — FFI
- **Single-target FFI extraction** via TESScut (`run --ffi`, `watch --ffi`):
  reaches stars with no pre-made SPOC/QLP light curve.
- **FFI batch extraction** (`ffi-batch`): one cutout → every catalog star in it,
  with crowding-blend dedup. Batch finds flow through the full record path.

### Ground surveys
- **ZTF and ASAS-SN cross-check** (`ground`): is a candidate's host quiet over
  years, or a variable star / EB? Independent confirmation.

### Phase 3
- **Crowd vetting UI** (`vet`): static page of candidate PNGs + label buttons,
  votes exported to JSON — the label factory.
- **ML triage classifier** (`triage-train`, `triage`): ranks survivors by
  P(worth vetting) from record features. Leave-one-out accuracy 92% on the seed
  labels; improves as crowd labels accumulate.

### Records & performance
- FindRecord schema v4 → v6 (multi-sector context, measured period); all fields
  additive/optional, old records still load.
- Parallel sweeps/watch (`--workers`); graceful skip of truncated MAST downloads.

## 0.1.0

Initial release: box matched-filter detector with 6 false-positive guards +
red-noise SNR, trapezoid characterization, analytic next-transit ephemeris,
versioned find-records, community leaderboard, and a resumable fresh-sector
watcher.
