"""Triage tests — feature extraction (pure) + a train/predict separation check."""

import numpy as np

from monohunter.triage import (
    FEATURE_NAMES,
    S14_SYSTEMATIC_TIMES,
    extract_features,
    score_record,
    train,
)


def test_features_shape_and_systematic_proximity():
    f = extract_features(snr=100, depth_ppt=50, duration_hr=6, event_time_btjd=1696.0,
                         likely_eb=True, period_constrained=True)
    assert f.shape == (len(FEATURE_NAMES),)
    # t0 exactly on the mid-sector gap -> proximity 0
    assert f[FEATURE_NAMES.index("systematic_proximity_d")] == 0.0
    # a mid-sector event is far from every systematic time
    mid = extract_features(snr=100, depth_ppt=50, duration_hr=6, event_time_btjd=1702.0,
                           likely_eb=True, period_constrained=True)
    assert mid[FEATURE_NAMES.index("systematic_proximity_d")] > 5.0


def test_log_features_monotonic():
    lo = extract_features(7, 1, 10, 1702.0, False, False)
    hi = extract_features(300, 100, 10, 1702.0, True, True)
    assert hi[0] > lo[0]      # log_snr rises with SNR
    assert hi[1] > lo[1]      # log_depth rises with depth


def _synth(interesting, rng):
    if interesting:  # high SNR, deep, mid-sector
        return extract_features(rng.uniform(40, 400), rng.uniform(30, 150), rng.uniform(3, 9),
                                rng.uniform(1700, 1705), True, True)
    # low SNR, shallow, near a systematic time
    return extract_features(rng.uniform(7, 12), rng.uniform(0.4, 2.0), rng.uniform(15, 40),
                            rng.choice([1683.5, 1695.6, 1709.5]), False, False)


def test_model_learns_the_separation():
    rng = np.random.default_rng(0)
    X = np.array([_synth(i % 2 == 0, rng) for i in range(60)])
    y = np.array([1 if i % 2 == 0 else 0 for i in range(60)])
    model = train(X, y)
    # a clear EB scores high, a low-SNR edge FP scores low
    eb = {"snr": 350, "depth_ppt": 100, "duration_hr": 6, "event_time_btjd": 1702.0,
          "likely_eb": True, "period_constrained": True}
    fp = {"snr": 7.5, "depth_ppt": 0.5, "duration_hr": 30, "event_time_btjd": 1695.7,
          "likely_eb": False, "period_constrained": False}
    assert score_record(model, eb) > 0.8
    assert score_record(model, fp) < 0.2
