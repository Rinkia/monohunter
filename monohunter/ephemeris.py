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
# Below this SNR the trapezoid ingress is noise-dominated: its implied impact
# parameter is meaningless, so fall back to a blind b prior (wider, honest
# posterior) rather than a fake-precise one. Detection floor is 7; ingress shape
# is a 2nd-order feature needing more S/N than the dip itself.
SNR_INGRESS_MIN = 15.0
# The ingress must be spanned by at least this many cadences for its slope (hence
# the implied b) to mean anything. Coarse cadence smears the ingress LONGER than
# it is, biasing b -> period high — flooring the ingress *error* can't fix a biased
# *value* (verified: FFI TOI-2180 needed a ~4h error just to touch the truth), so
# below this we drop to blind b, which brackets. FFI 30-min ≈ 6 cadences -> blind;
# SPOC 2-min ≈ 69 -> trusted.
MIN_INGRESS_CADENCES = 10.0


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


P_MIN_GAP_THRESHOLD_D = 0.2  # a diff larger than this splits the baseline into segments


def _segments(t: np.ndarray, gap_threshold_d: float) -> list[tuple[float, float]]:
    """Contiguous observed (start, end) intervals, split at gaps > threshold."""
    edges = np.nonzero(np.diff(t) > gap_threshold_d)[0]
    starts = np.concatenate(([0], edges + 1))
    ends = np.concatenate((edges, [t.size - 1]))
    return [(float(t[s]), float(t[e])) for s, e in zip(starts, ends)]


def _p_min_baseline(
    t0_btjd: float, time_array, gap_threshold_d: float = P_MIN_GAP_THRESHOLD_D
) -> float:
    """Hard lower bound on P from non-detection of a 2nd transit.

    A period P is refuted if a sibling at t0±P lands in *covered* time (inside an
    observed segment). p_min is the smallest P that is NOT refuted — i.e. the
    nearest P at which both siblings escape into a gap or off the baseline. With
    no gaps this is just the far baseline edge; a mid-sector gap lets a sibling
    hide, lowering p_min to the distance from t0 to the near gap edge.
    """
    t = np.asarray(time_array, dtype=float)
    t = t[np.isfinite(t)]
    if t.size < 2:
        return 0.0
    t.sort()
    max_edge = float(max(t.max() - t0_btjd, t0_btjd - t.min()))

    # Refuted P-ranges: sibling t0+P inside a segment [s,e] -> P in [s-t0, e-t0];
    # sibling t0-P inside [s,e] -> P in [t0-e, t0-s]. Keep only positive P.
    refuted: list[tuple[float, float]] = []
    for s, e in _segments(t, gap_threshold_d):
        if e > t0_btjd:
            refuted.append((max(s - t0_btjd, 0.0), e - t0_btjd))
        if s < t0_btjd:
            refuted.append((max(t0_btjd - e, 0.0), t0_btjd - s))

    # p_min = end of the refuted interval that covers P=0 (t0 sits in a segment,
    # so both siblings start covered). The first gap in that run is the bound.
    refuted.sort()
    p_min = 0.0
    for lo, hi in refuted:
        if lo <= p_min + 1e-9:
            p_min = max(p_min, hi)
        else:
            break  # a non-refuted window opened -> that's the lower bound
    return min(p_min, max_edge)


def period_from_transits(transit_times, p_guess: float | None = None, resid_frac: float = 0.01):
    """Exact period from MULTIPLE transit times of the same event across epochs.

    Once a star transits in several sectors we have several observed transit
    times; the true period is the one that puts every transit on an integer cycle
    (t_i = t0 + n_i * P). This is vastly tighter than the single-transit estimate.

    - >=3 transits: uniquely recoverable. Scan the cycle count between first and
      last transit (largest period first); return the first period that gives
      every transit a distinct integer epoch with a small residual — the
      fundamental (aliases at P/k fit too but appear at higher cycle counts).
    - exactly 2 transits: genuinely ambiguous (P = span / N for any N); use
      p_guess (the rho*-based single-transit estimate) to pick the cycle count.

    Returns (period_d, t0_btjd, n_transits) or None.
    """
    ts = np.array(sorted({round(float(t), 6) for t in transit_times if np.isfinite(t)}))
    m = ts.size
    if m < 2:
        return None
    span = float(ts[-1] - ts[0])
    if span <= 0:
        return None

    def _fit(cycles: int):
        P = span / cycles
        ep = np.round((ts - ts[0]) / P).astype(int)
        if np.unique(ep).size < m:      # two transits collapsed onto one epoch
            return None
        design = np.vstack([np.ones(m), ep]).T
        (t0f, Pf), *_ = np.linalg.lstsq(design, ts, rcond=None)
        resid = float(np.sqrt(np.mean((ts - (t0f + ep * Pf)) ** 2)))
        return float(Pf), float(t0f), resid

    if m >= 3:
        max_cycles = min(int(span / 0.5), 50000)    # ignore periods below 0.5 d
        for cycles in range(1, max_cycles + 1):
            fit = _fit(cycles)
            if fit is None:
                continue
            P, t0, resid = fit
            if resid <= resid_frac * P:
                return P, t0, m
        return None

    # m == 2: pick the cycle count from the single-transit guess, else ambiguous.
    if p_guess and p_guess > 0:
        cycles = max(1, round(span / p_guess))
        return span / cycles, float(ts[0]), 2
    return None


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
    snr: float | None = None,
    cadence_s: float | None = None,
    n: int = 20000,
    seed: int = 0,
) -> PeriodPosterior:
    """Period posterior + next-transit window for a single transit. Pure.

    snr: detection SNR. Below SNR_INGRESS_MIN the ingress is too noisy to trust,
    so b falls back to blind regardless of the measured ingress. None = trust
    ingress when present (back-compat).
    cadence_s: sampling cadence. When the ingress is spanned by fewer than
    MIN_INGRESS_CADENCES, it is too coarsely sampled to trust -> blind b. None =
    ignore cadence (back-compat).
    """
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

    # Impact parameter: constrain from ingress only if it's measured, the SNR is
    # high enough, AND the cadence samples the ingress finely enough; else blind.
    snr_ok = snr is None or snr >= SNR_INGRESS_MIN
    cadence_ok = (
        cadence_s is None
        or ingress_hr is None
        or ingress_hr / (cadence_s / 3600.0) >= MIN_INGRESS_CADENCES
    )
    ingress_usable = (
        snr_ok
        and cadence_ok
        and ingress_hr is not None
        and np.isfinite(ingress_hr)
        and 0 < ingress_hr < t14_hr / 2
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
