"""Next-transit ephemeris from a single transit (analytic estimator).

A single transit gives t0, T14, ingress, depth — not the period P. Duration +
stellar density constrain P (Winn 2010 / Seager & Mallen-Ornelas 2003):

    P ≈ π² · G · ρ* · T14³ · f_ecc³ / (3 · [(1+k)² − b²]^(3/2))

k=Rp/R* from depth; b (impact parameter) is constrained from the measured
ingress/T14 ratio; e (eccentricity) is marginalized with a Kipping (2013) Beta
prior; ρ* comes from the catalog. Output is a period POSTERIOR (never a single
P — single transits are inherently period-ambiguous) plus the next-transit
window a follow-up observer can act on.

Pure math: no network. The caller supplies ρ* (the fetch lives in the pipeline).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

G = 6.674e-11          # m^3 / kg / s^2
DAY = 86400.0          # s
RHO_SUN_CGS = 1.408    # g/cm^3
# Kipping (2013) Beta eccentricity prior for transiting planets.
_ECC_A, _ECC_B = 0.867, 3.03


@dataclass(frozen=True)
class PeriodPosterior:
    period_constrained: bool          # False when ρ* is missing/too uncertain
    p_min_d: float                    # hard lower bound from non-detection of transit #2
    p_best_d: float | None = None     # posterior median
    p05_d: float | None = None
    p16_d: float | None = None
    p84_d: float | None = None
    p95_d: float | None = None
    b_from_ingress: bool = False      # True if b was constrained by ingress, not blind
    next_window_btjd: tuple[float, float, float] | None = None  # (5%, 50%, 95%) of next transit
    n_used: int = 0


def _b_from_ingress(ingress_hr, t14_hr: float, k: float):
    """Impact parameter from the ingress/T14 ratio (trapezoid geometry).

    Sharp ingress (T23 ≈ T14) → central transit (b ≈ 0). Long ingress
    (T23 → 0, V-shaped) → grazing (b → 1). Vectorized over ingress.
    """
    ingress = np.clip(ingress_hr, 1e-6, t14_hr / 2 - 1e-6)
    T23 = t14_hr - 2 * ingress                      # flat (2nd-3rd contact) duration
    r = np.clip((np.clip(T23, 0, t14_hr) / t14_hr) ** 2, 0.0, 1 - 1e-9)
    b2 = ((1 - k) ** 2 - r * (1 + k) ** 2) / (1 - r)
    b2 = np.clip(b2, 0.0, (1 + k) ** 2 - 1e-6)      # allow grazing up to b=1+k
    return np.sqrt(b2)


def _p_min_baseline(t0_btjd: float, time_array) -> float:
    """Conservative lower bound: a 2nd transit was not seen in the baseline, so
    P must exceed the distance from t0 to each baseline edge.

    ponytail: baseline-only; a gap-aware version (siblings can hide in data gaps,
    lowering p_min) is a later refinement.
    """
    t = np.asarray(time_array, dtype=float)
    t = t[np.isfinite(t)]
    if t.size < 2:
        return 0.0
    return float(max(t.max() - t0_btjd, t0_btjd - t.min()))


def estimate_period(
    t0_btjd: float,
    t14_hr: float,
    ingress_hr: float | None,
    ingress_err_hr: float | None,
    depth_ppt: float,
    rho_star_cgs: float | None,
    rho_err_cgs: float | None,
    time_array,
    now_btjd: float | None = None,
    n: int = 20000,
    seed: int = 0,
) -> PeriodPosterior:
    """Period posterior + next-transit window for a single transit. Pure."""
    rng = np.random.default_rng(seed)
    t14_s = t14_hr * 3600.0
    k = float(np.sqrt(max(depth_ppt, 0.0) / 1e3))
    p_min = _p_min_baseline(t0_btjd, time_array)

    # ρ* gate: never emit a confident wrong period.
    if rho_star_cgs is None or not np.isfinite(rho_star_cgs) or rho_star_cgs <= 0:
        return PeriodPosterior(False, p_min)
    rho_err = rho_err_cgs if (rho_err_cgs and rho_err_cgs > 0) else 0.5 * rho_star_cgs
    if rho_err / rho_star_cgs > 1.0:               # too uncertain to constrain P
        return PeriodPosterior(False, p_min)

    # Impact parameter: constrain from ingress if measured, else blind.
    ingress_usable = (
        ingress_hr is not None and np.isfinite(ingress_hr) and 0 < ingress_hr < t14_hr / 2
    )
    if ingress_usable:
        ie = ingress_err_hr if (ingress_err_hr and ingress_err_hr > 0) else 0.3 * ingress_hr
        # Ingress-error FLOOR: on a long transit the ingress is resolved by few
        # cadences, so a tight error over-trusts b and biases the period high
        # (demonstrated on TOI-2180: a 0.4h error pushed the true 261d out of the
        # 90% interval; ≥1h re-brackets it). Never trust ingress better than this.
        ie = max(ie, 0.5 * ingress_hr, 0.03 * t14_hr)
        ing_s = np.clip(rng.normal(ingress_hr, ie, n), 1e-3, t14_hr / 2 - 1e-3)
        b = _b_from_ingress(ing_s, t14_hr, k)
        b_constrained = True
    else:
        b = rng.uniform(0.0, 1.0, n)
        b_constrained = False

    e = rng.beta(_ECC_A, _ECC_B, n)
    w = rng.uniform(0.0, 2 * np.pi, n)
    rho_si = np.clip(rng.normal(rho_star_cgs, rho_err, n), 1e-4, None) * 1000.0  # g/cm^3 -> kg/m^3

    x = np.sqrt(np.clip((1 + k) ** 2 - b ** 2, 1e-6, None))
    f_ecc = (1 + e * np.sin(w)) / np.sqrt(1 - e ** 2)
    P_days = (np.pi ** 2 * G * rho_si * t14_s ** 3 * f_ecc ** 3 / (3 * x ** 3)) / DAY

    # A period below p_min would have shown a 2nd transit — physically excluded.
    P_days = P_days[P_days >= p_min]
    if P_days.size < 10:
        return PeriodPosterior(b_constrained, p_min, b_from_ingress=b_constrained)

    p05, p16, p50, p84, p95 = np.percentile(P_days, [5, 16, 50, 84, 95])

    next_window = None
    if now_btjd is not None:
        cycles = np.ceil((now_btjd - t0_btjd) / P_days)
        cycles = np.where(cycles < 1, 1, cycles)
        t_next = t0_btjd + cycles * P_days
        w5, w50, w95 = np.percentile(t_next, [5, 50, 95])
        next_window = (float(w5), float(w50), float(w95))

    return PeriodPosterior(
        period_constrained=True,
        p_min_d=p_min,
        p_best_d=float(p50),
        p05_d=float(p05),
        p16_d=float(p16),
        p84_d=float(p84),
        p95_d=float(p95),
        b_from_ingress=b_constrained,
        next_window_btjd=next_window,
        n_used=int(P_days.size),
    )
