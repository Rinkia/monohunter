"""Novelty cross-match — is a find already a known variable star?

A find list is only credible if it says which entries are genuinely new. This
cone-matches a target against the AAVSO Variable Star Index (VSX) via Vizier —
the standard variable-star catalog — so each eclipsing binary / candidate is
labelled "known VSX <name> (<type>, P)" or "not in VSX (novel)". Same posture as
the known-TOI check: network-optional, any failure degrades to "unknown".

    TIC -> RA/Dec (catalog)  ->  VSX cone search (Vizier)  ->  nearest match

_nearest is pure and unit-tested; vsx_match / check_novelty hit the network.
"""

from __future__ import annotations

_VSX_CATALOG = "B/vsx/vsx"
_CACHE: dict[int, dict | None] = {}


def _nearest(candidates: list[dict]) -> dict | None:
    """Closest VSX candidate by separation. Pure. None if the list is empty."""
    if not candidates:
        return None
    return min(candidates, key=lambda c: c["sep_arcsec"])


def vsx_match(ra: float, dec: float, radius_arcsec: float = 10.0) -> dict | None:
    """Nearest VSX variable within radius of (ra, dec), or None. Network.

    Returns {name, type, period, sep_arcsec}. The cone is ~10" — VSX positions and
    the TIC position can differ by a few arcsec.
    """
    try:
        import astropy.units as u
        from astropy.coordinates import SkyCoord
        from astroquery.vizier import Vizier

        center = SkyCoord(ra, dec, unit="deg")
        res = Vizier(columns=["Name", "Type", "Period", "_RAJ2000", "_DEJ2000"]).query_region(
            center, radius=radius_arcsec * u.arcsec, catalog=_VSX_CATALOG
        )
        if not res or len(res) == 0 or len(res[0]) == 0:
            return None
        cands: list[dict] = []
        for row in res[0]:
            try:
                c = SkyCoord(float(row["_RAJ2000"]), float(row["_DEJ2000"]), unit="deg")
                period_raw = str(row["Period"]).strip()
                period = float(period_raw) if period_raw and period_raw not in ("--", "") else None
                cands.append({
                    "name": str(row["Name"]).strip(),
                    "type": str(row["Type"]).strip(),
                    "period": period,
                    "sep_arcsec": float(center.separation(c).arcsec),
                })
            except Exception:
                continue
        return _nearest(cands)
    except Exception:
        return None


def check_novelty(tic: int) -> dict | None:
    """Resolve a TIC to coordinates and VSX-match it. Cached; None = not in VSX
    (or offline). Network."""
    tic = int(tic)
    if tic in _CACHE:
        return _CACHE[tic]
    result: dict | None = None
    try:
        from astroquery.mast import Catalogs

        cat = Catalogs.query_object(f"TIC {tic}", radius=0.0016, catalog="TIC")
        if len(cat):
            result = vsx_match(float(cat[0]["ra"]), float(cat[0]["dec"]))
    except Exception:
        result = None
    _CACHE[tic] = result
    return result
