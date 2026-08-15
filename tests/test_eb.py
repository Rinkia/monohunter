"""EB period tests — eclipse finding + orbital period from eclipse times (pure)."""

import numpy as np

from monohunter.eb import eb_period, eb_period_from_eclipses, eclipse_times


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


def test_fragments_of_one_eclipse_merge():
    # a shallow jagged eclipse split into sub-hour fragments (like TIC 120239458's
    # secondary) must count as ONE eclipse, not several.
    t, f = _curve()
    f = f + np.random.default_rng(6).normal(0, 5e-4, t.size)
    f = _add_eclipse(t, f, 5.0, 0.20)                      # deep primary
    for tc in (12.00, 12.04, 12.07, 12.09):               # one dip, fragmented
        f = _add_eclipse(t, f, tc, 0.012, width_d=0.03)
    events = eclipse_times(t, f)
    assert len(events) == 2                                # not 5
    res = eb_period(t, f)
    assert res.n_eclipses == 2 and res.n_primary == 1
    assert res.secondary_detected is True
    assert res.orbital_period_d is None


def test_cross_sector_stitch_recovers_period():
    # one primary eclipse per sector, sectors far apart -> unrecoverable per sector,
    # recoverable from the stitched eclipse times (>=3 primaries pin the period).
    # Primaries at BTJD 1005, 1012, 1019 (7 d apart across "sectors").
    def sector_eclipse(t0):
        t, f = _curve(days=3.0)
        t = t + (t0 - 1.5)                     # center the 3-day window on t0
        f = f + np.random.default_rng(int(t0)).normal(0, 5e-4, t.size)
        f = _add_eclipse(t, f, t0, 0.10)
        return eclipse_times(t, f)

    all_ecl = sector_eclipse(1005.0) + sector_eclipse(1012.0) + sector_eclipse(1019.0)
    # each "sector" alone: 1 primary -> no period
    assert eb_period_from_eclipses(sector_eclipse(1005.0), assume_adjacent=True).orbital_period_d is None
    # stitched: 3 primaries 7 d apart -> P recovered
    combined = eb_period_from_eclipses(all_ecl, assume_adjacent=False)
    assert combined.n_primary == 3
    assert abs(combined.orbital_period_d - 7.0) < 0.1


def test_flat_curve_no_eclipses():
    t, f = _curve()
    rng = np.random.default_rng(1)
    f = f + rng.normal(0, 5e-4, t.size)
    assert eclipse_times(t, f) == []
