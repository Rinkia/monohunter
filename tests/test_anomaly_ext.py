"""Extended anomaly detector tests — pure, offline. Realistic sector-length curves."""

import numpy as np

from monohunter.anomaly_ext import (
    anomaly_score,
    find_deep_dimming,
    find_heartbeat,
    find_outbursts,
    fold_skew,
    pulsator_subclass,
)

CAD_D = 2.0 / (60 * 24)      # 2-min cadence in days


def _time(n=15000):
    return np.arange(n) * CAD_D


def _box(time, t0, depth_frac, dur_hr):
    half = (dur_hr / 24.0) / 2.0
    dip = np.zeros_like(time)
    dip[np.abs(time - t0) <= half] = -depth_frac
    return dip


# ---- 1. deep irregular dimming -------------------------------------------

def test_deep_dimming_flags_deep_aperiodic_dips():
    t = _time()
    rng = np.random.default_rng(0)
    flux = 1.0 + rng.normal(0, 5e-4, t.size)  # noise so the box SNR is finite
    for t0 in (5.0, 9.0, 16.0):               # irregular spacing (4, 7 d), within baseline
        flux += _box(t, t0, 0.05, 6.0)        # 5% deep, 6 h wide
    res = find_deep_dimming(t, flux)
    assert res.is_deep_dipper is True
    assert res.n_dips >= 2
    assert res.max_depth_ppt >= 30.0


def test_deep_dimming_ignores_quiet_star():
    t = _time()
    rng = np.random.default_rng(0)
    flux = 1.0 + rng.normal(0, 3e-4, t.size)
    res = find_deep_dimming(t, flux)
    assert res.is_deep_dipper is False


# ---- 2. heartbeat --------------------------------------------------------

def test_heartbeat_flags_localized_bipolar_pulse():
    t = _time()
    period = 3.0
    ph = (t / period) % 1.0
    sig = 0.04
    g = np.exp(-((ph - 0.5) / sig) ** 2 / 2)
    pulse = -(ph - 0.5) / sig * g                       # smooth + then - = bipolar
    rng = np.random.default_rng(0)
    flux = 1.0 + 0.012 * pulse + rng.normal(0, 3e-4, t.size)
    res = find_heartbeat(t, flux)
    assert res.is_heartbeat is True
    assert res.bipolar is True
    assert abs(res.period_d - period) < 0.3


def test_heartbeat_rejects_pure_sinusoid():
    t = _time()
    rng = np.random.default_rng(1)
    flux = 1.0 + 0.01 * np.sin(2 * np.pi * t / 3.0) + rng.normal(0, 3e-4, t.size)
    res = find_heartbeat(t, flux)
    assert res.is_heartbeat is False        # sinusoid isn't phase-localized


# ---- 3. pulsator subclass ------------------------------------------------

def test_pulsator_subclass_rules():
    assert pulsator_subclass(0.5, 120.0, 0.6) == "rr_lyrae"      # large-amp, skewed, RRL band
    assert pulsator_subclass(0.1, 5.0, 0.0) == "delta_scuti"     # fast
    assert pulsator_subclass(1.5, 4.0, 0.0) == "gamma_dor"       # slow g-mode
    assert pulsator_subclass(0.5, 5.0, 0.0) == "gamma_dor"       # RRL band but low amp -> g-mode band
    assert pulsator_subclass(5.0, 4.0, 0.0) == "pulsator"        # outside every named band
    assert pulsator_subclass(None, 100.0, 1.0) == "pulsator"


def test_fold_skew_sawtooth_vs_sine():
    t = _time()
    p = 0.6
    ph = (t / p) % 1.0
    spike = np.maximum(0.0, 1.0 - ph / 0.2)      # narrow peak: mostly low, few high -> skewed
    sine = np.sin(2 * np.pi * ph)
    assert abs(fold_skew(t, sine, p)) < 0.2
    assert abs(fold_skew(t, spike, p)) > 0.2


# ---- 4. outbursts --------------------------------------------------------

def test_outburst_flags_sustained_brightening():
    t = _time()
    flux = 1.0 + np.random.default_rng(1).normal(0, 1e-3, t.size)
    burst = (t >= 10.0) & (t <= 11.0)            # 1-day plateau, +50%
    flux[burst] += 0.5
    events = find_outbursts(t, flux)
    assert len(events) == 1
    assert events[0].duration_hr >= 6.0
    assert events[0].amplitude_ppt > 100.0


def test_outburst_ignores_short_flare():
    t = _time()
    flux = 1.0 + np.random.default_rng(2).normal(0, 1e-3, t.size)
    spike = np.abs(t - 5.0) <= (1.0 / 24.0)      # ~2 h, too short for an outburst
    flux[spike] += 0.5
    assert find_outbursts(t, flux) == []


# ---- 5. generalized anomaly score ----------------------------------------

def test_anomaly_score_quiet_is_low_weird_is_high():
    t = _time()
    quiet = 1.0 + np.random.default_rng(3).normal(0, 3e-4, t.size)
    s_quiet = anomaly_score(t, quiet, quiet)
    assert s_quiet.score < 0.15

    weird = quiet.copy()
    weird[(t >= 10.0) & (t <= 11.5)] += 0.5      # an outburst
    weird += 0.02 * np.sin(2 * np.pi * t / 2.0)  # plus variability
    s_weird = anomaly_score(t, weird, weird)
    assert s_weird.score > s_quiet.score
    assert set(s_weird.components) >= {"variability", "outbursts", "flares"}
