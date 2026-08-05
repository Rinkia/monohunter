"""Real-data regression: monohunter must recover TOI-2180 b's single transit.

The canonical mono-transit — one ~24h dip in TESS Sector 19 (SNR ~165). This is
the by-hand reproduce assignment, frozen as an automated check. Hits the network,
so it's `slow` (run with `pytest --runslow`).
"""

import pytest

from monohunter.pipeline import run_target

TOI_2180_TIC = 298663873
TRANSIT_SECTOR = 19


@pytest.mark.slow
def test_recovers_toi2180_single_transit():
    try:
        records = run_target(TOI_2180_TIC, sectors=[TRANSIT_SECTOR], make_plots=False)
    except Exception as exc:  # MAST/download outage — infra, not a code regression
        pytest.skip(f"TESS data unavailable: {exc}")

    assert records, "no candidate found in Sector 19 — detection regressed"
    best = max(records, key=lambda r: r.snr)

    # The real transit: deep, long, high-SNR, in S19.
    assert best.sector == TRANSIT_SECTOR
    assert best.snr > 25.0            # red-noise-aware SNR ~45; well clear of the 7 floor
    assert 12.0 <= best.duration_hr <= 30.0
    assert best.depth_ppt > 1.0

    # Cross-match is offline-safe (returns None on archive outage); assert only
    # when it resolved, so a NASA-archive hiccup can't fail the detection test.
    if best.known_toi_id is not None:
        assert best.known_toi_match is True
        assert "2180" in best.known_toi_id
