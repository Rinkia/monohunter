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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .fetch import search_tess  # noqa: F401  (re-exported convenience)
from .pipeline import run_target
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


def watch(
    sector: int,
    outdir: str = "watch_out",
    state_path: str = "watch_state.json",
    max_targets: int = 50,
    target_pool: list[int] | None = None,
    runner: Callable[[int], list[FindRecord]] | None = None,
    source: str = "spoc",
) -> WatchResult:
    """Process the next `max_targets` un-scanned TICs of `sector`. Resumable.

    Writes each not-known-TOI candidate's record to outdir; updates state after
    every target so a crash never re-scans or loses work.

    source: "spoc" (pre-made light curves) or "ffi" (extract from Full-Frame
    Images). NOTE the default pool (`sector_targets`) enumerates 2-min SPOC TICs;
    FFI mode is most useful with an injected `target_pool` of stars that LACK
    SPOC data (there's no cheap MAST query for the full FFI star pool — deferred).
    """
    os.makedirs(outdir, exist_ok=True)
    run = runner or (
        lambda tic: run_target(
            tic, sectors=[sector], make_plots=False, outdir=outdir, source=source
        )
    )
    tics = target_pool if target_pool is not None else sector_targets(sector)

    state = load_state(state_path)
    todo = pending_targets(state, sector, tics, max_targets)

    novel: list[FindRecord] = []
    for tic in todo:
        try:
            recs = run(tic)
        except Exception:
            recs = []
        for rec in recs:
            if not rec.known_toi_match:
                novel.append(rec)
                path = Path(outdir) / f"tic{rec.tic}_s{rec.sector}.json"
                path.write_text(rec.to_json(indent=2), encoding="utf-8")
        mark_processed(state, sector, [tic])
        save_state(state_path, state)   # incremental — resumable on crash

    # state now includes what we just processed; whatever's still pending is remaining.
    remaining = len(pending_targets(state, sector, tics, None))
    return WatchResult(sector=sector, scanned=len(todo), remaining=remaining, novel=novel)
