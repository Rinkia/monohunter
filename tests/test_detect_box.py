"""T3 tests — the box detector must recover a real dip AND reject flat noise."""

import numpy as np

from monohunter.detect import BoxMatchedFilter, Candidate


def _time_axis(n=2000, cadence_min=2.0):
    dt = cadence_min / (60.0 * 24.0)  # days
    return np.arange(n) * dt


def test_flat_noise_yields_no_candidate():
    rng = np.random.default_rng(0)
    time = _time_axis()
    flux = 1.0 + rng.normal(0.0, 5e-4, size=time.size)
    assert BoxMatchedFilter().search(time, flux) == []


def test_injected_transit_is_recovered():
    rng = np.random.default_rng(1)
    time = _time_axis()
    flux = 1.0 + rng.normal(0.0, 5e-4, size=time.size)

    # Inject a ~24h box dip, depth 5 ppt, centered in the light curve.
    dt = time[1] - time[0]
    half = int((0.5 / 24.0) / dt) * 24  # ~12h half-width -> ~24h box
    center = time.size // 2
    flux[center - half : center + half] -= 5e-3

    found = BoxMatchedFilter().search(time, flux)
    assert len(found) == 1
    cand = found[0]
    assert isinstance(cand, Candidate)
    assert cand.snr >= 7.0
    assert cand.depth_ppt > 2.0  # recovered a real dip, not noise
    # event time lands within the injected window
    assert abs(cand.event_time_btjd - time[center]) < (half + 5) * dt


def test_short_light_curve_is_safe():
    assert BoxMatchedFilter().search(np.arange(4.0), np.ones(4)) == []


def test_zero_scatter_is_safe():
    # A perfectly flat curve has sigma 0 — must not divide by zero.
    time = _time_axis(n=500)
    assert BoxMatchedFilter().search(time, np.ones(time.size)) == []
