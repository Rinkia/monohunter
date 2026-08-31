"""Observability tests — interval grouping (pure) + AltAz geometry (deterministic).

The Sun-darkness gate is disabled (sun_alt_deg=90 -> always 'dark') in the geometry
tests so they assert the altitude logic without depending on an exact ephemeris date.
"""

from monohunter.observability import _runs_to_intervals, observable_windows


def test_runs_to_intervals_groups_contiguous_trues():
    x = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    mask = [False, True, True, False, True, False]
    assert _runs_to_intervals(x, mask) == [(1.0, 2.0), (4.0, 4.0)]


def test_runs_to_intervals_all_false_is_empty():
    assert _runs_to_intervals([0.0, 1.0], [False, False]) == []


def test_empty_window_returns_nothing():
    assert observable_windows(180.0, 45.0, 1800.5, 1800.0, 0.0, 0.0) == []


def test_circumpolar_target_is_one_continuous_window():
    # Dec +89 seen from lat +80 sits ~9-89 deg up all night; sun gate off -> the whole
    # window is a single up-and-dark interval.
    ivals = observable_windows(
        ra_deg=0.0, dec_deg=89.0, t_start_btjd=1800.0, t_end_btjd=1800.5,
        lat_deg=80.0, lon_deg=0.0, min_alt_deg=30.0, sun_alt_deg=90.0, step_min=60.0,
    )
    assert len(ivals) == 1
    start, end = ivals[0]
    assert start == 1800.0 and abs(end - 1800.5) < 1e-6


def test_target_below_horizon_is_never_observable():
    # Dec -89 from lat +45 stays ~44 deg BELOW the horizon -> no interval clears 30 deg.
    ivals = observable_windows(
        ra_deg=0.0, dec_deg=-89.0, t_start_btjd=1800.0, t_end_btjd=1800.5,
        lat_deg=45.0, lon_deg=0.0, min_alt_deg=30.0, sun_alt_deg=90.0, step_min=60.0,
    )
    assert ivals == []
