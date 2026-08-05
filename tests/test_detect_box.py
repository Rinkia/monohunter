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


def test_variable_star_is_rejected():
    # Continuous ~2% oscillation over many cycles, no flat baseline (the
    # TIC 17308640 case). Every trough is as deep as the deepest, so the
    # isolation guard must reject it despite a high SNR.
    time = _time_axis(n=15000)  # ~21 days, ~8 cycles of a 2.5-day period
    rng = np.random.default_rng(4)
    flux = 1.0 + 0.02 * np.sin(2 * np.pi * time / 2.5) + rng.normal(0, 5e-4, time.size)
    assert BoxMatchedFilter().search(time, flux) == []


def test_isolated_transit_survives_guard_on_quiet_star():
    # Flat baseline + one dip -> depth >> out-of-transit scatter -> kept.
    rng = np.random.default_rng(5)
    time = _time_axis()
    flux = 1.0 + rng.normal(0, 5e-4, time.size)
    dt = time[1] - time[0]
    half = int((0.5 / 24.0) / dt) * 24
    c = time.size // 2
    flux[c - half : c + half] -= 5e-3
    assert len(BoxMatchedFilter().search(time, flux)) == 1


def test_gap_straddling_candidate_is_rejected():
    # A dip at the edge of a 1-day data gap: the box mixes cadences across the
    # gap into a spurious dip (the sweep's gap-edge false positives).
    dt = 2.0 / (60 * 24)
    seg = np.arange(1500) * dt
    time = np.concatenate([seg, seg[-1] + 1.0 + np.arange(1500) * dt])  # 1-day gap
    rng = np.random.default_rng(7)
    flux = 1.0 + rng.normal(0, 5e-4, time.size)
    flux[1450:1500] -= 5e-3  # low points right at the gap boundary
    assert BoxMatchedFilter().search(time, flux) == []


def test_scatter_stripe_is_rejected():
    # A high-scatter patch with a slightly low mean: the box picks it (high SNR),
    # but it scatters strongly ABOVE baseline too -> not a coherent transit.
    time = _time_axis(n=3000)
    rng = np.random.default_rng(11)
    flux = 1.0 + rng.normal(0, 5e-4, time.size)
    s0, s1 = 1450, 1560
    flux[s0:s1] = 1.0 - 2e-3 + rng.normal(0, 5e-3, s1 - s0)  # low mean, huge scatter
    assert BoxMatchedFilter().search(time, flux) == []


def test_gap_flanking_ramp_is_rejected():
    # A momentum-dump-style ramp on the near side of a gap (not spanning it) —
    # the sweep's dominant FP at Sector 14's mid-sector gap. Must be trimmed.
    dt = 2.0 / (60 * 24)
    seg = np.arange(1500) * dt
    time = np.concatenate([seg, seg[-1] + 1.0 + np.arange(1500) * dt])  # 1-day gap
    rng = np.random.default_rng(9)
    flux = 1.0 + rng.normal(0, 5e-4, time.size)
    flux[1470:1500] = np.linspace(1.0, 0.994, 30)  # ramp down INTO the gap
    assert BoxMatchedFilter().search(time, flux) == []


def test_transit_in_continuous_data_survives_gap_guard():
    # Same dip, no gap -> box span matches expectation -> kept.
    dt = 2.0 / (60 * 24)
    time = np.arange(3000) * dt
    rng = np.random.default_rng(8)
    flux = 1.0 + rng.normal(0, 5e-4, time.size)
    c = time.size // 2
    flux[c - 360 : c + 360] -= 5e-3
    assert len(BoxMatchedFilter().search(time, flux)) == 1


def test_edge_ramp_is_not_a_candidate():
    # Start-of-sector ramp (no real transit) must NOT fire — the S26 false-positive bug.
    time = _time_axis()
    flux = np.ones(time.size)
    ramp = 300
    flux[:ramp] = np.linspace(0.995, 1.0, ramp)  # rising ramp at the left edge
    rng = np.random.default_rng(2)
    flux += rng.normal(0.0, 5e-4, size=time.size)
    assert BoxMatchedFilter().search(time, flux) == []


def test_short_light_curve_is_safe():
    assert BoxMatchedFilter().search(np.arange(4.0), np.ones(4)) == []


def test_zero_scatter_is_safe():
    # A perfectly flat curve has sigma 0 — must not divide by zero.
    time = _time_axis(n=500)
    assert BoxMatchedFilter().search(time, np.ones(time.size)) == []
