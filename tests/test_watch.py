"""Watcher tests — pure state/selection logic + resumable orchestration."""

from pathlib import Path

from monohunter import watch as W
from monohunter.record import FindRecord


def _rec(tic, known=False):
    return FindRecord(
        tic=tic, sector=14, cadence_s=120, event_time_btjd=1.0, depth_ppt=2.0,
        duration_hr=10.0, snr=15.0, detrend_method="biweight", detrend_window_d=3.0,
        tool_version="0", known_toi_match=known,
        known_toi_id="TOI-x" if known else None,
    )


def test_pending_targets_excludes_processed_and_caps():
    state = {"processed": {"14": [1, 2]}}
    assert W.pending_targets(state, 14, [1, 2, 3, 4, 5], 2) == [3, 4]
    assert W.pending_targets(state, 14, [1, 2], None) == []


def test_state_roundtrip(tmp_path):
    sp = tmp_path / "s.json"
    state = W.load_state(sp)
    assert state == {"processed": {}}
    W.mark_processed(state, 14, [1, 2])
    W.save_state(sp, state)
    assert set(W.load_state(sp)["processed"]["14"]) == {1, 2}


def test_watch_collects_novel_and_resumes(tmp_path):
    pool = [10, 20, 30]

    def runner(tic):
        return [_rec(tic, known=(tic == 20))]   # 20 is a known TOI; 10/30 novel

    sp, out = str(tmp_path / "state.json"), str(tmp_path / "out")

    r1 = W.watch(14, outdir=out, state_path=sp, max_targets=2, target_pool=pool, runner=runner)
    assert r1.scanned == 2
    assert {n.tic for n in r1.novel} == {10}          # 20 (known) excluded
    assert r1.remaining == 1
    assert (Path(out) / "tic10_s14.json").exists()
    assert not (Path(out) / "tic20_s14.json").exists()  # known not written

    # resume: second run picks up the remaining target only
    r2 = W.watch(14, outdir=out, state_path=sp, max_targets=2, target_pool=pool, runner=runner)
    assert r2.scanned == 1
    assert {n.tic for n in r2.novel} == {30}
    assert r2.remaining == 0


def test_runner_error_is_skipped_not_fatal(tmp_path):
    def runner(tic):
        if tic == 10:
            raise RuntimeError("network blip")
        return [_rec(tic)]

    res = W.watch(
        14, outdir=str(tmp_path / "o"), state_path=str(tmp_path / "s.json"),
        max_targets=5, target_pool=[10, 20], runner=runner,
    )
    assert res.scanned == 2                     # both marked processed
    assert {n.tic for n in res.novel} == {20}   # 10 errored -> skipped


def test_cli_watch_wires(tmp_path, monkeypatch, capsys):
    from monohunter import cli

    monkeypatch.setattr(W, "sector_targets", lambda s: [10, 20])
    monkeypatch.setattr(W, "run_target", lambda tic, **k: [_rec(tic, known=False)])

    rc = cli.main([
        "watch", "--sector", "14", "--max", "5",
        "--out", str(tmp_path / "o"), "--state", str(tmp_path / "st.json"),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sector 14" in out
    assert "NOVEL" in out
