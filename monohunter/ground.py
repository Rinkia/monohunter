"""Ground-survey cross-check — ZTF (and later ASAS-SN) confirmation.

Ground surveys sample nightly over YEARS, not every 2 minutes over one sector.
That cadence can't resolve a ~24h transit, so this is NOT a primary detector; it
is a CONFIRMATION tool. A genuine long-period single transit sits on a star that
is otherwise QUIET; if a candidate's host is visibly variable across years of
ZTF/ASAS-SN photometry, it is a variable star / eclipsing binary, not a clean
mono-transit — the ground baseline settles the ambiguity a single sector can't.

    resolve TIC -> RA/Dec (catalog)             network
      -> fetch survey photometry (mag vs time)  network
      -> mag_to_flux                            pure
      -> variability amplitude over the baseline pure

mag_to_flux / variability are pure and unit-tested; the fetch + orchestrator are
network, exercised live.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826
# Fractional amplitude above which the host is "variable" — comfortably above a
# ground survey's ~1% per-point noise floor, so a flat star reads as quiet.
GROUND_VARIABLE_THRESHOLD = 0.03
ZTF_LC_URL = "https://irsa.ipac.caltech.edu/cgi-bin/ZTF/nph_light_curves"


def mag_to_flux(mag: np.ndarray) -> np.ndarray:
    """Magnitudes -> flux normalized to the median (baseline ~1).

    A brightening (smaller mag) rises above 1; a dimming (larger mag) dips below.
    """
    m = np.asarray(mag, dtype=float)
    med = np.nanmedian(m)
    return 10.0 ** (-0.4 * (m - med))


@dataclass(frozen=True)
class Variability:
    frac_amplitude: float    # robust fractional RMS of the normalized flux
    baseline_days: float
    n_epochs: int
    is_variable: bool        # amplitude above the ground noise floor


def variability(time, flux) -> Variability:
    """Robust variability of a normalized-flux series over its time baseline."""
    t = np.asarray(time, dtype=float)
    f = np.asarray(flux, dtype=float)
    good = np.isfinite(t) & np.isfinite(f)
    t, f = t[good], f[good]
    if f.size < 5:
        return Variability(0.0, 0.0, int(f.size), False)
    med = np.median(f)
    amp = _MAD_TO_SIGMA * float(np.median(np.abs(f - med))) / (abs(med) or 1.0)
    baseline = float(t.max() - t.min())
    return Variability(amp, baseline, int(f.size), bool(amp > GROUND_VARIABLE_THRESHOLD))


def fetch_ztf_lightcurve(ra: float, dec: float, radius_arcsec: float = 8.0, band: str = "r"):
    """ZTF photometry near (ra, dec) from the IRSA light-curve API.

    Returns (mjd, mag) for the ZTF object with the most epochs in the cone (the
    target, versus faint neighbours). Empty arrays on any failure. Network.

    The cone is ~8" because ZTF object centroids sit a few arcsec off the TIC
    catalog position — a 3" cone misses the target entirely; much wider pulls in
    neighbours and slows the query. The most-epochs pick still lands on the
    (brightest) target.
    """
    import csv
    import io

    import requests

    radius_deg = radius_arcsec / 3600.0
    params = {
        "POS": f"CIRCLE {ra} {dec} {radius_deg}",
        "BANDNAME": band,
        "FORMAT": "csv",
    }
    try:
        resp = requests.get(ZTF_LC_URL, params=params, timeout=120)
        resp.raise_for_status()
    except Exception:
        return np.array([]), np.array([])

    by_oid: dict[str, list[tuple[float, float]]] = {}
    for row in csv.DictReader(io.StringIO(resp.text)):
        try:
            oid = row["oid"]
            by_oid.setdefault(oid, []).append((float(row["mjd"]), float(row["mag"])))
        except (KeyError, ValueError):
            continue
    if not by_oid:
        return np.array([]), np.array([])

    best = max(by_oid.values(), key=len)   # the object with the most epochs
    best.sort()
    mjd = np.array([p[0] for p in best])
    mag = np.array([p[1] for p in best])
    return mjd, mag


@dataclass(frozen=True)
class GroundCheck:
    tic: int
    survey: str
    band: str
    variability: Variability


def run_ground_check(tic: int, survey: str = "ztf", band: str = "r") -> GroundCheck | None:
    """Resolve a TIC to coordinates, pull its ground light curve, and measure how
    variable the host is over the survey baseline. None if no photometry. Network.
    """
    from astroquery.mast import Catalogs

    cat = Catalogs.query_object(f"TIC {int(tic)}", radius=0.0016, catalog="TIC")
    if len(cat) == 0:
        return None
    ra, dec = float(cat[0]["ra"]), float(cat[0]["dec"])

    if survey == "ztf":
        mjd, mag = fetch_ztf_lightcurve(ra, dec, band=band)
    else:
        raise ValueError(f"unsupported survey {survey!r} (ztf only for now)")

    if mag.size == 0:
        return None
    flux = mag_to_flux(mag)
    return GroundCheck(int(tic), survey, band, variability(mjd, flux))
