"""Trapezoid fit must recover true depth — deeper than the box average."""

import numpy as np

from monohunter.characterize import (
    EB_DEPTH_THRESHOLD_PPT,
    _trapezoid,
    fit_trapezoid,
    is_likely_eb,
)


def test_is_likely_eb_depth_threshold():
    assert is_likely_eb(87.6) is True      # 8.8% -> eclipsing binary
    assert is_likely_eb(4.1) is False      # planet-depth transit
    assert is_likely_eb(EB_DEPTH_THRESHOLD_PPT + 1) is True
    assert is_likely_eb(EB_DEPTH_THRESHOLD_PPT - 1) is False


def _time_axis(n=3000):
    dt = 2.0 / (60 * 24)  # 2-min cadence, days
    return np.arange(n) * dt


def test_recovers_known_trapezoid():
    t = _time_axis()
    t0 = t[t.size // 2]
    truth = _trapezoid(t, t0, 6e-3, 1.0, 0.12)  # 6 ppt, 24h total, ~2.9h ingress
    rng = np.random.default_rng(0)
    flux = truth + rng.normal(0, 3e-4, t.size)

    fit = fit_trapezoid(t, flux, t0, duration_guess_hr=24.0)
    assert fit is not None
    assert abs(fit.depth_ppt - 6.0) < 1.0     # true depth, not box-diluted
    assert abs(fit.duration_hr - 24.0) < 4.0
    assert fit.ingress_hr > 0


def test_fit_is_deeper_than_box_average():
    # The whole point: a wide box average under-reads a real trapezoid.
    t = _time_axis()
    t0 = t[t.size // 2]
    flux = _trapezoid(t, t0, 6e-3, 1.0, 0.15)

    fit = fit_trapezoid(t, flux, t0, duration_guess_hr=24.0)
    box_depth = 1.0 - flux[np.abs(t - t0) <= 0.5].mean()  # crude 24h box depth
    assert fit is not None
    assert fit.depth_ppt / 1e3 > box_depth


def test_too_few_points_returns_none():
    assert fit_trapezoid(np.arange(5.0), np.ones(5), 2.0, 24.0) is None
