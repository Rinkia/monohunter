"""Trapezoid fit — refine a box candidate's depth and duration.

The box scan is a good DETECTOR but a poor characterizer: a wide uniform box
averages over ingress/egress and dilutes the depth (TOI-2180 read 3.6 ppt vs a
visual ~6 ppt). A trapezoid model recovers the real flat-bottom depth, the total
(first-to-last contact) duration, and the ingress/egress time.

        1.0 ──┐                    ┌──   out of transit
              \                    /
               \__________________/       flat bottom = 1 - depth
              |ingress|  flat   |egress|
              |<----- duration (T14) ---->|
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import curve_fit


# A transiting planet's depth tops out near ~3% (a giant on a small star);
# anything deeper is almost certainly a star eclipsing a star.
EB_DEPTH_THRESHOLD_PPT = 30.0
# V-shape: a dip whose ingress fills most of the half-duration has no flat bottom
# — the hallmark of a grazing eclipse (typically stellar). Paired with a modest
# depth floor so shallow noisy fits aren't mislabelled.
EB_VSHAPE_INGRESS_FRAC = 0.8
EB_VSHAPE_MIN_DEPTH_PPT = 10.0
# NOTE: no secondary-eclipse test. For a genuine long-period mono-transit the
# secondary sits ~P/2 after the primary, i.e. outside the single observed sector
# (P > sector by definition), so it can never appear in the data. Short-period
# EBs whose secondary would show are already rejected by the isolation guard.


def is_likely_eb(
    depth_ppt: float,
    ingress_hr: float | None = None,
    duration_hr: float | None = None,
) -> bool:
    """Likely an eclipsing binary → label (never reject).

    Two signals: (1) depth too deep for any planet; (2) a V-shaped (grazing) dip
    with non-trivial depth. ingress/duration are optional (None → depth-only).
    """
    if depth_ppt > EB_DEPTH_THRESHOLD_PPT:
        return True
    if ingress_hr is not None and duration_hr and duration_hr > 0:
        half = duration_hr / 2.0
        if (
            half > 0
            and ingress_hr / half >= EB_VSHAPE_INGRESS_FRAC
            and depth_ppt > EB_VSHAPE_MIN_DEPTH_PPT
        ):
            return True
    return False


@dataclass(frozen=True)
class TrapezoidFit:
    t0_btjd: float
    depth_ppt: float
    duration_hr: float  # T14, first-to-last contact
    ingress_hr: float


def _trapezoid(t: np.ndarray, t0: float, depth: float, dur: float, ingress: float) -> np.ndarray:
    """Symmetric trapezoid dip: 1 outside, ramps over `ingress`, flat at 1-depth."""
    phase = np.abs(t - t0)
    half = dur / 2.0
    ingress = np.clip(ingress, 1e-9, half)
    # slope in (0,1) during ingress/egress, >=1 (clipped) on the flat bottom
    frac = np.clip((half - phase) / ingress, 0.0, 1.0)
    return np.where(phase <= half, 1.0 - depth * frac, 1.0)


def fit_trapezoid(
    time: np.ndarray,
    flux: np.ndarray,
    t0_guess: float,
    duration_guess_hr: float,
    window_factor: float = 2.5,
) -> TrapezoidFit | None:
    """Fit a trapezoid near (t0_guess, duration_guess). None if the fit fails."""
    time = np.asarray(time, dtype=float)
    flux = np.asarray(flux, dtype=float)
    good = np.isfinite(time) & np.isfinite(flux)
    time, flux = time[good], flux[good]

    dur_g = duration_guess_hr / 24.0  # days
    local = np.abs(time - t0_guess) <= window_factor * dur_g
    t, f = time[local], flux[local]
    if t.size < 10:
        return None

    depth0 = max(1e-4, 1.0 - float(np.percentile(f, 1)))
    p0 = [t0_guess, depth0, dur_g, 0.2 * dur_g]
    lower = [t0_guess - dur_g, 1e-5, 0.2 * dur_g, 1e-5]
    upper = [t0_guess + dur_g, 0.5, 3.0 * dur_g, 1.5 * dur_g]

    try:
        popt, _ = curve_fit(_trapezoid, t, f, p0=p0, bounds=(lower, upper), maxfev=5000)
    except Exception:
        return None

    t0, depth, dur, ingress = popt
    if depth <= 0 or dur <= 0:
        return None
    return TrapezoidFit(
        t0_btjd=float(t0),
        depth_ppt=float(depth * 1e3),
        duration_hr=float(dur * 24.0),
        ingress_hr=float(ingress * 24.0),
    )
