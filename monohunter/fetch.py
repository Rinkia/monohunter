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
import socket
from typing import Any, Callable, Iterable, Iterator, Mapping, TypeVar

import numpy as np

# A hung MAST/IRSA read (no data, connection stuck) would block a sweep worker
# thread forever with no timeout — one stall wedges the whole parallel sweep.
# Cap every socket read so a stuck download raises (ReadTimeout/socket.timeout,
# both OSError) instead, and gets skipped like any other failed download.
socket.setdefaulttimeout(180)

Row = Mapping[str, object]
LC = TypeVar("LC")


# "hard" drops cadences flagged for scattered light, momentum dumps, and other
# bad-quality events. lightkurve's default ("default") leaves narrow artifacts
# that the box scan can mistake for dips. "hardest" over-trims real data.
DEFAULT_QUALITY_BITMASK = "hard"


def _sector_from_mission(value: object) -> int | None:
    match = re.search(r"Sector\s+(\d+)", str(value))
    return int(match.group(1)) if match else None


_RHO_SUN_CGS = 1.408  # solar mean density, g/cm^3
_RHO_CACHE: dict[int, tuple[float | None, float | None]] = {}


def _as_float(value: object) -> float | None:
    try:
        f = float(value)  # type: ignore[arg-type]
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except Exception:
        return None


def get_stellar_density(tic: int) -> tuple[float | None, float | None]:
    """(rho_cgs, rho_err_cgs) for a TIC. Prefer TIC 'rho', else derive from
    R*+M*, else (None, None). Cached; offline-safe (network failure -> None)."""
    tic = int(tic)
    if tic in _RHO_CACHE:
        return _RHO_CACHE[tic]

    result: tuple[float | None, float | None] = (None, None)
    try:
        from astroquery.mast import Catalogs

        cat = Catalogs.query_criteria(catalog="TIC", ID=tic)
        if len(cat):
            row = cat[0]
            rho = _as_float(row["rho"])            # solar units
            erho = _as_float(row["e_rho"])
            if rho is None:                        # derive from R*, M* (solar)
                rad, mass = _as_float(row["rad"]), _as_float(row["mass"])
                if rad and mass and rad > 0:
                    rho = mass / rad**3
            if rho is not None and rho > 0:
                rho_cgs = rho * _RHO_SUN_CGS
                erho_cgs = erho * _RHO_SUN_CGS if erho else 0.3 * rho_cgs
                result = (rho_cgs, erho_cgs)
    except Exception:
        result = (None, None)

    _RHO_CACHE[tic] = result
    return result


def download_lightcurve(
    search_result: Any, index: int, quality_bitmask: str = DEFAULT_QUALITY_BITMASK
) -> Any:
    """Download one row, quality-masked, NaN-stripped, normalized.

    Centralizes data cleaning in the fetch layer. Falls back to a plain download
    if a product doesn't accept quality_bitmask (e.g. some FFI products). Returns
    None on a truncated/corrupt FITS (MAST serves partial files under load) so the
    caller skips the sector instead of crashing — remove_nans() materializes the
    arrays and raises "buffer is too small" on a partial download.
    """
    from lightkurve.utils import LightkurveError

    entry = search_result[index]
    try:
        try:
            lc = entry.download(quality_bitmask=quality_bitmask)
        except TypeError:
            lc = entry.download()
        return lc.remove_nans().normalize()
    except (LightkurveError, TypeError, OSError, ValueError):
        # A corrupt/truncated FITS from an interrupted MAST download raises
        # LightkurveError ("This file may be corrupt..."); remove_nans() on a
        # partial array raises TypeError. Either way skip the sector, don't crash.
        return None


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


# FFI cutout side in pixels: room for a threshold aperture plus a sky ring for
# background. Bigger wastes MAST bandwidth; smaller starves the background ring.
DEFAULT_CUTOUT_PX = 11


def cadence_seconds(time_array: Any) -> int:
    """Cadence in seconds from a BTJD time array (median sample spacing).

    FFI cadence varies by cycle (1800s / 600s / 200s), so it's measured from the
    data rather than read off a fixed table like the 2-min SPOC path.
    """
    t = np.asarray(getattr(time_array, "value", time_array), dtype=float)
    if t.size < 2:
        return 0
    return int(round(float(np.median(np.diff(t))) * 86400.0))


def search_tesscut(tic: int, sectors: set[int] | None = None) -> tuple[Any, list[Row]]:
    """Search TESS Full-Frame-Image cutouts (TESScut) for a TIC.

    This is the Phase-2 wedge: TESScut serves a pixel stamp for ANY star, so it
    reaches the millions with no pre-made SPOC/QLP light curve. Returns
    (SearchResult, rows); cadence_s is 0 here and measured after download.
    Network call — exercised by the CLI E2E, not unit tests.
    """
    import lightkurve as lk

    sr = lk.search_tesscut(f"TIC {int(tic)}")
    table = sr.table
    rows: list[Row] = []
    for i in range(len(sr)):
        sector = _sector_from_mission(table["mission"][i])
        if sector is None or (sectors is not None and sector not in sectors):
            continue
        rows.append({"sector": sector, "cadence_s": 0, "_index": i})
    return sr, rows


def extract_ffi_lightcurve(tpf: Any, threshold: float = 3.0) -> Any:
    """Aperture photometry on an FFI cutout -> cleaned, normalized LightCurve.

    Threshold aperture (pixels > threshold-MAD above median), minus a per-cadence
    sky level taken as the median of the out-of-aperture pixels. Output matches
    the SPOC path's contract (.time / .flux) so it drops straight into pipeline.

    # ponytail: naive median-background aperture photometry — no PLD/CBV systematics
    # correction. Swap in eleanor-grade detrending only if FFI precision falls short.
    """
    aperture = tpf.create_threshold_mask(threshold=threshold)
    if not aperture.any():  # faint/edge star: fall back to the brightest pixel
        aperture = tpf.create_threshold_mask(threshold=1.0)
    lc = tpf.to_lightcurve(aperture_mask=aperture)
    # tpf.flux is an astropy Quantity (electron/s); carry its unit onto the sky
    # term so the subtraction stays dimensionally consistent (fakes have unit 1).
    unit = getattr(tpf.flux, "unit", 1)
    flux_cube = np.asarray(getattr(tpf.flux, "value", tpf.flux), dtype=float)
    sky_per_pixel = np.nanmedian(flux_cube[:, ~aperture], axis=1)
    lc = lc - sky_per_pixel * unit * int(aperture.sum())
    return lc.remove_nans().normalize()


def download_ffi_lightcurve(
    search_result: Any, index: int, cutout_px: int = DEFAULT_CUTOUT_PX
) -> Any:
    """Download one TESScut cutout and reduce it to a light curve. Returns None on
    a truncated/corrupt cutout (same MAST partial-download failure as SPOC)."""
    from lightkurve.utils import LightkurveError

    try:
        tpf = search_result[index].download(cutout_size=cutout_px)
        return extract_ffi_lightcurve(tpf)
    except (LightkurveError, TypeError, OSError, ValueError):
        return None


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
        lc = download(row)
        if lc is None:          # truncated/failed download -> skip this sector
            continue
        yield row, lc
