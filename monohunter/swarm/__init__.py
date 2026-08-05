"""Swarm — aggregate many community find-records into one ranked leaderboard.

Phase 1 (this): a static aggregator over the contributions/ PR flow. No live
server — reads submitted JSON, dedups by (tic, sector), ranks by novelty +
cross-submitter agreement + SNR, renders JSON + a static HTML dashboard.
A live coordination server (target hand-out) is a later increment, justified
only once there is contention between many simultaneous searchers.
"""

from .aggregate import AggregatedCandidate, aggregate, load_records, render_html, render_json

__all__ = [
    "AggregatedCandidate",
    "aggregate",
    "load_records",
    "render_html",
    "render_json",
]
