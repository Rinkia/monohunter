"""Per-star stellar summary — more science per download.

A sweep is MAST-download-bound; each downloaded light curve currently feeds only
the transit scan and is then discarded. The same bytes hold much more. summarize()
computes, cheaply and offline, a compact stellar summary per star — a rotation /
variability / flare / dipper catalog useful far beyond single-transit hunting.

KEY: rotation lives on days-to-weeks timescales that the transit detrend (wotan,
3-day window) WIPES OUT. So rotation and variability are measured on the RAW
normalized flux; flares and dippers on the transit-flattened flux. Both already
exist per download — nothing extra is fetched.

    raw normalized flux -> Lomb-Scargle rotation + variability amplitude
    flattened flux       -> flare count + dipper flag (reuses anomaly.py)
                         -> one StellarSummary row per star

summarize / rotation_period are pure and unit-tested; run_summary is the network
orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, ConfigDict

from . import __version__

SUMMARY_SCHEMA_VERSION = 2  # v2: subclass (pulsator/rotator/eclipsing refinement)

# Rotation search window and the LS power a peak must clear to be called real.
ROT_MIN_PERIOD_D = 0.1
ROT_MAX_PERIOD_D = 30.0
ROT_MIN_POWER = 0.1
# TESS instrumental periods that masquerade as rotation: the ~13.7 d spacecraft
# orbit (momentum dumps / downlinks) and the 1 d ground alias. A peak near these,
# or longer than most of the baseline, is flagged systematic (no rotation period).
TESS_SYSTEMATIC_PERIODS_D = (13.7, 1.0)
SYSTEMATIC_TOL_FRAC = 0.05
# Classification thresholds.
FLARE_CLASS_MIN = 3
VARIABLE_AMPLITUDE_PPT = 5.0   # >0.5% robust amplitude -> "variable"
# Subclass refinement (periodogram harmonics + eclipse shape). A pure sinusoid
# (pulsator) has almost no 2nd harmonic; a spot-modulated rotator's non-sinusoidal
# shape raises A2/A1; a >=2-eclipse curve is eclipsing. Above this A2/A1 ratio the
# light curve is too non-sinusoidal to be a coherent pulsator -> rotator.
PULSATOR_HARMONIC_MAX = 0.25
# Short periods that are almost pure sinusoids are pulsators (delta Scuti / gamma
# Dor regime) even if slightly above the harmonic cutoff; spot rotation rarely
# sits this fast this cleanly.
PULSATOR_MAX_PERIOD_D = 2.0


def rotation_period(time, raw_flux):
    """Dominant Lomb-Scargle period of the RAW (un-transit-detrended) flux.

    Returns (period_d, power, systematic): period is None when the peak is too
    weak OR is an instrumental period (systematic=True); power is always the peak
    LS power so the caller can judge.
    """
    from astropy.timeseries import LombScargle

    t = np.asarray(time, dtype=float)
    f = np.asarray(raw_flux, dtype=float)
    good = np.isfinite(t) & np.isfinite(f)
    t, f = t[good], f[good]
    if t.size < 50:
        return None, 0.0, False
    baseline = float(t.max() - t.min())
    if baseline <= 0:
        return None, 0.0, False

    freq, power = LombScargle(t, f).autopower(
        minimum_frequency=1.0 / min(ROT_MAX_PERIOD_D, baseline),
        maximum_frequency=1.0 / ROT_MIN_PERIOD_D,
        samples_per_peak=5,
    )
    if power.size == 0:
        return None, 0.0, False
    i = int(np.argmax(power))
    period = float(1.0 / freq[i])
    peak = float(power[i])
    if peak < ROT_MIN_POWER:
        return None, peak, False

    systematic = period > 0.9 * baseline or any(
        abs(period - p) <= SYSTEMATIC_TOL_FRAC * p for p in TESS_SYSTEMATIC_PERIODS_D
    )
    if systematic:
        return None, peak, True
    return period, peak, False


def harmonic_ratio(time, flux, period) -> float:
    """A2/A1: amplitude of the 2nd harmonic over the fundamental at `period`.

    Least-squares fit of {1, sin f, cos f, sin 2f, cos 2f} (f = 2π/period). A pure
    sinusoid (pulsation) has A2≈0; a non-sinusoidal spot / eclipse shape lifts A2.
    Returns 0.0 when the fit is degenerate. Pure.
    """
    t = np.asarray(time, dtype=float)
    f = np.asarray(flux, dtype=float)
    good = np.isfinite(t) & np.isfinite(f)
    t, f = t[good], f[good]
    if t.size < 20 or not (period and period > 0):
        return 0.0
    w = 2 * np.pi / period
    design = np.vstack([
        np.ones(t.size), np.sin(w * t), np.cos(w * t), np.sin(2 * w * t), np.cos(2 * w * t)
    ]).T
    coef, *_ = np.linalg.lstsq(design, f, rcond=None)
    a1 = float(np.hypot(coef[1], coef[2]))
    a2 = float(np.hypot(coef[3], coef[4]))
    return a2 / a1 if a1 > 0 else 0.0


def _subclass(base_class, period, time, raw_flux, flat_flux) -> str:
    """Refine a variable star: eclipsing / pulsator / rotator. Pure.

    Eclipses (>=2 deep dips) win outright. Otherwise a periodic star splits by
    sinusoid purity: near-pure sine -> pulsator, non-sinusoidal -> rotator.
    Non-periodic classes (quiet/flaring/dipper/variable) are returned unchanged.
    """
    from .eb import eclipse_times

    if len(eclipse_times(time, flat_flux)) >= 2:
        return "eclipsing"
    if base_class != "rotator" or period is None:
        return base_class
    r = harmonic_ratio(time, raw_flux, period)
    if r < PULSATOR_HARMONIC_MAX or period < PULSATOR_MAX_PERIOD_D:
        return "pulsator"
    return "rotator"


@dataclass(frozen=True)
class SummaryResult:
    var_amplitude_ppt: float
    rotation_period_d: float | None
    rotation_power: float
    rotation_systematic: bool
    n_flares: int
    is_dipper: bool
    n_dips: int
    var_class: str            # quiet | rotator | variable | flaring | dipper
    subclass: str = "quiet"   # eclipsing | pulsator | rotator | (echoes var_class otherwise)


def _classify(period, amp_ppt, n_flares, is_dipper) -> str:
    if is_dipper:
        return "dipper"
    if n_flares >= FLARE_CLASS_MIN:
        return "flaring"
    if period is not None:
        return "rotator"
    if amp_ppt > VARIABLE_AMPLITUDE_PPT:
        return "variable"
    return "quiet"


def summarize(time, raw_flux, flat_flux) -> SummaryResult:
    """One stellar summary. Rotation+variability on RAW flux; flares+dippers on
    the transit-flattened flux. Pure."""
    from .anomaly import find_dippers, find_flares
    from .ground import variability

    amp_ppt = variability(time, raw_flux).frac_amplitude * 1000.0
    period, power, systematic = rotation_period(time, raw_flux)
    n_flares = len(find_flares(time, flat_flux))
    dip = find_dippers(time, flat_flux)
    var_class = _classify(period, amp_ppt, n_flares, dip.is_dipper)
    return SummaryResult(
        var_amplitude_ppt=float(amp_ppt),
        rotation_period_d=period,
        rotation_power=float(power),
        rotation_systematic=systematic,
        n_flares=int(n_flares),
        is_dipper=bool(dip.is_dipper),
        n_dips=int(dip.n_dips),
        var_class=var_class,
        subclass=_subclass(var_class, period, time, raw_flux, flat_flux),
    )


class StellarSummary(BaseModel):
    """Serializable per-star summary — a catalog row."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SUMMARY_SCHEMA_VERSION
    tic: int
    sector: int
    cadence_s: int
    n_epochs: int
    var_amplitude_ppt: float
    rotation_period_d: float | None = None
    rotation_power: float = 0.0
    rotation_systematic: bool = False
    n_flares: int = 0
    is_dipper: bool = False
    n_dips: int = 0
    var_class: str = "quiet"
    subclass: str = "quiet"
    tool_version: str = __version__

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)


