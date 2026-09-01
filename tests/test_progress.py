"""ProgressReporter + Watchdog tests — pure, offline (injected clock + stream)."""

import io

from monohunter.progress import ProgressReporter, Watchdog, _fmt_dt


class _Clock:
    """Deterministic monotonic clock: advance() to control step timing."""

    def __init__(self):
        self.t = 0.0

    def advance(self, dt):
        self.t += dt

    def __call__(self):
        return self.t


def test_progress_counts_and_reports_eta():
    clk = _Clock()
    out = io.StringIO()
    pr = ProgressReporter(4, label="stars", slow_after_s=100, stream=out, clock=clk)
    for name in ("a", "b"):
        clk.advance(10)
        pr.tick(name, "used")
    text = out.getvalue()
    assert "[1/4] a: used" in text
    assert "[2/4] b: used" in text
    assert "ETA" in text
    assert "[WARN]" not in text          # 10s steps are not slow


def test_progress_flags_slow_step():
    clk = _Clock()
    out = io.StringIO()
    pr = ProgressReporter(3, slow_after_s=100, stream=out, clock=clk)
    clk.advance(30)
    assert pr.tick("fast") is False
    clk.advance(200)                      # a stall
    assert pr.tick("slow") is True
    assert "[WARN] slow step" in out.getvalue()
    assert pr.n_slow == 1


def test_progress_done_summary_notes_slow():
    clk = _Clock()
    out = io.StringIO()
    pr = ProgressReporter(1, label="stars", slow_after_s=1, stream=out, clock=clk)
    clk.advance(5)
    pr.tick("x")
    pr.done()
    assert "1/1 stars" in out.getvalue()
    assert "1 slow" in out.getvalue()


def test_watchdog_arms_and_cancels_without_firing():
    # max_hours huge -> neither timer fires during the test; __exit__ cancels both.
    out = io.StringIO()
    with Watchdog(1000.0, progress=lambda: "0/10", stream=out) as wd:
        assert len(wd._timers) == 2       # warn timer + fire timer armed
    assert out.getvalue() == ""           # nothing fired during the run
    # after __exit__ the timers are cancelled: none fires later
    import time as _t
    _t.sleep(0.05)
    assert out.getvalue() == ""


def test_watchdog_fires_and_writes_marker(tmp_path, monkeypatch):
    import os as _os
    import time

    fired = {}

    def fake_exit(code):
        fired["code"] = code       # record instead of exiting; _fire then returns cleanly

    monkeypatch.setattr(_os, "_exit", fake_exit)
    marker = tmp_path / "s.json.watchdog"
    wd = Watchdog(0.0002, marker_path=str(marker), progress=lambda: "0/1", stream=io.StringIO())
    wd.__enter__()                 # ~0.72s cap; fire timer runs before we exit
    time.sleep(1.0)
    wd.__exit__()
    assert fired.get("code") == 2
    assert marker.exists()          # deadline marker written


def test_fmt_dt():
    assert _fmt_dt(30) == "30s"
    assert _fmt_dt(120) == "2m"
    assert _fmt_dt(7200) == "2.0h"
