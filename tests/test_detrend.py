"""T5 tests — the top footgun: a too-short detrend window EATS the transit.

This regression guards the #1 mistake from the reproduce-by-hand notebook.
"""

import numpy as np

from monohunter.detrend import flatten


def _curve_with_dip():
    # 27-day sector, slow sinusoidal stellar trend, one ~24h box dip of 1%.
    time = np.linspace(0.0, 27.0, 27 * 720)  # 2-min cadence
    trend = 1.0 + 0.01 * np.sin(2 * np.pi * time / 13.0)
    flux = trend.copy()
    center = time.size // 2
    half = 360  # ~12h -> 24h dip
    flux[center - half : center + half] -= 0.01
    return time, flux


def test_long_window_preserves_dip_short_window_eats_it():
    time, flux = _curve_with_dip()

    flat_good, _ = flatten(time, flux, window_length=3.0)   # >> 1-day transit
    flat_bad, _ = flatten(time, flux, window_length=0.5)    # < 1-day transit

    depth_good = 1.0 - np.nanmin(flat_good)
    depth_bad = 1.0 - np.nanmin(flat_bad)

    # Good window keeps most of the 1% dip.
    assert depth_good > 5e-3
    # Short window flattens the dip away — strictly shallower.
    assert depth_bad < depth_good
