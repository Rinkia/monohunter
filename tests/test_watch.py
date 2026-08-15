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


def test_workers_parallel_matches_serial_and_saves_all(tmp_path):
    import threading
    import time

    pool = list(range(10, 100, 10))  # 9 targets

    threads_used = set()

    def runner(tic):
        threads_used.add(threading.get_ident())
        time.sleep(0.02)                       # force overlap so >1 thread runs
        return [_rec(tic, known=(tic == 50))]  # 50 is a known TOI

    sp, out = str(tmp_path / "s.json"), str(tmp_path / "o")
    res = W.watch(
        14, outdir=out, state_path=sp, max_targets=99,
        target_pool=pool, runner=runner, workers=4,
    )

    assert res.scanned == len(pool)
    assert {n.tic for n in res.novel} == set(pool) - {50}   # same set as serial
    assert len(threads_used) > 1                            # actually parallel
    # every target committed to state -> nothing re-scanned on resume
    assert set(W.load_state(sp)["processed"]["14"]) == set(pool)
    assert res.remaining == 0


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


def test_cli_watch_auto_detects_newest_sector(tmp_path, monkeypatch, capsys):
    from monohunter import cli

    seen = {}
    monkeypatch.setattr(W, "latest_sector", lambda hint=1: 42)
    monkeypatch.setattr(W, "sector_targets", lambda s: [10])

    def spy_run_target(tic, **k):
        seen["sectors"] = k.get("sectors")
        return []

    monkeypatch.setattr(W, "run_target", spy_run_target)

    rc = cli.main([
        "watch", "--out", str(tmp_path / "o"), "--state", str(tmp_path / "st.json"),
    ])  # no --sector
    assert rc == 0
    assert seen["sectors"] == [42]                       # auto-detected sector used
    assert "auto-detected newest sector: 42" in capsys.readouterr().out


def test_cli_watch_ffi_threads_source(tmp_path, monkeypatch):
    from monohunter import cli

    seen = {}

    def spy_run_target(tic, **k):
        seen["source"] = k.get("source")
        return []

    monkeypatch.setattr(W, "sector_targets", lambda s: [10])
    monkeypatch.setattr(W, "run_target", spy_run_target)

    cli.main([
        "watch", "--sector", "14", "--ffi",
        "--out", str(tmp_path / "o"), "--state", str(tmp_path / "st.json"),
    ])
    assert seen["source"] == "ffi"


def test_csv_log_and_error_retry(tmp_path):
    """csv_log writes a status row per star; errored stars are NOT marked
    processed, so the next run retries them (no manual clean/retry)."""
    import csv

    calls = {"n": 0}

    def runner(tic):
        # tic 2 fails the first time, succeeds on retry; 1 novel, 3 clean
        if tic == 1:
            return [_rec(1)]
        if tic == 3:
            return []
        if tic == 2:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient MAST")
            return [_rec(2)]
        return []

    log = tmp_path / "sweep.csv"
    state = tmp_path / "state.json"
    kw = dict(outdir=str(tmp_path / "out"), state_path=str(state),
              target_pool=[1, 2, 3], runner=runner, csv_log=str(log), max_targets=10)

    r1 = W.watch(14, **kw)
    assert r1.errors == 1 and len(r1.novel) == 1        # tic2 errored, tic1 novel
    rows1 = list(csv.DictReader(open(log)))
    assert {r["tic"]: r["status"] for r in rows1} == {"1": "novel", "2": "error", "3": "none"}

    r2 = W.watch(14, **kw)                               # retry run
    assert r2.scanned == 1 and r2.errors == 0           # only the errored tic2 retried
    statuses = [r["status"] for r in csv.DictReader(open(log)) if r["tic"] == "2"]
    assert statuses == ["error", "novel"]               # retried and succeeded
