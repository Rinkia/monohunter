"""Novelty tests — nearest-VSX selection (pure, offline)."""

from monohunter.novelty import _nearest


def test_nearest_picks_smallest_separation():
    cands = [
        {"name": "V1", "type": "EA", "period": 2.5, "sep_arcsec": 8.0},
        {"name": "V2", "type": "RR", "period": 0.5, "sep_arcsec": 1.2},
        {"name": "V3", "type": "EW", "period": 0.3, "sep_arcsec": 4.0},
    ]
    m = _nearest(cands)
    assert m["name"] == "V2" and m["sep_arcsec"] == 1.2


def test_nearest_empty_is_none():
    assert _nearest([]) is None
