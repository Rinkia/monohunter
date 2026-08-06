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
# A dipper needs MANY dips whose spacing is IRREGULAR (high coefficient of
# variation). Regular spacing => eclipsing binary, not a dipper.
MIN_DIPPER_DIPS = 4
DIPPER_INTERVAL_CV_MIN = 0.3
# Iteratively pull the deepest GUARDED dip and mask it, up to this many times.
MAX_DIPPER_ITERS = 12
DIP_MASK_FACTOR = 1.5  # mask +/- this * duration around each found dip


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
    """Count GUARDED dimming events and decide dipper vs single-transit/EB.

    A dipper is MANY dips with IRREGULAR spacing. One dip = a transit; many
    REGULAR dips = an eclipsing binary; many irregular dips = a dipper.

    Each dip is a real detection from the box matched filter with all its
    false-positive guards (edge, gap-span, gap-flanking-ramp, scatter-stripe,
    scatter-region, red-noise SNR) EXCEPT isolation — which is disabled here on
    purpose, since a dipper is precisely a multi-dip star that isolation would
    reject. This is what makes it robust to TESS systematics that a raw >3-sigma
    threshold counts as spurious dips (the earlier naive version false-flagged
    TOI-2180 with 6 "dips"; guarded counting leaves the 1 real transit).

    We pull the deepest guarded dip, mask it, and re-search until none remain.
    """
    from .detect import BoxMatchedFilter

    time = np.asarray(time, dtype=float)
    flux = np.asarray(flux, dtype=float)
    good = np.isfinite(time) & np.isfinite(flux)
    time, flux = time[good], flux[good]
    if time.size < 10:
        return DipperResult(False, 0, float("nan"), ())

    detector = BoxMatchedFilter(check_isolation=False)
    work = flux.copy()
    dip_times: list[float] = []
    for _ in range(MAX_DIPPER_ITERS):
        cands = detector.search(time, work)
        if not cands:
            break
        c = cands[0]
        dip_times.append(c.event_time_btjd)
        half = (c.duration_hr / 24.0) * DIP_MASK_FACTOR
        work = work.copy()
        work[np.abs(time - c.event_time_btjd) <= half] = 1.0   # remove found dip

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
