"""Triage tests — feature extraction (pure) + a train/predict separation check."""

import numpy as np

from monohunter.triage import (
    FEATURE_NAMES,
    _legacy_edge_gap,
    extract_features,
    score_record,
    train,
)


def _feat(snr, depth, dur, likely_eb, pconstr, edge_gap, scatter):
    return extract_features(snr, depth, dur, likely_eb, pconstr, edge_gap, scatter)


def test_features_shape_and_edge_gap():
    f = _feat(100, 50, 6, True, True, edge_gap=0.0, scatter=0.5)
    assert f.shape == (len(FEATURE_NAMES),)
    assert f[FEATURE_NAMES.index("edge_gap_dist_d")] == 0.0        # on an edge/gap
    mid = _feat(100, 50, 6, True, True, edge_gap=6.0, scatter=0.5)
    assert mid[FEATURE_NAMES.index("edge_gap_dist_d")] == 6.0      # mid-sector, far


def test_log_features_monotonic():
    lo = _feat(7, 1, 10, False, False, 6.0, 0.5)
    hi = _feat(300, 100, 10, True, True, 6.0, 0.5)
    assert hi[0] > lo[0]      # log_snr rises with SNR
    assert hi[1] > lo[1]      # log_depth rises with depth
    # log_baseline_scatter rises with scatter
    assert _feat(100, 5, 6, False, True, 6, 30)[-1] > _feat(100, 5, 6, False, True, 6, 0.5)[-1]


def test_legacy_edge_gap_matches_s14_systematics():
    assert _legacy_edge_gap(1696.0) == 0.0        # on the mid-sector gap
    assert _legacy_edge_gap(1702.0) > 5.0         # mid-sector, far from any systematic


def _synth(interesting, rng):
    if interesting:  # high SNR, deep, mid-sector (large edge_gap), quiet baseline
        return _feat(rng.uniform(40, 400), rng.uniform(30, 150), rng.uniform(3, 9),
                     True, True, rng.uniform(4, 8), rng.uniform(0.3, 1.5))
    # low SNR, shallow, near an edge/gap (small edge_gap), noisy baseline
    return _feat(rng.uniform(7, 12), rng.uniform(0.4, 2.0), rng.uniform(15, 40),
                 False, False, rng.uniform(0.0, 0.6), rng.uniform(10, 60))


def test_model_learns_the_separation():
    rng = np.random.default_rng(0)
    X = np.array([_synth(i % 2 == 0, rng) for i in range(60)])
    y = np.array([1 if i % 2 == 0 else 0 for i in range(60)])
    model = train(X, y)
    # a clean mid-sector EB scores high; a low-SNR noisy edge FP scores low
    eb = {"snr": 350, "depth_ppt": 100, "duration_hr": 6, "likely_eb": True,
          "period_constrained": True, "edge_gap_dist_d": 6.0, "baseline_scatter_ppt": 0.8}
    fp = {"snr": 7.5, "depth_ppt": 0.5, "duration_hr": 30, "likely_eb": False,
          "period_constrained": False, "edge_gap_dist_d": 0.1, "baseline_scatter_ppt": 40.0}
    assert score_record(model, eb) > 0.8
    assert score_record(model, fp) < 0.2


def test_score_record_falls_back_when_edge_gap_missing():
    # an old record dict without edge_gap_dist_d still scores (derived from t0)
    rng = np.random.default_rng(1)
    X = np.array([_synth(i % 2 == 0, rng) for i in range(60)])
    y = np.array([1 if i % 2 == 0 else 0 for i in range(60)])
    model = train(X, y)
    old = {"snr": 7.5, "depth_ppt": 0.5, "duration_hr": 30, "likely_eb": False,
           "period_constrained": False, "event_time_btjd": 1695.7}  # near S14 gap
    assert 0.0 <= score_record(model, old) <= 1.0                    # no crash, valid prob
