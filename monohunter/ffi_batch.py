"""FFI batch extraction — many stars from ONE cutout (Phase-2 data frontier).

The single-target FFI path (fetch.extract_ffi_lightcurve) downloads one cutout
per star: as slow as SPOC, one download each. The batch win is to download ONE
larger FFI region and pull a light curve for EVERY catalog star inside it — the
download cost is amortized across all of them, which is how you actually reach
the millions of stars with no pre-made light curve.

    big TESScut cutout (network)                     one download
      -> query TIC stars in the footprint (network)
      -> WCS: star RA/Dec -> pixel (col,row)
      -> extract_at_position: small aperture + sky per star   pure, vectorized
      -> detrend + detect each                                reuses the pipeline

extract_at_position / extract_batch are pure (take a flux cube / a TPF-like) so
they unit-test offline; run_ffi_batch is the network orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# TESS pixel scale — used to size the catalog cone to the cutout footprint.
ARCSEC_PER_PIXEL = 21.0
# Default aperture half-width (1 => 3x3 box) and how many pixels to keep clear
# around the source before measuring sky.
DEFAULT_APERTURE_RADIUS = 1
SKY_EXCLUDE_PAD = 1
# Photometry only trusts reasonably bright stars; fainter than this the FFI
# aperture is background-dominated.
DEFAULT_TMAG_MAX = 14.0


def extract_at_position(
    flux_cube: np.ndarray,
    col: float,
    row: float,
    radius: int = DEFAULT_APERTURE_RADIUS,
    sky_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Sky-subtracted aperture-sum light curve for a source at pixel (col, row).

    flux_cube is (ntime, ny, nx). A (2*radius+1) box around the pixel is the
    aperture; the sky level per cadence is the median of pixels outside a slightly
    larger exclusion zone (or the supplied sky_mask). Returns a 1-D flux array.
    """
    cube = np.asarray(flux_cube, dtype=float)
    ntime, ny, nx = cube.shape
    c, r = int(round(col)), int(round(row))

    r0, r1 = max(0, r - radius), min(ny, r + radius + 1)
    c0, c1 = max(0, c - radius), min(nx, c + radius + 1)
    aperture = cube[:, r0:r1, c0:c1].reshape(ntime, -1)
    n_ap = aperture.shape[1]
    ap_sum = np.nansum(aperture, axis=1)

    if sky_mask is None:
        sky_mask = np.ones((ny, nx), dtype=bool)
        pad = radius + SKY_EXCLUDE_PAD
        sky_mask[max(0, r - pad) : r + pad + 1, max(0, c - pad) : c + pad + 1] = False
    sky = np.nanmedian(cube[:, sky_mask], axis=1)
    return ap_sum - sky * n_ap


@dataclass(frozen=True)
class StarPixel:
    tic: int
    col: float
    row: float


def extract_batch(tpf, stars: list[StarPixel], radius: int = DEFAULT_APERTURE_RADIUS):
    """Extract a normalized light curve per star from one shared cutout TPF.

    Yields (tic, time, flux) for every star whose aperture fits inside the cutout.
    """
    flux_cube = np.asarray(getattr(tpf.flux, "value", tpf.flux), dtype=float)
    time = np.asarray(getattr(tpf.time, "value", tpf.time), dtype=float)
    _, ny, nx = flux_cube.shape
    for s in stars:
        c, r = int(round(s.col)), int(round(s.row))
        if not (radius <= c < nx - radius and radius <= r < ny - radius):
            continue  # too close to the cutout edge to place an aperture
        raw = extract_at_position(flux_cube, s.col, s.row, radius=radius)
        med = np.nanmedian(raw)
        if not np.isfinite(med) or med <= 0:
            continue
        flux = raw / med
        good = np.isfinite(time) & np.isfinite(flux)
        if good.sum() < 10:
            continue
        yield s.tic, time[good], flux[good]


@dataclass(frozen=True)
class BatchDetection:
    tic: int
    sector: int
    event_time_btjd: float
    depth_ppt: float
    duration_hr: float
    snr: float


# In a crowded FFI cutout a deep event bleeds into neighbouring stars' apertures
# (overlapping PSFs), so several stars "detect" the same eclipse at the same time.
# Detections within this window are treated as one physical event.
BLEND_DT_D = 0.1


def dedup_blends(detections: list[BatchDetection]) -> tuple[list[BatchDetection], int]:
    """Collapse crowding blends: cluster detections by event time and keep the
    highest-SNR one per cluster (the best-centered aperture = the likely true
    source). Returns (primaries, n_blended_removed).

    ponytail: time-cluster + brightest-wins. A PSF-fit / difference-image centroid
    would attribute the event to the right star more rigorously; this is the cheap
    honest first cut so the batch doesn't report one eclipse as N discoveries.
    """
    if not detections:
        return [], 0
    ordered = sorted(detections, key=lambda d: d.event_time_btjd)
    clusters: list[list[BatchDetection]] = [[ordered[0]]]
    for d in ordered[1:]:
        if abs(d.event_time_btjd - clusters[-1][-1].event_time_btjd) <= BLEND_DT_D:
            clusters[-1].append(d)
        else:
            clusters.append([d])
    primaries = [max(c, key=lambda d: d.snr) for c in clusters]
    blended = sum(len(c) - 1 for c in clusters)
    return primaries, blended


def run_ffi_batch(
    center_tic: int,
    sector: int,
    cutout_px: int = 30,
    tmag_max: float = DEFAULT_TMAG_MAX,
    window_length: float | None = None,
    detector=None,
) -> tuple[list[BatchDetection], int]:
    """Download ONE cutout around center_tic, extract every catalog star in it, and
    run the transit detector on each. Returns detections across all stars.

    Network — exercised live, not unit-tested. The pure pieces (extract_at_position,
    extract_batch) carry the offline tests.
    """
    import lightkurve as lk
    from astroquery.mast import Catalogs

    from .detect import BoxMatchedFilter
    from .detrend import DEFAULT_WINDOW_D, flatten

    detector = detector or BoxMatchedFilter()
    win = window_length if window_length is not None else DEFAULT_WINDOW_D

    sr = lk.search_tesscut(f"TIC {int(center_tic)}", sector=sector)
    if len(sr) == 0:
        return [], 0
    tpf = sr[0].download(cutout_size=cutout_px)
    if tpf is None:
        return [], 0

    # Catalog stars inside the cutout footprint (a cone sized to the cutout).
    radius_deg = (cutout_px * ARCSEC_PER_PIXEL / 2.0) / 3600.0
    cat = Catalogs.query_object(f"TIC {int(center_tic)}", radius=radius_deg, catalog="TIC")
    stars: list[StarPixel] = []
    for r in cat:
        try:
            tmag = float(r["Tmag"])
            if tmag > tmag_max:
                continue
            col, row = tpf.wcs.all_world2pix(float(r["ra"]), float(r["dec"]), 0)
            stars.append(StarPixel(int(r["ID"]), float(col), float(row)))
        except Exception:
            continue

    detections: list[BatchDetection] = []
    for tic, time, flux in extract_batch(tpf, stars):
        flat, _ = flatten(time, flux, window_length=win)
        for cand in detector.search(time, flat):
            detections.append(BatchDetection(
                tic=tic, sector=sector,
                event_time_btjd=cand.event_time_btjd,
                depth_ppt=cand.depth_ppt,
                duration_hr=cand.duration_hr,
                snr=cand.snr,
            ))
    return dedup_blends(detections)   # (primaries, n_blended) — collapse crowding blends