def load_summaries(summaries_dir: str, workers: int = 16) -> list[dict]:
    """Read every summary JSON in a dir as a plain dict, in parallel.

    Building a catalog means opening thousands of tiny files; that's I/O-bound
    (cold-disk per-file open dominates, ~45 ms/file on Windows), so parallel reads
    overlap the latency. No pydantic — these are trusted, self-written records, so
    validating each on the way to a CSV is wasted work.
    """
    import glob
    import json as _json
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    files = sorted(glob.glob(str(Path(summaries_dir) / "*.json")))

    def _one(path: str) -> dict | None:
        try:
            with open(path, encoding="utf-8") as fh:
                return _json.load(fh)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [r for r in pool.map(_one, files) if r is not None]


def write_catalog_csv(rows: list[dict], out_path: str) -> int:
    """Write summary dicts to a CSV with the canonical StellarSummary columns."""
    import csv as _csv

    cols = list(StellarSummary.model_fields.keys())
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def run_summary(tic: int, sectors: list[int] | None = None, window_length: float | None = None):
    """Fetch + summarize each sector of a TIC. Returns list[StellarSummary].
    Network — mirrors pipeline.run_target's fetch loop."""
    from .detrend import DEFAULT_WINDOW_D, flatten
    from .fetch import cadence_seconds, download_lightcurve, iter_lightcurves, search_tess

    win = window_length if window_length is not None else DEFAULT_WINDOW_D
    sr, rows = search_tess(tic)
    if sectors is not None:
        wanted = set(sectors)
        rows = [r for r in rows if int(r["sector"]) in wanted]

    def download(row):
        return download_lightcurve(sr, row["_index"])

    out: list[StellarSummary] = []
    for row, lc in iter_lightcurves(rows, download):
        time = np.asarray(lc.time.value if hasattr(lc.time, "value") else lc.time, dtype=float)
        raw = np.asarray(getattr(lc.flux, "value", lc.flux), dtype=float)   # already normalized
        cadence_s = int(row["cadence_s"]) or cadence_seconds(time)
        flat, _ = flatten(time, raw, window_length=win)
        res = summarize(time, raw, flat)
        out.append(StellarSummary(
            tic=int(tic), sector=int(row["sector"]), cadence_s=cadence_s,
            n_epochs=int(np.isfinite(raw).sum()),
            var_amplitude_ppt=res.var_amplitude_ppt,
            rotation_period_d=res.rotation_period_d, rotation_power=res.rotation_power,
            rotation_systematic=res.rotation_systematic, n_flares=res.n_flares,
            is_dipper=res.is_dipper, n_dips=res.n_dips, var_class=res.var_class,
            subclass=res.subclass,
        ))
    return out
