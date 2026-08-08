"""Summary tests — Lomb-Scargle rotation + classification (pure, offline)."""

import numpy as np

from monohunter.summary import (
    TESS_SYSTEMATIC_PERIODS_D,
    _classify,
    rotation_period,
    summarize,
)


def _time(n=15000):
    return np.arange(n) * (2.0 / (60 * 24))  # ~21 d at 2-min cadence


def test_rotation_recovers_injected_period():
    t = _time()
    rng = np.random.default_rng(0)
    p = 4.3
    flux = 1.0 + 0.02 * np.sin(2 * np.pi * t / p) + rng.normal(0, 5e-4, t.size)
    period, power, systematic = rotation_period(t, flux)
    assert systematic is False
    assert period is not None
    assert abs(period - p) < 0.1
    assert power > 0.1


def test_flat_star_has_no_rotation():
    t = _time()
    rng = np.random.default_rng(1)
    flux = 1.0 + rng.normal(0, 5e-4, t.size)
    period, power, systematic = rotation_period(t, flux)
    assert period is None and systematic is False


def test_tess_orbit_period_is_flagged_systematic():
    t = _time()
    rng = np.random.default_rng(2)
    p = TESS_SYSTEMATIC_PERIODS_D[0]  # ~13.7 d spacecraft orbit
    flux = 1.0 + 0.03 * np.sin(2 * np.pi * t / p) + rng.normal(0, 5e-4, t.size)
    period, power, systematic = rotation_period(t, flux)
    assert systematic is True          # not reported as a rotation period
    assert period is None


def test_classify_priority():
    assert _classify(period=4.0, amp_ppt=20, n_flares=0, is_dipper=True) == "dipper"
    assert _classify(period=4.0, amp_ppt=20, n_flares=5, is_dipper=False) == "flaring"
    assert _classify(period=4.0, amp_ppt=20, n_flares=0, is_dipper=False) == "rotator"
    assert _classify(period=None, amp_ppt=20, n_flares=0, is_dipper=False) == "variable"
    assert _classify(period=None, amp_ppt=1.0, n_flares=0, is_dipper=False) == "quiet"


def test_summarize_rotator():
    t = _time()
    rng = np.random.default_rng(3)
    raw = 1.0 + 0.02 * np.sin(2 * np.pi * t / 4.3) + rng.normal(0, 5e-4, t.size)
    # a transit-flattened copy: the rotation removed, flat baseline (no flares/dips)
    flat = 1.0 + rng.normal(0, 5e-4, t.size)
    res = summarize(t, raw, flat)
    assert res.var_class == "rotator"
    assert res.rotation_period_d is not None
    assert res.var_amplitude_ppt > 5.0     # 2% sine is clearly variable
