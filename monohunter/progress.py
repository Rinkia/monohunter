"""Shared safety net for long / network runs: progress, stall warnings, watchdog.

Three layers guard a long sweep from silent stalls:

1. **Per-read timeout** — `fetch.socket.setdefaulttimeout(180)` caps every network read,
   so a single hung MAST/IRSA socket raises instead of blocking forever. (Lives in
   fetch.py; the base layer under everything here.)
2. **Per-step progress + stall warning** — `ProgressReporter` prints one line per step
   with elapsed/ETA and flags a step that runs longer than `slow_after_s` (a stall short
   of the hard timeout, e.g. a slow-but-alive download or a pathological star).
3. **Wall-clock watchdog** — `Watchdog` warns at a fraction of the cap and force-exits at
   `max_hours` for a run whose state is saved per step, so a wedged run self-heals on the
   next resume instead of idling.

ProgressReporter is pure (inject a clock + stream) and unit-tested offline; Watchdog wraps
threads + os._exit, so it is exercised structurally, not by actually firing.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Callable, TextIO

DEFAULT_SLOW_STEP_S = 120.0   # a per-item step slower than this is flagged as a stall
DEFAULT_WARN_FRAC = 0.8       # watchdog soft-warns at this fraction of max_hours


def _fmt_dt(seconds: float) -> str:
    """Compact h/m/s."""
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


class ProgressReporter:
    """Live per-step progress with elapsed/ETA and a slow-step (stall) warning.

    Call `tick(name, status)` once per completed step. A step whose wall time exceeds
    `slow_after_s` prints a `[WARN] slow step` — visible long before the hard socket
    timeout, so a slow-but-alive run is distinguishable from a wedged one.
    """

    def __init__(
        self,
        total: int,
        *,
        label: str = "items",
        slow_after_s: float = DEFAULT_SLOW_STEP_S,
        stream: TextIO | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.total = int(total)
        self.label = label
        self.slow_after_s = float(slow_after_s)
        self.stream = stream if stream is not None else sys.stdout
        self._clock = clock
        self.i = 0
        self.n_slow = 0
        self._t0 = clock()
        self._t_last = self._t0

    def tick(self, name: str, status: str = "ok") -> bool:
        """Record one finished step; print progress. Returns True if it was slow."""
        now = self._clock()
        dt = now - self._t_last
        self._t_last = now
        self.i += 1
        elapsed = now - self._t0
        eta = (elapsed / self.i) * (self.total - self.i) if self.i and self.total else 0.0
        slow = dt > self.slow_after_s
        if slow:
            self.n_slow += 1
        warn = f"  [WARN] slow step {_fmt_dt(dt)} > {_fmt_dt(self.slow_after_s)}" if slow else ""
        print(
            f"  [{self.i}/{self.total}] {name}: {status}  "
            f"({_fmt_dt(dt)}, elapsed {_fmt_dt(elapsed)}, ETA {_fmt_dt(eta)}){warn}",
            file=self.stream,
            flush=True,
        )
        return slow

    def done(self) -> None:
        """Final one-line summary."""
        elapsed = self._clock() - self._t0
        note = f", {self.n_slow} slow" if self.n_slow else ""
        print(
            f"  {self.i}/{self.total} {self.label} in {_fmt_dt(elapsed)}{note}",
            file=self.stream,
            flush=True,
        )


class Watchdog:
    """Wall-clock safety net: soft-warn at `warn_frac` of the cap, then force-exit at
    `max_hours`. For a run whose state is saved per step, a hard `os._exit` loses nothing
    and the run resumes — hitting the cap IS the "wedged / too slow" signal. Targets a
    hung socket Python can't interrupt; ordinary reads are already capped in fetch.

    Use as a context manager around the loop; timers are daemons and are cancelled on a
    clean exit. `progress()` returns a short status string embedded in the messages.
    """

    def __init__(
        self,
        max_hours: float,
        *,
        marker_path: str | None = None,
        progress: Callable[[], str] | None = None,
        warn_frac: float = DEFAULT_WARN_FRAC,
        stream: TextIO | None = None,
    ) -> None:
        self.max_hours = float(max_hours)
        self.marker_path = marker_path
        self.progress = progress or (lambda: "")
        self.warn_frac = warn_frac
        self.stream = stream if stream is not None else sys.stderr
        self._timers: list[threading.Timer] = []

    def __enter__(self) -> "Watchdog":
        secs = self.max_hours * 3600.0
        if 0.0 < self.warn_frac < 1.0:
            tw = threading.Timer(secs * self.warn_frac, self._warn)
            tw.daemon = True
            tw.start()
            self._timers.append(tw)
        tf = threading.Timer(secs, self._fire)
        tf.daemon = True
        tf.start()
        self._timers.append(tf)
        return self

    def _warn(self) -> None:
        print(
            f"[watchdog] {self.warn_frac:.0%} of max_hours={self.max_hours} elapsed; "
            f"{self.progress()}. Still running — will force-exit at the cap.",
            file=self.stream,
            flush=True,
        )

    def _fire(self) -> None:
        import os

        msg = (
            f"[watchdog] max_hours={self.max_hours} exceeded; {self.progress()}. "
            f"Forcing exit; resume to continue."
        )
        if self.marker_path:
            try:
                Path(self.marker_path).write_text(msg, encoding="utf-8")
            except Exception:
                pass
        print(msg, file=self.stream, flush=True)
        os._exit(2)

    def __exit__(self, *exc: object) -> bool:
        for t in self._timers:
            t.cancel()
        return False
