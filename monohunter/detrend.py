"""T5 — detrend wrapper (wotan).

Thin wrapper so the rest of the code depends on ONE detrend entry point. The only
real knob is `window_length` (days): it MUST be several times the transit
duration, or flattening eats the very dip you're hunting. That footgun has a
regression test (test_detrend.py) — do not remove it.
"""

from __future__ import annotations

import numpy as np
from wotan import flatten as _wotan_flatten

DEFAULT_METHOD = "biweight"
DEFAULT_WINDOW_D = 3.0  # ponytail: 3x a ~1-day (24h) transit. Tune per target.


def flatten(
    time: np.ndarray,
    flux: np.ndarray,
    method: str = DEFAULT_METHOD,
    window_length: float = DEFAULT_WINDOW_D,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (flat_flux, trend). window_length is in DAYS."""
    time = np.asarray(time, dtype=float)
    flux = np.asarray(flux, dtype=float)
    flat, trend = _wotan_flatten(
        time, flux, method=method, window_length=window_length, return_trend=True
    )
    return flat, trend
