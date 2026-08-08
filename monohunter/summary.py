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

SUMMARY_SCHEMA_VERSION = 1

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
    return SummaryResult(
        var_amplitude_ppt=float(amp_ppt),
        rotation_period_d=period,
        rotation_power=float(power),
        rotation_systematic=systematic,
        n_flares=int(n_flares),
        is_dipper=bool(dip.is_dipper),
        n_dips=int(dip.n_dips),
        var_class=_classify(period, amp_ppt, n_flares, dip.is_dipper),
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
    tool_version: str = __version__

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)


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
        ))
    return out
