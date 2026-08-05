"""T2 — the Detector seam (design decision 1D).

A Detector is PURE SIGNAL: it takes a detrended light curve (time, flux) and
returns candidate dips. It knows nothing about TIC ids, sectors, or JSON — the
pipeline assembles those into a FindRecord. This keeps the box detector, the
future nuance (GP) detector, and Swarm's server-side re-scoring all behind one
interface. Detection logic must NOT leak into the fetch or CLI layers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Candidate:
    """A single dip found in a light curve. No target metadata — that's the pipeline's job."""

    event_time_btjd: float
    depth_ppt: float
    duration_hr: float
    snr: float


class Detector(ABC):
    """Search a detrended light curve for mono-transit candidates."""

    @abstractmethod
    def search(self, time: np.ndarray, flux: np.ndarray) -> list[Candidate]:
        """Return candidates ordered best-first (highest SNR). Empty list = nothing found."""
        raise NotImplementedError
