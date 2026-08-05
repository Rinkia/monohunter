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
# ponytail: trim this much from each end before searching. Start/end-of-sector
# ramps span hours-to-a-day and masquerade as transits; a box-width-only guard
# misses ramps wider than the smallest box. Widen if edge FPs persist.
EDGE_TRIM_D = 0.5
# Isolation guard: reject if a SECOND independent dip (same duration, well
# separated) is more than this fraction of the candidate's depth. A real single
# transit stands alone; a variable / eclipsing-binary star has other troughs
# just as deep, so its "dip" is not isolated. ponytail: a single ratio; a proper
# per-star variability model (Lomb-Scargle prewhitening) would do better but is
# overkill for v1.
DEFAULT_MAX_SECONDARY_RATIO = 0.5


class BoxMatchedFilter(Detector):
    def __init__(
        self,
        durations_hr: tuple[float, ...] = DEFAULT_DURATIONS_HR,
        snr_threshold: float = DEFAULT_SNR_THRESHOLD,
        max_secondary_ratio: float = DEFAULT_MAX_SECONDARY_RATIO,
    ) -> None:
        self.durations_hr = durations_hr
        self.snr_threshold = snr_threshold
        self.max_secondary_ratio = max_secondary_ratio

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
        best_i = 0
        best_width = 0
        for dur_hr in self.durations_hr:
            width = int(round((dur_hr / 24.0) / dt))  # cadences in the box
            if width < 3 or width >= flux.size:
                continue
            rolling_mean = uniform_filter1d(flux, size=width, mode="nearest")
            # Edge guard: a box centered at index i spans [i-width/2, i+width/2],
            # so to keep the whole box clear of the trimmed edge zone (padding +
            # start/end-of-sector ramps — the S26 TOI-2180 false positive) the
            # center must sit at least EDGE_TRIM_D + half a box from each end.
            edge = int(round(EDGE_TRIM_D / dt)) + width // 2
            if 2 * edge >= rolling_mean.size:
                continue
            rolling_mean[:edge] = np.inf
            rolling_mean[-edge:] = np.inf
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
                best_i, best_width = i, width

        if best is None or best.snr < self.snr_threshold:
            return []

        # Isolation guard: is there a SECOND dip nearly as deep, well away from
        # the candidate? A real single transit has none (flat baseline elsewhere).
        # A variable / eclipsing-binary star keeps dipping, so its deepest trough
        # is not special — reject it. (TIC 17308640 was this: SNR 74 on a ~2%
        # variable star.)
        smooth = uniform_filter1d(flux, size=best_width, mode="nearest")
        guard_edge = int(round(EDGE_TRIM_D / dt)) + best_width // 2
        smooth[:guard_edge] = np.inf
        smooth[-guard_edge:] = np.inf
        idx = np.arange(flux.size)
        smooth[np.abs(idx - best_i) <= 2 * best_width] = np.inf  # mask the candidate
        finite = np.isfinite(smooth)
        if finite.sum() >= 20:
            second_depth = 1.0 - float(np.min(smooth[finite]))
            depth = best.depth_ppt / 1e3
            if second_depth > self.max_secondary_ratio * depth:
                return []
        return [best]
