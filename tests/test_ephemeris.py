"""Ephemeris tests — physics recovers a known period; guards behave."""

import numpy as np

from monohunter.ephemeris import (
    PeriodPosterior,
    _b_from_ingress,
    _p_min_baseline,
    estimate_period,
)

# TOI-2180 b: the by-hand-check target. Real TIC ρ*=0.238 solar → cgs.
TOI2180 = dict(
    t0_btjd=1830.77,
    t14_hr=24.0,
    depth_ppt=4.1,
    rho_star_cgs=0.238 * 1.408,   # 0.335 g/cm^3
    rho_err_cgs=0.05,
)
KNOWN_P = 260.8
# ~25-day S19 baseline, transit mid-sector.
S19_TIME = np.linspace(1816.0, 1841.0, 15000)


def test_b_from_ingress_sharp_is_central_graze_is_high():
    t14, k = 24.0, 0.06
    b_sharp = float(_b_from_ingress(np.array([0.3]), t14, k)[0])   # near-box ingress
    b_graze = float(_b_from_ingress(np.array([t14 / 2 - 0.5]), t14, k)[0])  # V-shaped
    assert b_sharp < 0.3
    assert b_graze > 0.8


def test_recovers_toi2180_period_blind_b():
    # Blind b (ingress=None) reproduces the by-hand check: posterior brackets 261 d.
    post = estimate_period(
        ingress_hr=None, ingress_err_hr=None, time_array=S19_TIME, **TOI2180
    )
    assert post.period_constrained is True
    assert post.b_from_ingress is False
    assert post.p_best_d > post.p_min_d
    assert post.p05_d <= KNOWN_P <= post.p95_d      # true period inside 5-95%


def test_ingress_narrows_the_posterior():
    blind = estimate_period(
        ingress_hr=None, ingress_err_hr=None, time_array=S19_TIME, **TOI2180
    )
    withing = estimate_period(
        ingress_hr=2.3, ingress_err_hr=0.4, time_array=S19_TIME, **TOI2180
    )
    assert withing.b_from_ingress is True
    # constraining b tightens the fractional spread of the period posterior
    assert (withing.p95_d / withing.p05_d) < (blind.p95_d / blind.p05_d)


def test_toi2180_brackets_despite_tight_ingress_error():
    # The ingress-error floor must prevent over-trusting a suspiciously tight
    # ingress error (which biased the period high and excluded the truth).
    post = estimate_period(
        ingress_hr=2.3, ingress_err_hr=0.1, time_array=S19_TIME, **TOI2180
    )
    assert post.b_from_ingress is True
    assert post.p05_d <= KNOWN_P <= post.p95_d


def test_missing_rho_is_unconstrained():
    post = estimate_period(
        t0_btjd=1830.77, t14_hr=24.0, ingress_hr=2.3, ingress_err_hr=0.4,
        depth_ppt=4.1, rho_star_cgs=None, rho_err_cgs=None, time_array=S19_TIME,
    )
    assert post.period_constrained is False
    assert post.p_best_d is None
    assert post.p_min_d > 0            # p_min still reported


def test_huge_rho_error_is_unconstrained():
    post = estimate_period(
        ingress_hr=2.3, ingress_err_hr=0.4, time_array=S19_TIME,
        **{**TOI2180, "rho_err_cgs": 5.0},   # >100% error
    )
    assert post.period_constrained is False


def test_grazing_does_not_blow_up():
    # Very long ingress -> b near 1 -> must stay finite (x capped), not inf.
    post = estimate_period(
        ingress_hr=11.5, ingress_err_hr=0.2, time_array=S19_TIME, **TOI2180
    )
    assert post.p_best_d is None or np.isfinite(post.p_best_d)


def test_p_min_baseline():
    # transit mid-baseline -> p_min ~ half; near start -> ~full baseline.
    t = np.linspace(0.0, 27.0, 1000)
    assert abs(_p_min_baseline(13.5, t) - 13.5) < 0.1
    assert abs(_p_min_baseline(1.0, t) - 26.0) < 0.1


def test_next_window_from_known_period():
    # now just after t0 -> next transit ~ t0 + P (median), inside baseline-consistent range.
    post = estimate_period(
        ingress_hr=2.3, ingress_err_hr=0.4, time_array=S19_TIME,
        now_btjd=1835.0, **TOI2180,
    )
    assert post.next_window_btjd is not None
    lo, med, hi = post.next_window_btjd
    assert lo <= med <= hi
    assert med > 1835.0                # next transit is in the future
