"""T7 — known-TOI cross-match.

Flags whether a target is already a known TESS Object of Interest, so a candidate
the tool surfaces is auto-labeled "already known" vs potentially new. Queries the
NASA Exoplanet Archive TOI table. Network-optional: any failure degrades to
"unknown" (False, None) so the tool still runs offline.
"""

from __future__ import annotations

_CACHE: dict[int, tuple[bool, str | None]] = {}


def known_toi(tic: int) -> tuple[bool, str | None]:
    """Return (is_known_toi, toi_id_or_None). Cached per TIC; safe offline."""
    tic = int(tic)
    if tic in _CACHE:
        return _CACHE[tic]

    result: tuple[bool, str | None] = (False, None)
    try:
        from astroquery.ipac.nexsci.nasa_exoplanet_archive import (
            NasaExoplanetArchive,
        )

        table = NasaExoplanetArchive.query_criteria(table="toi", where=f"tid={tic}")
        if len(table) > 0:
            result = (True, f"TOI-{table['toi'][0]}")
    except Exception:
        result = (False, None)  # network down / astroquery hiccup -> unknown

    _CACHE[tic] = result
    return result
