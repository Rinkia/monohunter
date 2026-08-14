"""EB period tests — eclipse finding + orbital period from eclipse times (pure)."""

import numpy as np

from monohunter.eb import eb_period, eclipse_times


def _curve(n=15000, days=21.0):
    return np.arange(n) * (days / n), np.ones(n)


def _add_eclipse(t, f, t0, depth, width_d=0.1):
    f[np.abs(t - t0) < width_d / 2] -= depth
    return f


def test_eclipse_times_finds_both_dips():
    t, f = _curve()
    rng = np.random.default_rng(0)
    f = f + rng.normal(0, 5e-4, t.size)
    f = _add_eclipse(t, f, 5.0, 0.1)
    f = _add_eclipse(t, f, 12.0, 0.1)
    events = eclipse_times(t, f)
    assert len(events) == 2
    times = sorted(e.time_btjd for e in events)
    assert abs(times[0] - 5.0) < 0.1 and abs(times[1] - 12.0) < 0.1


def test_two_primaries_give_period():
    t, f = _curve()
    f = f + np.random.default_rng(2).normal(0, 5e-4, t.size)
    f = _add_eclipse(t, f, 5.0, 0.1)
    f = _add_eclipse(t, f, 12.0, 0.1)
    res = eb_period(t, f)
    assert res is not None
    assert res.n_primary == 2 and res.secondary_detected is False
    assert abs(res.orbital_period_d - 7.0) < 0.1


def test_period_from_primaries_only_ignores_secondary():
    t, f = _curve()
    f = f + np.random.default_rng(3).normal(0, 5e-4, t.size)
    for tc in (3.0, 9.0, 15.0):        # primaries, deep -> spacing 6 = orbital P
        f = _add_eclipse(t, f, tc, 0.10)
    for tc in (6.0, 12.0):             # secondaries, shallow (mid-orbit)
        f = _add_eclipse(t, f, tc, 0.03)
    res = eb_period(t, f)
    assert res is not None
    assert res.n_primary == 3 and res.secondary_detected is True
    assert abs(res.orbital_period_d - 6.0) < 0.1     # primary spacing, not 3


def test_primary_plus_secondary_is_unrecoverable():
    # eccentric-EB case (TIC 271763138): one primary + one secondary, secondary at
    # an arbitrary phase -> period NOT recoverable, must return None period.
    t, f = _curve()
    f = f + np.random.default_rng(4).normal(0, 5e-4, t.size)
    f = _add_eclipse(t, f, 5.0, 0.24)      # primary
    f = _add_eclipse(t, f, 14.16, 0.045)   # secondary at phase ~0.2
    res = eb_period(t, f)
    assert res is not None
    assert res.n_eclipses == 2 and res.n_primary == 1
    assert res.secondary_detected is True
    assert res.orbital_period_d is None    # never a confident wrong period


def test_single_eclipse_period_none():
    t, f = _curve()
    f = f + np.random.default_rng(5).normal(0, 5e-4, t.size)
    f = _add_eclipse(t, f, 5.0, 0.1)
    res = eb_period(t, f)
    assert res is not None and res.n_primary == 1 and res.orbital_period_d is None


def test_flat_curve_no_eclipses():
    t, f = _curve()
    rng = np.random.default_rng(1)
    f = f + rng.normal(0, 5e-4, t.size)
    assert eclipse_times(t, f) == []
