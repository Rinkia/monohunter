"""Pipeline — glue fetch -> detrend -> detect -> FindRecord for one target.

Streams sectors one at a time (bounded memory), runs the detector on each
detrended light curve, and assembles a validated FindRecord per candidate with
a diagnostic PNG. This is the orchestration layer the CLI calls.
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")  # headless: save PNGs, never open a window
import matplotlib.pyplot as plt
import numpy as np

from . import __version__
from .crossmatch import known_toi
from .detect import BoxMatchedFilter, Detector
from .detrend import DEFAULT_METHOD, DEFAULT_WINDOW_D, flatten
from .fetch import iter_lightcurves, search_tess
from .record import FindRecord


def _values(array: object) -> np.ndarray:
    return np.asarray(getattr(array, "value", array), dtype=float)


def _save_plot(outdir: str, rec: FindRecord, time: np.ndarray, flux: np.ndarray) -> str:
    os.makedirs(outdir, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.scatter(time, flux, s=1)
    ax.axvline(rec.event_time_btjd, color="red", lw=1)
    ax.set_xlabel("Time [BTJD]")
    ax.set_ylabel("flattened flux")
    ax.set_title(f"TIC {rec.tic}  S{rec.sector}  SNR={rec.snr:.1f}")
    path = os.path.join(outdir, f"tic{rec.tic}_s{rec.sector}.png")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return path


def run_target(
    tic: int,
    detector: Detector | None = None,
    window_length: float = DEFAULT_WINDOW_D,
    outdir: str = "candidates",
    make_plots: bool = True,
    sectors: list[int] | None = None,
) -> list[FindRecord]:
    """Search deduped sectors of one TIC; return validated candidate records.

    sectors: restrict to these sector numbers (None = all available).
    """
    detector = detector or BoxMatchedFilter()
    sr, rows = search_tess(tic)
    if sectors is not None:
        wanted = set(sectors)
        rows = [r for r in rows if int(r["sector"]) in wanted]
    is_known, toi_id = known_toi(tic)

    def download(row: dict) -> object:
        return sr[row["_index"]].download().remove_nans().normalize()

    records: list[FindRecord] = []
    for row, lc in iter_lightcurves(rows, download):
        time = _values(lc.time.value if hasattr(lc.time, "value") else lc.time)
        flux = _values(lc.flux)
        flat, _ = flatten(time, flux, window_length=window_length)
        for cand in detector.search(time, flat):
            rec = FindRecord(
                tic=int(tic),
                sector=int(row["sector"]),
                cadence_s=int(row["cadence_s"]),
                event_time_btjd=cand.event_time_btjd,
                depth_ppt=cand.depth_ppt,
                duration_hr=cand.duration_hr,
                snr=cand.snr,
                detrend_method=DEFAULT_METHOD,
                detrend_window_d=window_length,
                tool_version=__version__,
                known_toi_match=is_known,
                known_toi_id=toi_id,
            )
            if make_plots:
                rec = rec.model_copy(update={"plot_path": _save_plot(outdir, rec, time, flat)})
            records.append(rec)
    return records
