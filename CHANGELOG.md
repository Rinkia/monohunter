# Changelog

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
