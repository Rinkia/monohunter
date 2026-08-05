"""T3 — matched-filter box scan (v1 detector).

Non-periodic by design: slides a box (uniform-mean) transit model of several
trial durations across the light curve and scores the deepest sustained dip by
SNR. No phase-folding, so a SINGLE transit is detectable — which is the whole
point (TLS can't do this; it needs a period to fold on).

    flux ─┐         ┌─────  baseline ≈ 1 (after normalize+detrend)
          │  ┌───┐  │
          └──┘   └──┘       one box, width = trial duration
             ▲
          depth = 1 - mean_in_box
          snr   = depth / (sigma / sqrt(n_in))     sigma = robust MAD scatter

ponytail: returns the single best candidate. Multi-candidate / iterative masking
is a later upgrade once v1 finds things.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter1d

from .base import Candidate, Detector

# ponytail: fixed duration grid tuned for long/single transits (hours). Widen if
# you start hunting shorter events.
DEFAULT_DURATIONS_HR = (2.0, 4.0, 6.0, 8.0, 12.0, 18.0, 24.0, 30.0)
DEFAULT_SNR_THRESHOLD = 7.0  # SDE-like floor; below this is noise (see TLS best practice)
_MAD_TO_SIGMA = 1.4826  # MAD -> Gaussian sigma


class BoxMatchedFilter(Detector):
    def __init__(
        self,
        durations_hr: tuple[float, ...] = DEFAULT_DURATIONS_HR,
        snr_threshold: float = DEFAULT_SNR_THRESHOLD,
    ) -> None:
        self.durations_hr = durations_hr
        self.snr_threshold = snr_threshold

    def search(self, time: np.ndarray, flux: np.ndarray) -> list[Candidate]:
        time = np.asarray(time, dtype=float)
        flux = np.asarray(flux, dtype=float)
        good = np.isfinite(time) & np.isfinite(flux)
        time, flux = time[good], flux[good]
        if time.size < 10:
            return []

        dt = float(np.median(np.diff(time)))  # days per cadence
        if not np.isfinite(dt) or dt <= 0:
            return []

        sigma = _MAD_TO_SIGMA * float(np.median(np.abs(flux - np.median(flux))))
        if sigma <= 0:
            return []

        best: Candidate | None = None
        for dur_hr in self.durations_hr:
            width = int(round((dur_hr / 24.0) / dt))  # cadences in the box
            if width < 3 or width >= flux.size:
                continue
            rolling_mean = uniform_filter1d(flux, size=width, mode="nearest")
            i = int(np.argmin(rolling_mean))
            depth = 1.0 - float(rolling_mean[i])
            if depth <= 0:
                continue
            snr = depth / (sigma / np.sqrt(width))
            if best is None or snr > best.snr:
                best = Candidate(
                    event_time_btjd=float(time[i]),
                    depth_ppt=depth * 1e3,
                    duration_hr=float(dur_hr),
                    snr=float(snr),
                )

        if best is None or best.snr < self.snr_threshold:
            return []
        return [best]
