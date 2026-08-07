"""Ephemeris tests — physics recovers a known period; guards behave."""

import numpy as np

from monohunter.ephemeris import (
    PeriodPosterior,
    _b_from_ingress,
    _p_min_baseline,
    estimate_period,
    period_from_transits,
)


def test_period_from_3plus_transits_is_exact():
    # Epochs 0, 1, 3 (a unit gap present, coprime differences) uniquely pin the
    # period — no guess needed. Sparse epochs sharing a common factor would leave
    # a multiple-of-P alias, which is an honest data limit, not a bug.
    P, t0 = 84.3, 1500.0
    times = [t0 + n * P for n in (0, 1, 3)]
    res = period_from_transits(times)
    assert res is not None
    period, fit_t0, n = res
    assert n == 3
    assert abs(period - P) < 1e-3


def test_period_from_transits_tolerates_small_timing_noise():
    P, t0 = 84.3, 1500.0
    times = [t0, t0 + P + 0.05, t0 + 3 * P - 0.05, t0 + 4 * P + 0.03]
    res = period_from_transits(times)
    assert res is not None
    period, _, n = res
    assert n == 4
    assert abs(period - P) < 0.05


def test_two_transits_need_a_guess():
    P, t0 = 84.3, 1500.0
    two = [t0, t0 + 12 * P]         # span = 12P; ambiguous without a guess
    assert period_from_transits(two) is None
    res = period_from_transits(two, p_guess=85.0)   # guess -> pick 12 cycles
    assert res is not None
    period, _, n = res
    assert n == 2 and abs(period - P) < 1e-6


def test_fewer_than_two_transits_returns_none():
    assert period_from_transits([1500.0]) is None
    assert period_from_transits([]) is None

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


def test_low_snr_ignores_ingress_and_widens_posterior():
    # Same ingress; low SNR must fall back to blind b (ingress unreliable), giving
    # b_from_ingress False and a wider posterior than the high-SNR case.
    low = estimate_period(
        ingress_hr=2.3, ingress_err_hr=0.4, time_array=S19_TIME, snr=8.0, **TOI2180
    )
    high = estimate_period(
        ingress_hr=2.3, ingress_err_hr=0.4, time_array=S19_TIME, snr=50.0, **TOI2180
    )
    assert low.b_from_ingress is False           # gated: ingress not trusted
    assert high.b_from_ingress is True           # trusted above SNR_INGRESS_MIN
    assert (low.p95_d / low.p05_d) > (high.p95_d / high.p05_d)
    assert low.period_constrained is True        # ρ* fine — still constrained, just blind b


def test_coarse_cadence_ignores_ingress_and_brackets():
    # FFI 30-min cadence spans the ~2.9h ingress by only ~6 cadences (< 10): the
    # ingress is smeared, so trusting it biases P high and excludes 261 (the real
    # FFI bug). Dropping to blind b must re-bracket the truth.
    coarse = estimate_period(
        ingress_hr=2.886, ingress_err_hr=None, time_array=S19_TIME,
        snr=53.0, cadence_s=1800.0, **TOI2180
    )
    fine = estimate_period(
        ingress_hr=2.886, ingress_err_hr=None, time_array=S19_TIME,
        snr=53.0, cadence_s=120.0, **TOI2180   # 2-min: ~87 cadences, trusted
    )
    assert coarse.b_from_ingress is False           # gated out by cadence
    assert fine.b_from_ingress is True              # finely sampled -> trusted
    assert coarse.p05_d <= KNOWN_P <= coarse.p95_d  # blind b re-brackets the truth


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


def test_p_min_gap_aware_lowers_bound():
    # Heavily-gapped baseline: segments [0,10], [20,22], [32,42]. Transit sits in
    # the short middle segment (t0=21). A period ~1-11d places BOTH siblings in the
    # flanking gaps, so p_min drops from the conservative far-edge (21) to ~1 (the
    # distance from t0 to its own segment edge, where the sibling enters the gap).
    t = np.concatenate([
        np.linspace(0.0, 10.0, 200),
        np.linspace(20.0, 22.0, 60),
        np.linspace(32.0, 42.0, 200),
    ])
    conservative = max(42.0 - 21.0, 21.0 - 0.0)          # = 21 (old behavior)
    p_min = _p_min_baseline(21.0, t)
    assert p_min < conservative
    assert abs(p_min - 1.0) < 0.1

    # No-gap sanity: a contiguous baseline still returns the far edge.
    contig = np.linspace(0.0, 27.0, 1000)
    assert abs(_p_min_baseline(13.5, contig) - 13.5) < 0.1


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
