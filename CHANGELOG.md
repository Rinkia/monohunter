# Changelog

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
