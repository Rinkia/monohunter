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
# Gaia DR3 variability classification (vari_classifier_result): this Vizier table
# contains ONLY sources Gaia flagged variable, each with a Class — so a cone hit is
# a second, independent "already a known variable" signal beyond VSX.
_GAIA_VARI_CATALOG = "I/358/vclassre"
_CACHE: dict[int, dict | None] = {}
_GAIA_CACHE: dict[int, dict | None] = {}


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


def gaia_variability(ra: float, dec: float, radius_arcsec: float = 10.0) -> dict | None:
    """Nearest Gaia DR3 classified-variable source within radius, or None. Network.

    Returns {source_id, class, sep_arcsec}. Because the classifier table holds only
    variable sources, any match means Gaia independently flags the star as variable —
    a candidate that clears VSX may still be caught here."""
    try:
        import astropy.units as u
        from astropy.coordinates import SkyCoord
        from astroquery.vizier import Vizier

        center = SkyCoord(ra, dec, unit="deg")
        res = Vizier(columns=["Source", "Class", "_RAJ2000", "_DEJ2000"]).query_region(
            center, radius=radius_arcsec * u.arcsec, catalog=_GAIA_VARI_CATALOG
        )
        if not res or len(res) == 0 or len(res[0]) == 0:
            return None
        cands: list[dict] = []
        for row in res[0]:
            try:
                c = SkyCoord(float(row["_RAJ2000"]), float(row["_DEJ2000"]), unit="deg")
                cands.append({
                    "source_id": str(row["Source"]).strip(),
                    "class": str(row["Class"]).strip(),
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


def gaia_novelty(tic: int) -> dict | None:
    """Resolve a TIC to coordinates and Gaia-variability-match it. Cached; None = not
    a Gaia-classified variable (or offline). Network."""
    tic = int(tic)
    if tic in _GAIA_CACHE:
        return _GAIA_CACHE[tic]
    from .fetch import fetch_coords

    ra, dec = fetch_coords(tic)
    result = gaia_variability(ra, dec) if ra is not None else None
    _GAIA_CACHE[tic] = result
    return result
