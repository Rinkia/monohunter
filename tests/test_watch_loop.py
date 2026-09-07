"""watch_loop tests — the 24/7 watcher loop, offline via injected deps."""

import monohunter.watch as W
from monohunter.watch import WatchResult, watch_loop


def _fake_watch_ok(sector, **kw):
    return WatchResult(sector=sector, scanned=5, remaining=0, novel=[], errors=0)


def test_loop_runs_bounded_cycles(monkeypatch):
    monkeypatch.setattr(W, "latest_sector", lambda hint=1: 90)
    calls = {"watch": 0, "clean": 0, "sleep": 0}

    def watch_fn(sector, **kw):
        calls["watch"] += 1
        return _fake_watch_ok(sector, **kw)

    def clean_fn(cache):
        calls["clean"] += 1
        return (0, 0)

    def sleeper(s):
        calls["sleep"] += 1

    n = watch_loop(cycles=3, sleep_s=1.0, watch_fn=watch_fn, clean_fn=clean_fn,
                   sleeper=sleeper, cache_dir="/tmp/none", log=lambda *_: None)

    assert n == 3
    assert calls["watch"] == 3
    assert calls["clean"] == 3        # prune every cycle
    assert calls["sleep"] == 2        # sleeps BETWEEN cycles, not after the last


def test_loop_survives_a_failing_cycle(monkeypatch):
    monkeypatch.setattr(W, "latest_sector", lambda hint=1: 90)
    seen = []

    def watch_fn(sector, **kw):
        seen.append(1)
        raise RuntimeError("MAST hiccup")

    n = watch_loop(cycles=2, sleep_s=0, watch_fn=watch_fn,
                   clean_fn=lambda c: (0, 0), sleeper=lambda s: None,
                   cache_dir="/tmp/none", log=lambda *_: None)

    assert n == 2                     # kept looping despite each cycle raising
    assert len(seen) == 2


def test_loop_handles_no_sector(monkeypatch):
    monkeypatch.setattr(W, "latest_sector", lambda hint=1: None)
    watched = []
    n = watch_loop(cycles=1, sleep_s=0, watch_fn=lambda s, **k: watched.append(1),
                   clean_fn=lambda c: (0, 0), sleeper=lambda s: None,
                   cache_dir="/tmp/none", log=lambda *_: None)
    assert n == 1
    assert watched == []              # no sector -> watch not called, no crash
