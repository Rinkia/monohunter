"""Phase-2 anomaly detection — flares and dippers.

Two non-transit anomaly classes on the SAME detrended light curves the transit
box scan uses, but they are a different physics so they get their own light
results (not the transit FindRecord):

  FLARE   — a sharp POSITIVE excursion (stellar brightening): flux jumps well
            above baseline for a few cadences, then decays. The mirror image of
            a transit dip.
  DIPPER  — MANY aperiodic dimming events (young stellar objects with orbiting
            dust): the transit box scan is built to find ONE clean dip and its
            isolation guard REJECTS multi-dip stars, so a dipper is exactly the
            signal that guard throws away. Aperiodicity separates it from an
            eclipsing binary (regular period).

Pure math (no network) so it is unit-testable offline; the fetch/detrend lives
in run_anomaly, mirroring pipeline.run_target.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826  # MAD -> Gaussian sigma

# Flares are strong, sustained positive excursions. A single high cadence is a
# hot pixel, not a flare — require a short run.
FLARE_SIGMA = 4.0
MIN_FLARE_POINTS = 3
# Dips for the dipper test: shallower threshold than a flare (dips are the
# science signal here), grouped into events.
DIP_SIGMA = 3.0
# A real dimming event spans several cadences; requiring 3 rejects random
# 2-cadence noise dips that would otherwise inflate the dip count and the
# interval scatter, false-flagging a regular EB as an (aperiodic) dipper.
MIN_DIP_POINTS = 3
# A dipper needs MANY dips whose spacing is IRREGULAR (high coefficient of
# variation). Regular spacing => eclipsing binary, not a dipper.
MIN_DIPPER_DIPS = 4
DIPPER_INTERVAL_CV_MIN = 0.3


@dataclass(frozen=True)
class FlareEvent:
    t_peak_btjd: float
    amplitude_ppt: float   # (peak flux - 1) * 1000
    duration_hr: float
    n_points: int


@dataclass(frozen=True)
class DipperResult:
    is_dipper: bool
    n_dips: int
    interval_cv: float          # coefficient of variation of dip spacings (nan if <2 dips)
    dip_times_btjd: tuple[float, ...]


def _robust_sigma(flux: np.ndarray) -> float:
    return _MAD_TO_SIGMA * float(np.median(np.abs(flux - np.median(flux))))


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous [start, end] index runs where mask is True (end inclusive)."""
    if not mask.any():
        return []
    idx = np.flatnonzero(mask)
    breaks = np.flatnonzero(np.diff(idx) > 1)
    starts = np.concatenate(([idx[0]], idx[breaks + 1]))
    ends = np.concatenate((idx[breaks], [idx[-1]]))
    return list(zip(starts.tolist(), ends.tolist()))


def find_flares(time: np.ndarray, flux: np.ndarray) -> list[FlareEvent]:
    """Sustained POSITIVE excursions above baseline — candidate stellar flares.

    ponytail: threshold + run-length only. A rise/decay asymmetry test (real
    flares rise in ~1 cadence, decay over several) would sharpen it later.
    """
    time = np.asarray(time, dtype=float)
    flux = np.asarray(flux, dtype=float)
    good = np.isfinite(time) & np.isfinite(flux)
    time, flux = time[good], flux[good]
    if time.size < MIN_FLARE_POINTS:
        return []
    sigma = _robust_sigma(flux)
    if sigma <= 0:
        return []

    above = flux > 1.0 + FLARE_SIGMA * sigma
    events: list[FlareEvent] = []
    for s, e in _runs(above):
        if e - s + 1 < MIN_FLARE_POINTS:
            continue
        seg = flux[s : e + 1]
        peak = int(np.argmax(seg)) + s
        events.append(FlareEvent(
            t_peak_btjd=float(time[peak]),
            amplitude_ppt=float((flux[peak] - 1.0) * 1e3),
            duration_hr=float((time[e] - time[s]) * 24.0),
            n_points=int(e - s + 1),
        ))
    return events


def find_dippers(time: np.ndarray, flux: np.ndarray) -> DipperResult:
    """Count dimming events and decide dipper vs single-transit/EB.

    A dipper is MANY dips with IRREGULAR spacing. One dip = a transit; many
    REGULAR dips = an eclipsing binary; many irregular dips = a dipper.

    EXPERIMENTAL — real-data caveat: this counts every >DIP_SIGMA excursion, so
    TESS systematics (momentum-dump ramps, red-noise wander, scattered light)
    register as extra "dips" and can false-flag a clean single-transit star as a
    dipper (verified live on TOI-2180: 6 "dips", only 1 real). A robust version
    must count only GUARDED dips — reuse the box detector's FP guards WITHOUT its
    isolation guard (which by design rejects the multi-dip signal a dipper is).
    That hardening is the follow-up; treat the current output as a coarse flag.
    """
    time = np.asarray(time, dtype=float)
    flux = np.asarray(flux, dtype=float)
    good = np.isfinite(time) & np.isfinite(flux)
    time, flux = time[good], flux[good]
    if time.size < MIN_DIP_POINTS:
        return DipperResult(False, 0, float("nan"), ())
    sigma = _robust_sigma(flux)
    if sigma <= 0:
        return DipperResult(False, 0, float("nan"), ())

    below = flux < 1.0 - DIP_SIGMA * sigma
    dip_times: list[float] = []
    for s, e in _runs(below):
        if e - s + 1 < MIN_DIP_POINTS:
            continue
        seg = flux[s : e + 1]
        deepest = int(np.argmin(seg)) + s
        dip_times.append(float(time[deepest]))

    n = len(dip_times)
    if n < 2:
        return DipperResult(False, n, float("nan"), tuple(dip_times))

    intervals = np.diff(sorted(dip_times))
    mean_iv = float(np.mean(intervals))
    cv = float(np.std(intervals) / mean_iv) if mean_iv > 0 else float("nan")
    is_dipper = n >= MIN_DIPPER_DIPS and cv >= DIPPER_INTERVAL_CV_MIN
    return DipperResult(is_dipper, n, cv, tuple(dip_times))


def run_anomaly(tic: int, sectors: list[int] | None = None, window_length: float | None = None):
    """Fetch + detrend each sector of a TIC, then scan for flares and dippers.

    Returns a list of (sector, list[FlareEvent], DipperResult). Network — mirrors
    pipeline.run_target's fetch/detrend loop but runs the anomaly detectors.
    """
    from .detrend import DEFAULT_WINDOW_D, flatten
    from .fetch import download_lightcurve, iter_lightcurves, search_tess

    win = window_length if window_length is not None else DEFAULT_WINDOW_D
    sr, rows = search_tess(tic)
    if sectors is not None:
        wanted = set(sectors)
        rows = [r for r in rows if int(r["sector"]) in wanted]

    def download(row):
        return download_lightcurve(sr, row["_index"])

    out = []
    for row, lc in iter_lightcurves(rows, download):
        t = np.asarray(lc.time.value if hasattr(lc.time, "value") else lc.time, dtype=float)
        f = np.asarray(getattr(lc.flux, "value", lc.flux), dtype=float)
        flat, _ = flatten(t, f, window_length=win)
        out.append((int(row["sector"]), find_flares(t, flat), find_dippers(t, flat)))
    return out
