"""Observability — is a predicted transit catchable from the ground, and when?

A next-transit window (from ephemeris) is only actionable if the target is actually
above the horizon AND the sky is dark at the observer's site during it. This turns a
BTJD window into concrete "up and dark" clock-time intervals for a given latitude /
longitude, so an amateur with a telescope knows whether — and when — to point.

Astropy only (already a dependency): target altitude via AltAz, darkness via the
Sun's altitude. The interval-grouping is pure and unit-tested offline; the AltAz
transform is the only astropy-touching part.
"""

from __future__ import annotations

_BTJD_OFFSET = 2457000.0  # BTJD = BJD(TDB) - 2457000
ASTRONOMICAL_NIGHT_DEG = -18.0  # Sun this far below the horizon = fully dark sky
DEFAULT_MIN_ALT_DEG = 30.0      # below ~30° airmass/extinction make photometry poor


def _runs_to_intervals(x: list[float], mask: list[bool]) -> list[tuple[float, float]]:
    """Group contiguous True runs of `mask` into [x_start, x_end] intervals. Pure."""
    intervals: list[tuple[float, float]] = []
    n = len(mask)
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            intervals.append((float(x[i]), float(x[j])))
            i = j + 1
        else:
            i += 1
    return intervals


def observable_windows(
    ra_deg: float,
    dec_deg: float,
    t_start_btjd: float,
    t_end_btjd: float,
    lat_deg: float,
    lon_deg: float,
    elevation_m: float = 0.0,
    min_alt_deg: float = DEFAULT_MIN_ALT_DEG,
    sun_alt_deg: float = ASTRONOMICAL_NIGHT_DEG,
    step_min: float = 10.0,
) -> list[tuple[float, float]]:
    """BTJD intervals within [t_start, t_end] where the target is above min_alt_deg
    AND the Sun is below sun_alt_deg (dark) at the given site. Empty if never both.

    Sampled every step_min minutes; interval edges are therefore accurate to ~step_min
    — fine for deciding whether to observe. Returns [] for a non-positive window.
    """
    import astropy.units as u
    import numpy as np
    from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_sun
    from astropy.time import Time

    if t_end_btjd <= t_start_btjd:
        return []
    step_d = step_min / (60.0 * 24.0)
    n = max(2, int(np.ceil((t_end_btjd - t_start_btjd) / step_d)) + 1)
    btjd = np.linspace(t_start_btjd, t_end_btjd, n)
    times = Time(btjd + _BTJD_OFFSET, format="jd", scale="tdb")
    site = EarthLocation(lat=lat_deg * u.deg, lon=lon_deg * u.deg, height=elevation_m * u.m)
    frame = AltAz(obstime=times, location=site)
    target_alt = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg).transform_to(frame).alt.deg
    sun_alt = get_sun(times).transform_to(frame).alt.deg
    up_dark = (target_alt >= min_alt_deg) & (sun_alt <= sun_alt_deg)
    return _runs_to_intervals(list(btjd), list(bool(b) for b in up_dark))


def btjd_to_utc_iso(btjd: float) -> str:
    """BTJD -> UTC ISO string (minute precision)."""
    from astropy.time import Time

    return Time(btjd + _BTJD_OFFSET, format="jd", scale="tdb").utc.iso[:16] + " UTC"


def interval_hours(intervals: list[tuple[float, float]]) -> float:
    """Total length of the intervals, in hours."""
    return sum((b - a) for a, b in intervals) * 24.0
