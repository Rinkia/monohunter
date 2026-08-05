"""Swarm aggregator — grouping, consensus, novelty ranking, rendering."""

import json

from monohunter.record import FindRecord
from monohunter.swarm import aggregate, load_records, render_html, render_json


def _rec(tic, sector, snr, known=False, toi=None, depth=4.0, dur=24.0):
    return FindRecord(
        tic=tic,
        sector=sector,
        cadence_s=120,
        event_time_btjd=1830.0,
        depth_ppt=depth,
        duration_hr=dur,
        snr=snr,
        detrend_method="biweight",
        detrend_window_d=3.0,
        tool_version="0.1.0",
        known_toi_match=known,
        known_toi_id=toi,
    )


def _write(root, user, rec):
    d = root / "contributions" / user
    d.mkdir(parents=True, exist_ok=True)
    (d / f"tic{rec.tic}_s{rec.sector}.json").write_text(rec.to_json(), encoding="utf-8")


def test_groups_by_tic_sector_across_submitters(tmp_path):
    _write(tmp_path, "alice", _rec(111, 5, 20))
    _write(tmp_path, "bob", _rec(111, 5, 30))
    cands = aggregate(load_records(tmp_path / "contributions"))
    assert len(cands) == 1
    c = cands[0]
    assert c.n_submitters == 2
    assert c.submitters == ["alice", "bob"]
    assert c.best_snr == 30  # max across submitters


def test_ranks_novel_and_consensus_first(tmp_path):
    _write(tmp_path, "alice", _rec(200, 1, 50, known=True, toi="TOI-1"))  # known, high SNR
    _write(tmp_path, "alice", _rec(300, 1, 10))  # novel, 1 submitter
    _write(tmp_path, "bob", _rec(300, 1, 12))    # novel, 2nd submitter -> consensus

    cands = aggregate(load_records(tmp_path / "contributions"))
    assert cands[0].tic == 300 and cands[0].n_submitters == 2 and cands[0].novel
    assert cands[-1].tic == 200 and not cands[-1].novel


def test_render_json_and_html(tmp_path):
    _write(tmp_path, "alice", _rec(111, 5, 20))
    cands = aggregate(load_records(tmp_path / "contributions"))

    j = json.loads(render_json(cands))
    assert j["count"] == 1
    assert j["candidates"][0]["tic"] == 111
    assert j["candidates"][0]["novel"] is True

    h = render_html(cands)
    assert "111" in h
    assert "NEW" in h  # novel badge


def test_skips_invalid_json(tmp_path):
    d = tmp_path / "contributions" / "alice"
    d.mkdir(parents=True)
    (d / "bad.json").write_text("{not valid", encoding="utf-8")
    (d / "tic111_s5.json").write_text(_rec(111, 5, 20).to_json(), encoding="utf-8")
    assert len(load_records(tmp_path / "contributions")) == 1


def test_empty_dir_renders_placeholder(tmp_path):
    (tmp_path / "contributions").mkdir()
    cands = aggregate(load_records(tmp_path / "contributions"))
    assert cands == []
    assert "No candidates yet" in render_html(cands)
