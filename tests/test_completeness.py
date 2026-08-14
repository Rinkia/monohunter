"""Completeness tests — injection, recovery, and depth sensitivity (pure, offline)."""

import numpy as np

from monohunter.completeness import (
    completeness_depth,
    inject_box,
    is_recovered,
    mean_grid,
    recovery_fraction,
)


def test_mean_grid_averages_per_star_grids():
    g1 = {(1.0, 6.0): 0.5, (2.0, 6.0): 1.0}
    g2 = {(1.0, 6.0): 0.7, (2.0, 6.0): 0.8}
    m = mean_grid([g1, g2])
    assert abs(m[(1.0, 6.0)] - 0.6) < 1e-9
    assert abs(m[(2.0, 6.0)] - 0.9) < 1e-9


def _time(n=15000):
    return np.arange(n) * (2.0 / (60 * 24))  # ~21 d, 2-min cadence


class _Cand:
    def __init__(self, t0):
        self.event_time_btjd = t0


def test_inject_box_makes_a_dip_of_the_right_depth():
    t = _time()
    f = np.ones(t.size)
    c = t[t.size // 2]
    out = inject_box(t, f, c, depth_ppt=5.0, duration_hr=24.0)
    inside = np.abs(t - c) <= 0.5
    assert np.allclose(out[inside], 1.0 - 5e-3)   # 5 ppt dip
    assert np.allclose(out[~inside], 1.0)


def test_is_recovered_matches_position():
    assert is_recovered([_Cand(10.0)], t0=10.05, duration_hr=6.0) is True
    assert is_recovered([_Cand(10.0)], t0=15.0, duration_hr=6.0) is False   # far away
    assert is_recovered([], t0=10.0, duration_hr=6.0) is False              # nothing found


def test_recovery_high_for_deep_low_for_shallow():
    # A long transit averages the noise down, so "shallow" must also be SHORT to
    # sit under the SNR floor (a good sanity on the tool: sensitivity scales with
    # duration, not depth alone).
    t = _time()
    rng = np.random.default_rng(0)
    base = 1.0 + rng.normal(0, 5e-4, t.size)          # quiet baseline
    deep = recovery_fraction(t, base, depth_ppt=5.0, duration_hr=6.0, n=12, seed=1)
    shallow = recovery_fraction(t, base, depth_ppt=0.15, duration_hr=3.0, n=12, seed=1)
    assert deep > 0.8            # a 5 ppt / 6 h transit is nearly always recovered
    assert shallow < 0.3         # 0.15 ppt / 3 h sits under the SNR floor
    assert deep > shallow        # monotone in signal


def test_completeness_depth_threshold():
    grid = {
        (0.5, 12.0): 0.1, (1.0, 12.0): 0.4, (2.0, 12.0): 0.7, (5.0, 12.0): 0.95,
    }
    assert completeness_depth(grid, 12.0, 0.5) == 2.0     # first depth reaching 50%
    assert completeness_depth(grid, 12.0, 0.9) == 5.0
    assert completeness_depth(grid, 12.0, 0.99) is None   # never reached
