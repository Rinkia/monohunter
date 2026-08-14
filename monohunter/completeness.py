"""Survey completeness via injection-recovery.

A find list without a sensitivity function is a hobby list; with one it is a
survey. This injects synthetic box transits into a real light curve across a
depth x duration grid, runs the FULL detect pipeline (detrend + box + guards) on
each, and reports the recovered fraction — i.e. the depth at which the survey
catches 50% / 90% of transits. That number turns "we found X" into "we found X,
and here is what we would have missed."

    real light curve  ->  inject box(depth, dur) at N clean positions
                      ->  detrend + detect  ->  recovered? (candidate at t0)
                      ->  recovery fraction per (depth, dur)

inject_box / is_recovered / recovery_fraction / completeness_grid are pure (take
arrays + a detector) and unit-tested; run_completeness fetches a real light curve.
"""

from __future__ import annotations

import numpy as np

DEFAULT_DEPTHS_PPT = (0.5, 1.0, 2.0, 3.0, 5.0, 10.0)
DEFAULT_DURATIONS_HR = (3.0, 6.0, 12.0, 24.0)
GAP_THRESHOLD_D = 0.2
EDGE_MARGIN_D = 2.0   # keep injections clear of sector ends (the edge guard's turf)


def inject_box(time: np.ndarray, flux: np.ndarray, t0: float, depth_ppt: float, duration_hr: float) -> np.ndarray:
    """Add a symmetric box dip of depth_ppt (parts-per-thousand) at t0. Pure."""
    half = (duration_hr / 24.0) / 2.0
    out = np.asarray(flux, dtype=float).copy()
    inside = np.abs(np.asarray(time, dtype=float) - t0) <= half
    out[inside] -= depth_ppt / 1e3
    return out


def is_recovered(cands, t0: float, duration_hr: float) -> bool:
    """True if the detector's best candidate sits within ~one transit of t0."""
    if not cands:
        return False
    tol_d = max(duration_hr / 24.0, 0.1)   # within a transit width (generous), days
    return abs(cands[0].event_time_btjd - t0) <= tol_d


def _clean_positions(time: np.ndarray, n: int, duration_hr: float, rng) -> list[float]:
    """Random t0 in the mid-baseline, clear of sector ends and data gaps — so the
    recovery number measures DEPTH sensitivity, not edge/gap losses."""
    t = np.asarray(time, dtype=float)
    lo, hi = t.min() + EDGE_MARGIN_D, t.max() - EDGE_MARGIN_D
    gaps = t[np.nonzero(np.diff(t) > GAP_THRESHOLD_D)[0]]
    margin = EDGE_MARGIN_D + duration_hr / 24.0
    out: list[float] = []
    for _ in range(n * 20):
        if len(out) >= n:
            break
        c = float(rng.uniform(lo, hi))
        if gaps.size and np.min(np.abs(gaps - c)) < margin:
            continue
        out.append(c)
    return out


def recovery_fraction(time, base_flux, depth_ppt, duration_hr, detector=None,
                      window_length: float = 3.0, n: int = 20, seed: int = 0) -> float:
    """Fraction of N injected transits (depth, dur) recovered by the full pipeline."""
    from .detect import BoxMatchedFilter
    from .detrend import flatten

    detector = detector or BoxMatchedFilter()
    time = np.asarray(time, dtype=float)
    base = np.asarray(base_flux, dtype=float)
    rng = np.random.default_rng(seed)
    positions = _clean_positions(time, n, duration_hr, rng)
    if not positions:
        return float("nan")
    hits = 0
    for t0 in positions:
        injected = inject_box(time, base, t0, depth_ppt, duration_hr)
        flat, _ = flatten(time, injected, window_length=window_length)
        if is_recovered(detector.search(time, flat), t0, duration_hr):
            hits += 1
    return hits / len(positions)


def completeness_grid(time, base_flux, depths=DEFAULT_DEPTHS_PPT, durations=DEFAULT_DURATIONS_HR,
                      n: int = 20, window_length: float = 3.0, seed: int = 0) -> dict:
    """{(depth_ppt, duration_hr): recovered_fraction} over the grid."""
    out = {}
    for di, depth in enumerate(depths):
        for dj, dur in enumerate(durations):
            out[(depth, dur)] = recovery_fraction(
                time, base_flux, depth, dur, window_length=window_length, n=n,
                seed=seed + di * 100 + dj,
            )
    return out


def completeness_depth(grid: dict, duration_hr: float, level: float) -> float | None:
    """Shallowest depth (at this duration) whose recovery reaches `level` (e.g.
    0.5, 0.9). None if never reached."""
    pairs = sorted((d, f) for (d, dur), f in grid.items() if dur == duration_hr)
    for depth, frac in pairs:
        if frac is not None and frac >= level:
            return depth
    return None


def run_completeness(tic: int, sector: int, n: int = 20, window_length: float = 3.0):
    """Fetch a real light curve for (tic, sector) and run the injection-recovery
    grid on it. Use a QUIET star so injected transits are the only signal.
    Returns (grid, time_size). Network."""
    from .fetch import download_lightcurve, iter_lightcurves, search_tess

    sr, rows = search_tess(tic)
    rows = [r for r in rows if int(r["sector"]) == sector]
    if not rows:
        return None, 0

    def download(row):
        return download_lightcurve(sr, row["_index"])

    from .detect import BoxMatchedFilter  # noqa: F401 (used below)
    from .detrend import flatten  # noqa: F401

    for _row, lc in iter_lightcurves(rows, download):
        time = np.asarray(lc.time.value if hasattr(lc.time, "value") else lc.time, dtype=float)
        flux = np.asarray(getattr(lc.flux, "value", lc.flux), dtype=float)
        good = np.isfinite(time) & np.isfinite(flux)
        t, f = time[good], flux[good]
        # Base-star sanity: the detector returns only its single best candidate, so
        # a base with its OWN transit/eclipse would mask every weaker injection and
        # bias the whole grid low. Flag it so the caller knows the star isn't clean.
        flat, _ = flatten(t, f, window_length=window_length)
        base_clean = len(BoxMatchedFilter().search(t, flat)) == 0
        grid = completeness_grid(t, f, n=n, window_length=window_length)
        return grid, int(good.sum()), base_clean
    return None, 0, True


def mean_grid(grids: list[dict]) -> dict:
    """Average a set of per-star recovery grids into one survey grid."""
    keys = grids[0].keys()
    return {k: float(np.nanmean([g[k] for g in grids])) for k in keys}


def run_completeness_sample(tics, sector: int, n: int = 20, window_length: float = 3.0):
    """SURVEY completeness: run injection-recovery on each of `tics` and average.
    Sensitivity varies with a star's noise, so one star is not the survey — the
    mean over a representative sample is. Skips stars with their own signal.
    Returns (mean_grid, n_stars_used). Network."""
    grids = []
    for tic in tics:
        try:
            grid, _epochs, clean = run_completeness(int(tic), sector, n=n, window_length=window_length)
        except Exception:
            continue   # a slow/failed MAST fetch for one star must not sink the sample
        if grid is not None and clean:
            grids.append(grid)
    if not grids:
        return None, 0
    return mean_grid(grids), len(grids)
