"""Fresh-data watcher — be first to process a TESS sector.

Institutional pipelines take weeks-to-months to vet a new sector; a scheduler
running `monohunter watch --sector N` every few hours processes the sector's
targets incrementally and surfaces not-yet-known candidates first.

Resumable: state tracks which TICs are done, so each scheduled run continues
where the last stopped and a crash loses nothing. The state/selection logic is
pure and unit-tested; the network bits (target enumeration, per-target scan) are
injectable.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .fetch import search_tess  # noqa: F401  (re-exported convenience)
from .pipeline import run_target
from .progress import ProgressReporter, Watchdog
from .record import FindRecord


# ---- pure state + selection (unit-tested) --------------------------------

def load_state(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"processed": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"processed": {}}


def save_state(path: str | Path, state: dict) -> None:
    Path(path).write_text(json.dumps(state), encoding="utf-8")


def pending_targets(state: dict, sector: int, all_tics: list[int], max_n: int | None) -> list[int]:
    """TICs of `sector` not yet processed, capped at max_n (None = all)."""
    done = set(state.get("processed", {}).get(str(sector), []))
    todo = [int(t) for t in all_tics if int(t) not in done]
    return todo[:max_n] if max_n else todo


def mark_processed(state: dict, sector: int, tics: list[int]) -> None:
    bucket = state.setdefault("processed", {}).setdefault(str(sector), [])
    bucket.extend(int(t) for t in tics)


# ---- enumeration (network) -----------------------------------------------

def sector_targets(sector: int) -> list[int]:
    """All 2-min SPOC TIC ids observed in a sector."""
    from astroquery.mast import Observations

    obs = Observations.query_criteria(
        obs_collection="TESS", dataproduct_type="timeseries",
        sequence_number=sector, t_exptime=120,
    )
    return sorted({int(t) for t in obs["target_name"] if str(t).isdigit()})


def latest_sector(hint: int = 1, max_probe: int = 300) -> int | None:
    """Best-effort newest sector with data, probing upward from `hint`.

    The scheduler should pass a hint near the current sector so this is cheap.
    """
    last = None
    sec = max(1, hint)
    while sec <= max_probe:
        try:
            has = len(sector_targets(sec)) > 0
        except Exception:
            has = False
        if has:
            last, sec = sec, sec + 1
        else:
            break
    return last


# ---- orchestrator --------------------------------------------------------

@dataclass
class WatchResult:
    sector: int
    scanned: int
    remaining: int
    novel: list[FindRecord] = field(default_factory=list)
    errors: int = 0


# Per-star provenance log columns (the sweep CSV schema). Written when csv_log is
# set so a full sweep leaves a status row per star (none/novel/error), not just
# the candidate JSONs — the record retries and catalogs build from.
_CSV_FIELDS = ["tic", "sector", "status", "best_snr", "best_depth_ppt",
               "best_duration_hr", "event_time_btjd", "known_toi_id",
               "edge_gap_dist_d", "baseline_scatter_ppt"]


def _append_csv_row(csv_log: str, sector: int, tic: int, status: str,
                    recs: list[FindRecord]) -> None:
    import csv as _csv

    new = not os.path.exists(csv_log) or os.path.getsize(csv_log) == 0
    row = {k: "" for k in _CSV_FIELDS}
    row["tic"], row["sector"], row["status"] = tic, sector, status
    if recs:
        best = max(recs, key=lambda r: r.snr)
        row["best_snr"] = f"{best.snr:.2f}"
        row["best_depth_ppt"] = f"{best.depth_ppt:.3f}"
        row["best_duration_hr"] = f"{best.duration_hr:.2f}"
        row["event_time_btjd"] = f"{best.event_time_btjd:.4f}"
        row["known_toi_id"] = best.known_toi_id or ""
        if best.edge_gap_dist_d is not None:
            row["edge_gap_dist_d"] = f"{best.edge_gap_dist_d:.4f}"
        if best.baseline_scatter_ppt is not None:
            row["baseline_scatter_ppt"] = f"{best.baseline_scatter_ppt:.4f}"
    with open(csv_log, "a", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def watch(
    sector: int,
    outdir: str = "watch_out",
    state_path: str = "watch_state.json",
    max_targets: int = 50,
    target_pool: list[int] | None = None,
    runner: Callable[[int], list[FindRecord]] | None = None,
    source: str = "spoc",
    workers: int = 1,
    summaries_dir: str | None = None,
    csv_log: str | None = None,
    max_hours: float | None = None,
    show_progress: bool = False,
    slow_after_s: float = 120.0,
) -> WatchResult:
    """Process the next `max_targets` un-scanned TICs of `sector`. Resumable.

    Writes each not-known-TOI candidate's record to outdir; updates state after
    every target so a crash never re-scans or loses work.

    source: "spoc" (pre-made light curves) or "ffi" (extract from Full-Frame
    Images). NOTE the default pool (`sector_targets`) enumerates 2-min SPOC TICs;
    FFI mode is most useful with an injected `target_pool` of stars that LACK
    SPOC data (there's no cheap MAST query for the full FFI star pool — deferred).

    workers: parallel MAST downloads. The per-target work is network-bound, so a
    thread pool cuts wall-clock ~linearly up to MAST's rate limit (keep it modest,
    4-8). State writes stay single-threaded (results are consumed on the main
    thread as each future lands), so resumability is preserved without a lock.
    """
    os.makedirs(outdir, exist_ok=True)
    run = runner or (
        lambda tic: run_target(
            tic, sectors=[sector], make_plots=False, outdir=outdir, source=source,
            summaries_dir=summaries_dir,
        )
    )
    tics = target_pool if target_pool is not None else sector_targets(sector)

    state = load_state(state_path)
    todo = pending_targets(state, sector, tics, max_targets)

    novel: list[FindRecord] = []
    n_errors = 0
    n_done = 0

    reporter = (
        ProgressReporter(len(todo), label="stars", slow_after_s=slow_after_s)
        if show_progress and todo else None
    )

    def consume(tic: int, recs: list[FindRecord], errored: bool) -> None:
        # Main-thread only: mutate state and write files here so nothing races.
        nonlocal n_errors, n_done
        n_done += 1
        if errored:
            # Transient failure (usually MAST): DON'T mark processed, so the next
            # run retries it automatically — no manual CSV clean/retry as with the
            # old scratchpad sweeps. ponytail: a truly-corrupt star retries every
            # run; add a per-tic attempt cap if that ever churns.
            n_errors += 1
            if csv_log:
                _append_csv_row(csv_log, sector, tic, "error", [])
            if reporter is not None:
                reporter.tick(f"TIC {tic}", "error (will retry)")
            return
        status = "none"
        for rec in recs:
            if not rec.known_toi_match:
                status = "novel"
                novel.append(rec)
                path = Path(outdir) / f"tic{rec.tic}_s{rec.sector}.json"
                path.write_text(rec.to_json(indent=2), encoding="utf-8")
        if csv_log:
            _append_csv_row(csv_log, sector, tic, status, recs)
        mark_processed(state, sector, [tic])
        save_state(state_path, state)   # incremental — resumable on crash
        if reporter is not None:
            reporter.tick(f"TIC {tic}", status)

    def safe_run(tic: int) -> tuple[list[FindRecord], bool]:
        try:
            return run(tic), False
        except Exception:
            return [], True   # errored -> not marked processed -> retried next run

    # Wall-clock safety net: force-exit if the run blows past max_hours (a hung MAST
    # socket can wedge a worker thread indefinitely). Resumable — state is saved per
    # star, so nothing is lost; the watchdog soft-warns at 80% before firing.
    watchdog = (
        Watchdog(max_hours, marker_path=state_path + ".watchdog",
                 progress=lambda: f"{n_done}/{len(todo)} processed, {n_errors} error")
        if max_hours and max_hours > 0 else nullcontext()
    )
    with watchdog:
        if workers <= 1:
            for tic in todo:
                recs, errored = safe_run(tic)
                consume(tic, recs, errored)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(safe_run, tic): tic for tic in todo}
                for fut in as_completed(futures):
                    recs, errored = fut.result()
                    consume(futures[fut], recs, errored)
    if reporter is not None:
        reporter.done()

    # state now includes what we just processed; whatever's still pending is remaining.
    remaining = len(pending_targets(state, sector, tics, None))
    return WatchResult(
        sector=sector, scanned=len(todo), remaining=remaining, novel=novel, errors=n_errors
    )


def watch_loop(
    *,
    hint: int = 1,
    max_targets: int = 200,
    workers: int = 3,
    max_hours: float | None = 4.0,
    outdir: str = "candidates",
    state_path: str = "watch_state.json",
    summaries_dir: str | None = None,
    csv_log: str | None = None,
    sleep_s: float = 10800.0,
    cache_dir: str | None = None,
    cycles: int | None = None,
    watch_fn: Callable[..., WatchResult] | None = None,
    clean_fn: Callable[..., tuple[int, int]] | None = None,
    sleeper: Callable[[float], None] | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Self-healing forever-loop around watch(): auto-detect the newest sector, scan one
    resumable cycle, prune corrupt cached FITS, sleep, repeat. This is the 24/7 watcher —
    the same loop the Docker/Fly deployment runs, as one cross-platform command instead of
    an inline shell loop.

    Every cycle is wrapped so a transient failure (usually MAST) logs and continues rather
    than killing the watcher; watch()'s own --max-hours watchdog still hard-exits a wedged
    cycle, and the supervisor (compose `restart: always` / a Fly restart policy) relaunches
    it — state is saved per star, so nothing is lost. `cycles` caps iterations (None =
    forever); the injected deps make it unit-testable offline. Returns the cycle count run.
    """
    import time as _time
    from pathlib import Path

    from .fetch import clean_cache, default_cache_dir

    run_watch = watch_fn or watch
    prune = clean_fn or clean_cache
    rest = sleeper or _time.sleep
    cache = cache_dir if cache_dir is not None else str(default_cache_dir())

    i = 0
    while cycles is None or i < cycles:
        i += 1
        try:
            sector = latest_sector(hint=hint)
            if sector is None:
                log(f"[watch-loop] cycle {i}: no sector detected from hint {hint}; will retry")
            else:
                res = run_watch(
                    sector, outdir=outdir, state_path=state_path, max_targets=max_targets,
                    workers=workers, max_hours=max_hours, summaries_dir=summaries_dir,
                    csv_log=csv_log, show_progress=True,
                )
                log(f"[watch-loop] cycle {i}: sector {res.sector} scanned {res.scanned}, "
                    f"{len(res.novel)} novel, {res.errors} error, {res.remaining} remaining")
        except Exception as exc:   # a bad cycle must not kill the watcher
            log(f"[watch-loop] cycle {i} failed: {exc!r}; continuing")
        try:
            n, _freed = prune(cache)
            if n:
                log(f"[watch-loop] pruned {n} corrupt cached FITS")
        except Exception:
            pass
        if cycles is not None and i >= cycles:
            break
        log(f"[watch-loop] sleeping {sleep_s:.0f}s")
        rest(sleep_s)
    return i
