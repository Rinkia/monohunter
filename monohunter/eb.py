"""Eclipsing-binary orbital period from in-sector eclipses.

A sweep already flags likely EBs (deep OR V-shaped, or the isolation guard's
"keeps dipping" reject), but only records the depth. When two or more eclipses
fall inside one sector the ORBITAL PERIOD is recoverable with no extra download:
find the eclipse times, then reuse ephemeris.period_from_transits (which fits the
period that puts every eclipse on an integer cycle).

    flat flux  ->  eclipse_times (deep contiguous dips)  ->  period_from_transits
                -> eclipse interval  (+ x2 when a shallower secondary is present)

The period is recoverable ONLY from two or more SAME-TYPE eclipses (e.g. two
primaries), whose spacing is exactly one orbit. A lone primary+secondary pair is
NOT enough: on an eccentric orbit the secondary sits at an unknown phase (real
example TIC 271763138 — secondary at phase ~0.2, so the primary-secondary gap is
9.16d while the true period is 44.8d), so their separation is not a period
fraction. In that case orbital_period_d is None — never a confident wrong period.

Pure math, no network; run_eb is the fetch orchestrator (mirrors summary.run_summary).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .ephemeris import period_from_transits

# An eclipse point sits at least this many robust sigma below the flat baseline.
ECLIPSE_DEPTH_SIGMA = 5.0
# Minimum contiguous below-threshold cadences for a real eclipse (rejects single
# negative outliers). Real eclipses last hours = many 2-min cadences.
ECLIPSE_MIN_POINTS = 3
# Eclipse minima are timed by flux-argmin over a flat-bottomed dip, so they jitter
# by ~half the eclipse width — far looser than a sharp transit centroid. Loosen the
# period-fit residual tolerance accordingly (transit default 0.01 is too tight).
# ponytail: argmin timing; a parabola/centroid fit on each eclipse would tighten it.
EB_RESID_FRAC = 0.05
# An eclipse belongs to the PRIMARY (deep) class when its depth is at least this
# fraction of the deepest eclipse; shallower ones are secondaries. ponytail: a
# fixed split, not a clustering fit; good enough to separate a clear primary from
# a secondary. Refine to depth clustering if mixed catalogs need it.
PRIMARY_DEPTH_FRAC = 0.5


@dataclass(frozen=True)
class Eclipse:
    time_btjd: float
    depth_ppt: float


@dataclass(frozen=True)
class EbResult:
    n_eclipses: int
    n_primary: int                        # eclipses in the deep (primary) class
    orbital_period_d: float | None        # None unless >=2 same-type eclipses pin it
    secondary_detected: bool
    t0_btjd: float | None = None


def eclipse_times(
    time,
    flat_flux,
    min_depth_sigma: float = ECLIPSE_DEPTH_SIGMA,
    min_points: int = ECLIPSE_MIN_POINTS,
) -> list[Eclipse]:
    """Distinct eclipse epochs (deep contiguous dips) in a flattened light curve.

    Each below-threshold run of >= min_points cadences is one eclipse, timed at its
    flux minimum. Pure.
    """
    t = np.asarray(time, dtype=float)
    f = np.asarray(flat_flux, dtype=float)
    good = np.isfinite(t) & np.isfinite(f)
    t, f = t[good], f[good]
    if t.size < min_points:
        return []
    sigma = 1.4826 * float(np.median(np.abs(f - np.median(f))))
    if sigma <= 0:
        return []

    below = f < (1.0 - min_depth_sigma * sigma)
    if not below.any():
        return []

    # Contiguous runs of below-threshold cadences (NaNs already removed, so
    # adjacent indices are adjacent in time). Each run = one eclipse.
    edges = np.diff(below.astype(int))
    starts = list(np.nonzero(edges == 1)[0] + 1)
    ends = list(np.nonzero(edges == -1)[0] + 1)
    if below[0]:
        starts.insert(0, 0)
    if below[-1]:
        ends.append(below.size)

    events: list[Eclipse] = []
    for s, e in zip(starts, ends):
        if e - s < min_points:
            continue
        j = s + int(np.argmin(f[s:e]))
        events.append(Eclipse(time_btjd=float(t[j]), depth_ppt=float((1.0 - f[j]) * 1e3)))
    return events


def eb_period(time, flat_flux) -> EbResult | None:
    """Orbital period of an EB from its in-sector eclipses. Pure.

    Returns None if no eclipse is found. The period is recovered ONLY from >=2
    same-type (primary) eclipses — their spacing is exactly one orbit. A lone
    primary+secondary pair leaves orbital_period_d None (an eccentric secondary
    sits at an unknown phase, so the gap is not a period fraction).
    """
    events = eclipse_times(time, flat_flux)
    if not events:
        return None

    depths = np.array([e.depth_ppt for e in events])
    is_primary = depths >= PRIMARY_DEPTH_FRAC * float(depths.max())
    primary_times = [e.time_btjd for e, p in zip(events, is_primary) if p]
    secondary = bool((~is_primary).any())
    n_primary = len(primary_times)

    orbital: float | None = None
    t0: float | None = float(min(primary_times)) if primary_times else None
    if n_primary >= 2:
        span = max(primary_times) - min(primary_times)
        if n_primary >= 3:
            fit = period_from_transits(primary_times, p_guess=span, resid_frac=EB_RESID_FRAC)
            if fit is not None:
                orbital, t0, _ = float(fit[0]), float(fit[1]), fit[2]
        else:
            # two primaries: adjacent by construction (two in one sector) -> span = P
            orbital = span

    return EbResult(
        n_eclipses=len(events),
        n_primary=n_primary,
        orbital_period_d=float(orbital) if orbital is not None else None,
        secondary_detected=secondary,
        t0_btjd=float(t0) if t0 is not None else None,
    )


def run_eb(tic: int, sectors: list[int] | None = None, window_length: float | None = None):
    """Fetch + flatten each sector of a TIC, recover the EB period. Network.
    Returns list[(sector, EbResult)]. Mirrors summary.run_summary's fetch loop."""
    import numpy as _np

    from .detrend import DEFAULT_WINDOW_D, flatten
    from .fetch import download_lightcurve, iter_lightcurves, search_tess

    win = window_length if window_length is not None else DEFAULT_WINDOW_D
    sr, rows = search_tess(tic)
    if sectors is not None:
        wanted = set(sectors)
        rows = [r for r in rows if int(r["sector"]) in wanted]

    def download(row):
        return download_lightcurve(sr, row["_index"])

    out: list[tuple[int, EbResult | None]] = []
    for row, lc in iter_lightcurves(rows, download):
        time = _np.asarray(lc.time.value if hasattr(lc.time, "value") else lc.time, dtype=float)
        raw = _np.asarray(getattr(lc.flux, "value", lc.flux), dtype=float)
        flat, _ = flatten(time, raw, window_length=win)
        out.append((int(row["sector"]), eb_period(time, flat)))
    return out
