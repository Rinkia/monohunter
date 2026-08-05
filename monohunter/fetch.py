"""T4 — sector resolution + streaming loader (design decision 3A + streaming).

Two jobs:
  1. resolve_sectors(): dedup a search result to ONE row per sector, preferring
     2-min (120s) SPOC over the 20-sec duplicate. The notebook's naive all-58
     download is a footgun — many rows are the same sector at two cadences.
  2. iter_lightcurves(): stream sectors one at a time so memory stays bounded to
     ~one light curve even on 58-sector targets. The downloader is injected so
     this is unit-testable without hitting the network.

A "row" is any mapping with at least {"sector": int, "cadence_s": int}. In real
use these come from lightkurve's search table; in tests they're plain dicts.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Iterator, Mapping, TypeVar

Row = Mapping[str, object]
LC = TypeVar("LC")


def _sector_from_mission(value: object) -> int | None:
    match = re.search(r"Sector\s+(\d+)", str(value))
    return int(match.group(1)) if match else None


def _scalar(value: object) -> float:
    return float(getattr(value, "value", value))


def search_tess(tic: int, author: str = "SPOC") -> tuple[Any, list[Row]]:
    """Search TESS light curves for a TIC. Returns (SearchResult, rows).

    Prefers SPOC, falls back to QLP (FFI) if SPOC has nothing. Each row carries
    the SearchResult index so the streaming loader can download it lazily.
    Network call — not unit-tested; the CLI E2E exercises it live.
    """
    import lightkurve as lk

    sr = lk.search_lightcurve(f"TIC {int(tic)}", mission="TESS", author=author)
    if len(sr) == 0:
        sr = lk.search_lightcurve(f"TIC {int(tic)}", mission="TESS", author="QLP")

    table = sr.table
    rows: list[Row] = []
    for i in range(len(sr)):
        sector = _sector_from_mission(table["mission"][i])
        if sector is None:
            continue
        cadence = int(round(_scalar(table["exptime"][i])))
        rows.append({"sector": sector, "cadence_s": cadence, "_index": i})
    return sr, rows


def _preference(cadence_s: int) -> tuple[int, int]:
    """Lower sorts first. 120s (2-min) wins; otherwise shorter cadence."""
    return (0 if cadence_s == 120 else 1, int(cadence_s))


def resolve_sectors(rows: Iterable[Row]) -> list[Row]:
    """One row per sector, 2-min preferred, sorted by sector."""
    by_sector: dict[int, Row] = {}
    for row in rows:
        sector = int(row["sector"])  # type: ignore[call-overload]
        cadence = int(row["cadence_s"])  # type: ignore[call-overload]
        current = by_sector.get(sector)
        if current is None or _preference(cadence) < _preference(int(current["cadence_s"])):  # type: ignore[call-overload]
            by_sector[sector] = row
    return [by_sector[s] for s in sorted(by_sector)]


def iter_lightcurves(
    rows: Iterable[Row], download: Callable[[Row], LC]
) -> Iterator[tuple[Row, LC]]:
    """Yield (row, light_curve) one deduped sector at a time.

    The caller runs the detector on each and keeps only the find-record, so the
    light curve is released before the next download — bounded memory.
    """
    for row in resolve_sectors(rows):
        yield row, download(row)
