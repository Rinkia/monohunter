"""ML triage classifier — rank sweep survivors by P(worth a human's eyes).

The end of the roadmap: a sweep leaves a handful of survivors and a human vets
them by PNG. Most are the same low-SNR edge/gap junk; the real finds are deep,
high-SNR, and mid-sector. A classifier learns that boundary from labelled
examples (the crowd-vetting exports, seeded here by hand-vetted sweep survivors)
and orders new survivors so the promising ones surface first — the crowd's time
goes to candidates, not junk.

    labelled survivors -> features -> LogisticRegression -> P(interesting)
    new survivors      -> features -> model.predict       -> ranked queue

Deliberately a small, interpretable model on a handful of record features: the
FP classes separate cleanly, and with few labels a linear model is honest where
a deep net would overfit. It improves as labels/ fills from real vetting.

extract_features is pure and unit-tested; training/scoring wrap scikit-learn.
"""

from __future__ import annotations

import csv
import glob
import json
from pathlib import Path

import numpy as np

# Sector-14 systematic times (BTJD): start-of-sector ramp, mid-sector downlink
# gap (~1696), end-of-sector ramp. Legacy FALLBACK only — used to derive an
# edge/gap distance for old records/CSVs that predate the edge_gap_dist_d field.
# New records carry edge_gap_dist_d directly (general, per-sector), so the model
# transfers across sectors without this hardcode.
S14_SYSTEMATIC_TIMES = (1683.4, 1696.0, 1710.5)

FEATURE_NAMES = (
    "log_snr", "log_depth_ppt", "duration_hr",
    "likely_eb", "period_constrained", "edge_gap_dist_d", "log_baseline_scatter",
)


def _legacy_edge_gap(event_time_btjd: float) -> float:
    """Edge/gap distance from S14 systematic times — the fallback when a record/row
    has no edge_gap_dist_d (the S14 systematics ARE the sector edges + mid-gap, so
    this equals the general feature for the S14 training set)."""
    return min(abs(float(event_time_btjd) - t) for t in S14_SYSTEMATIC_TIMES)


def extract_features(
    snr: float,
    depth_ppt: float,
    duration_hr: float,
    likely_eb: bool | None,
    period_constrained: bool | None,
    edge_gap_dist_d: float,
    baseline_scatter_ppt: float | None,
) -> np.ndarray:
    """Feature vector for one candidate. Pure and deterministic.

    edge_gap_dist_d: distance to the nearest sector edge/gap (general FP tell).
    baseline_scatter_ppt: robust per-cadence scatter (faint/noisy-star tell);
    None -> neutral 0 (older data without the field).
    """
    scatter = float(baseline_scatter_ppt) if baseline_scatter_ppt else 0.0
    return np.array([
        np.log10(max(float(snr), 1e-3)),
        np.log10(max(float(depth_ppt), 1e-3)),
        float(duration_hr),
        1.0 if likely_eb else 0.0,
        1.0 if period_constrained else 0.0,
        float(edge_gap_dist_d),
        np.log10(max(scatter, 1e-3)),
    ], dtype=float)


def _features_from_row(row: dict) -> np.ndarray | None:
    try:
        # edge_gap_dist_d / baseline_scatter from the CSV when present (new sweeps),
        # else fall back to the S14-systematic proximity / neutral scatter (old CSVs).
        edge_gap = row.get("edge_gap_dist_d")
        edge_gap_d = float(edge_gap) if edge_gap not in (None, "", "None") \
            else _legacy_edge_gap(float(row["event_time_btjd"]))
        scatter = row.get("baseline_scatter_ppt")
        scatter_ppt = float(scatter) if scatter not in (None, "", "None") else None
        return extract_features(
            snr=float(row["best_snr"]),
            depth_ppt=float(row["best_depth_ppt"]),
            duration_hr=float(row["best_duration_hr"]),
            likely_eb=float(row["best_depth_ppt"]) > 30.0,   # CSV lacks the flag; depth proxy
            period_constrained=True,                          # CSV lacks it; neutral
            edge_gap_dist_d=edge_gap_d,
            baseline_scatter_ppt=scatter_ppt,
        )
    except (KeyError, ValueError):
        return None


def load_training_data(sweeps_dir: str | Path, labels_csv: str | Path):
    """Join hand/crowd labels (tic,label with label 1=interesting/0=junk) with the
    survivor rows across every sweep CSV. Returns (X, y, tics)."""
    labels: dict[int, int] = {}
    with open(labels_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                labels[int(row["tic"])] = int(row["label"])
            except (KeyError, ValueError):
                continue

    X, y, tics = [], [], []
    seen: set[int] = set()
    for path in sorted(glob.glob(str(Path(sweeps_dir) / "*.csv"))):
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    tic = int(row["tic"])
                except (KeyError, ValueError):
                    continue
                if tic not in labels or tic in seen:
                    continue
                feat = _features_from_row(row)
                if feat is None:
                    continue
                X.append(feat)
                y.append(labels[tic])
                tics.append(tic)
                seen.add(tic)
    return np.array(X), np.array(y), tics


def train(X: np.ndarray, y: np.ndarray):
    """Fit a standardized logistic-regression triage model. Returns the pipeline."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(class_weight="balanced", max_iter=1000),
    )
    model.fit(X, y)
    return model


def cross_val_accuracy(X: np.ndarray, y: np.ndarray) -> float:
    """Leave-one-out accuracy — honest for a small labelled set."""
    from sklearn.model_selection import LeaveOneOut, cross_val_score

    if len(y) < 4 or len(set(y.tolist())) < 2:
        return float("nan")
    scores = cross_val_score(train(X, y), X, y, cv=LeaveOneOut())
    return float(scores.mean())


def score_record(model, rec) -> float:
    """P(interesting) for a FindRecord (or dict with the same fields)."""
    get = (lambda k: getattr(rec, k, None)) if not isinstance(rec, dict) else rec.get
    edge_gap = get("edge_gap_dist_d")
    if edge_gap is None:                                   # old record: derive from t0
        edge_gap = _legacy_edge_gap(get("event_time_btjd"))
    feat = extract_features(
        snr=get("snr"), depth_ppt=get("depth_ppt"), duration_hr=get("duration_hr"),
        likely_eb=get("likely_eb"), period_constrained=get("period_constrained"),
        edge_gap_dist_d=edge_gap, baseline_scatter_ppt=get("baseline_scatter_ppt"),
    ).reshape(1, -1)
    return float(model.predict_proba(feat)[0, 1])


def save_model(model, path: str | Path) -> None:
    import joblib

    joblib.dump(model, path)


def load_model(path: str | Path):
    import joblib

    return joblib.load(path)


def rank_candidates(model, candidates_dir: str | Path) -> list[tuple[int, int, float]]:
    """Score every record JSON in candidates_dir. Returns (tic, sector, p) sorted
    by p descending — the human vetting queue."""
    from .record import FindRecord

    out = []
    for jpath in sorted(Path(candidates_dir).glob("*.json")):
        try:
            rec = FindRecord(**json.loads(jpath.read_text(encoding="utf-8")))
        except Exception:
            continue
        out.append((rec.tic, rec.sector, score_record(model, rec)))
    out.sort(key=lambda r: -r[2])
    return out
