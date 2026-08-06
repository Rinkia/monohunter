"""Anomaly tests — flares (positive spikes) and dippers (many irregular dips)."""

import numpy as np

from monohunter.anomaly import DipperResult, find_dippers, find_flares


def _time(n=15000, cadence_min=2.0):
    return np.arange(n) * (cadence_min / (60.0 * 24.0))


def _clean(rng, n=15000):
    return 1.0 + rng.normal(0.0, 5e-4, n)


def test_flare_is_found():
    rng = np.random.default_rng(0)
    t = _time(); f = _clean(rng)
    f[8000:8005] += 8e-3            # +16 sigma spike, 5 cadences
    flares = find_flares(t, f)
    assert len(flares) == 1
    assert flares[0].amplitude_ppt > 5.0
    assert abs(flares[0].t_peak_btjd - t[8000]) < (10 * (t[1] - t[0]))


def test_single_hot_pixel_is_not_a_flare():
    rng = np.random.default_rng(1)
    t = _time(); f = _clean(rng)
    f[8000] += 2e-2                 # one cadence -> below MIN_FLARE_POINTS
    assert find_flares(t, f) == []


def test_clean_star_has_no_flares():
    rng = np.random.default_rng(2)
    assert find_flares(_time(), _clean(rng)) == []


def test_dipper_many_irregular_dips():
    rng = np.random.default_rng(3)
    t = _time(); f = _clean(rng)
    # 6 dips at IRREGULAR indices, varying depth -> aperiodic dipper.
    for c in (1200, 3100, 3900, 7000, 10500, 12800):
        f[c : c + 6] -= 6e-3
    res = find_dippers(t, f)
    assert res.is_dipper is True
    assert res.n_dips == 6
    assert res.interval_cv >= 0.3


def test_regular_dips_are_not_a_dipper():
    rng = np.random.default_rng(4)
    t = _time(); f = _clean(rng)
    for c in range(2000, 14000, 2000):   # evenly spaced -> EB-like, low CV
        f[c : c + 6] -= 6e-3
    res = find_dippers(t, f)
    assert res.n_dips >= 4
    assert res.is_dipper is False        # regular spacing rejected


def test_single_transit_is_not_a_dipper():
    rng = np.random.default_rng(5)
    t = _time(); f = _clean(rng)
    f[7000:7300] -= 5e-3                  # one dip
    res = find_dippers(t, f)
    assert res.n_dips == 1
    assert res.is_dipper is False


def test_clean_star_is_not_a_dipper():
    rng = np.random.default_rng(6)
    res = find_dippers(_time(), _clean(rng))
    assert isinstance(res, DipperResult)
    assert res.is_dipper is False
    assert res.n_dips == 0
