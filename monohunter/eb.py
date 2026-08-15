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
# Two below-threshold runs closer than this are the SAME eclipse split by noise
# briefly rising above threshold (a jagged/shallow dip fragments into several
# runs). Merge them, keeping the deepest. A real eclipse lasts hours; two distinct
# eclipses of one system are >= half a period apart, so 0.3 d separates fragments
# from genuine siblings for all but ultra-short-period contact binaries.
# ponytail: fixed gap; a proper dip model would merge by shape.
MIN_ECLIPSE_SEP_D = 0.3
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

    # Merge fragments of one eclipse (runs split by noise briefly crossing the
    # threshold): collapse events within MIN_ECLIPSE_SEP_D, keeping the deepest.
    events.sort(key=lambda ev: ev.time_btjd)
    merged: list[Eclipse] = []
    for ev in events:
        if merged and ev.time_btjd - merged[-1].time_btjd < MIN_ECLIPSE_SEP_D:
            if ev.depth_ppt > merged[-1].depth_ppt:
                merged[-1] = ev
        else:
            merged.append(ev)
    return merged


def eb_period_from_eclipses(
    events: list[Eclipse], assume_adjacent: bool, p_guess: float | None = None
) -> EbResult | None:
    """Orbital period from a set of eclipses (one sector or many). Pure.

    Period comes ONLY from >=2 same-type (primary) eclipses; their spacing is a
    whole number of orbits.
    - >=3 primaries: period_from_transits pins the fundamental uniquely.
    - exactly 2 primaries: the cycle count between them is ambiguous. `assume_adjacent`
      (single-sector: two eclipses one sector apart ARE one orbit) takes their span as
      P; across sectors that's false, so a p_guess (single-transit estimate) is needed,
      else the period is left None.
    A lone primary+secondary pair also leaves orbital None (eccentric secondary at an
    unknown phase).
    """
    if not events:
        return None

    depths = np.array([e.depth_ppt for e in events])
    is_primary = depths >= PRIMARY_DEPTH_FRAC * float(depths.max())
    primary_times = sorted(e.time_btjd for e, p in zip(events, is_primary) if p)
    secondary = bool((~is_primary).any())
    n_primary = len(primary_times)

    orbital: float | None = None
    t0: float | None = float(primary_times[0]) if primary_times else None
    if n_primary >= 3:
        fit = period_from_transits(
            primary_times, p_guess=p_guess or (primary_times[-1] - primary_times[0]),
            resid_frac=EB_RESID_FRAC,
        )
        if fit is not None:
            orbital, t0, _ = float(fit[0]), float(fit[1]), fit[2]
    elif n_primary == 2:
        span = primary_times[1] - primary_times[0]
        if p_guess:
            fit = period_from_transits(primary_times, p_guess=p_guess, resid_frac=EB_RESID_FRAC)
            if fit is not None:
                orbital, t0, _ = float(fit[0]), float(fit[1]), fit[2]
        elif assume_adjacent:
            orbital = span

    return EbResult(
        n_eclipses=len(events),
        n_primary=n_primary,
        orbital_period_d=float(orbital) if orbital is not None else None,
        secondary_detected=secondary,
        t0_btjd=float(t0) if t0 is not None else None,
    )


def eb_period(time, flat_flux) -> EbResult | None:
    """Orbital period of an EB from its in-sector eclipses (single sector). Pure."""
    return eb_period_from_eclipses(eclipse_times(time, flat_flux), assume_adjacent=True)


def run_eb(tic: int, sectors: list[int] | None = None, window_length: float | None = None):
    """Fetch + flatten each sector of a TIC, recover the EB period. Network.

    Returns (per_sector, combined) where per_sector is list[(sector, EbResult|None)]
    and combined is an EbResult over ALL sectors' eclipse times together — a target
    with one eclipse per sector has its period unrecoverable in any single sector but
    recoverable from the stitched multi-sector eclipse times (like the transit path's
    measured_period_d). combined is None if fewer than 2 sectors have eclipses.

    NOTE the cross-sector period can be an integer MULTIPLE of the true period:
    sparse, widely-spaced eclipses whose epoch counts share a common factor alias
    to P*k (period_from_transits returns the largest period that fits). Verified on
    TIC 271763138 -> 134.48 d = 3 x the VSX 44.83 d. Still a valid ephemeris that
    phases every eclipse; treat the value as "P or P/k".
    """
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

    per_sector: list[tuple[int, EbResult | None]] = []
    all_eclipses: list[Eclipse] = []
    sectors_with_eclipses = 0
    for row, lc in iter_lightcurves(rows, download):
        time = _np.asarray(lc.time.value if hasattr(lc.time, "value") else lc.time, dtype=float)
        raw = _np.asarray(getattr(lc.flux, "value", lc.flux), dtype=float)
        flat, _ = flatten(time, raw, window_length=win)
        ecl = eclipse_times(time, flat)
        if ecl:
            sectors_with_eclipses += 1
        all_eclipses.extend(ecl)
        per_sector.append((int(row["sector"]), eb_period_from_eclipses(ecl, assume_adjacent=True)))

    # Stitch across sectors: primaries from >=2 sectors pin the period even when each
    # sector alone shows only one. assume_adjacent=False (cross-sector eclipses span
    # many cycles); >=3 primaries recover it uniquely.
    combined = (
        eb_period_from_eclipses(all_eclipses, assume_adjacent=False)
        if sectors_with_eclipses >= 2 else None
    )
    return per_sector, combined
