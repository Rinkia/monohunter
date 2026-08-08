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
from .characterize import fit_trapezoid, is_likely_eb
from .crossmatch import known_toi
from .detect import BoxMatchedFilter, Detector
from .detrend import DEFAULT_METHOD, DEFAULT_WINDOW_D, flatten
from .ephemeris import estimate_period, period_from_transits
from .fetch import (
    cadence_seconds,
    download_ffi_lightcurve,
    download_lightcurve,
    get_stellar_density,
    iter_lightcurves,
    search_tess,
    search_tesscut,
)
from .record import FindRecord

_BTJD_OFFSET = 2457000.0  # BTJD = BJD - 2457000


def _now_btjd() -> float | None:
    try:
        from astropy.time import Time

        return float(Time.now().jd) - _BTJD_OFFSET
    except Exception:
        return None


def _values(array: object) -> np.ndarray:
    return np.asarray(getattr(array, "value", array), dtype=float)


def _write_summary(
    outdir: str, tic: int, sector: int, cadence_s: int,
    time: np.ndarray, raw_flux: np.ndarray, flat_flux: np.ndarray,
) -> None:
    """Summarize this sector's light curve (rotation/variability/flares/dipper)
    and write it to outdir. Uses the SAME already-downloaded flux — no refetch."""
    from .summary import StellarSummary, summarize

    res = summarize(time, raw_flux, flat_flux)
    rec = StellarSummary(
        tic=int(tic), sector=int(sector), cadence_s=int(cadence_s),
        n_epochs=int(np.isfinite(raw_flux).sum()),
        var_amplitude_ppt=res.var_amplitude_ppt,
        rotation_period_d=res.rotation_period_d, rotation_power=res.rotation_power,
        rotation_systematic=res.rotation_systematic, n_flares=res.n_flares,
        is_dipper=res.is_dipper, n_dips=res.n_dips, var_class=res.var_class,
    )
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, f"tic{tic}_s{sector}.json"), "w", encoding="utf-8") as fh:
        fh.write(rec.to_json(indent=2))


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


def build_record(
    tic: int,
    sector: int,
    cadence_s: int,
    time: np.ndarray,
    flat: np.ndarray,
    cand,
    *,
    is_known: bool,
    toi_id: str | None,
    rho_cgs: float | None,
    rho_err_cgs: float | None,
    now_btjd: float | None,
    window_length: float,
    baseline_time: np.ndarray | None = None,
    n_sectors_observed: int = 1,
    recurring_dip: bool = False,
    outdir: str = "candidates",
    make_plots: bool = False,
) -> FindRecord:
    """Assemble one validated FindRecord from a box candidate: trapezoid-refine,
    EB flag, ephemeris, optional plot. Shared by run_target and the FFI batch so
    both paths produce identical, leaderboard-ready records.

    baseline_time overrides the time array fed to the ephemeris p_min (the full
    multi-sector baseline); defaults to this light curve's own time.
    """
    fit = fit_trapezoid(time, flat, cand.event_time_btjd, cand.duration_hr)
    if fit is not None:
        t0, depth_ppt, duration_hr, ingress_hr = (
            fit.t0_btjd, fit.depth_ppt, fit.duration_hr, fit.ingress_hr,
        )
    else:
        t0, depth_ppt, duration_hr, ingress_hr = (
            cand.event_time_btjd, cand.depth_ppt, cand.duration_hr, None,
        )
    rec = FindRecord(
        tic=int(tic),
        sector=int(sector),
        cadence_s=int(cadence_s),
        event_time_btjd=t0,
        depth_ppt=depth_ppt,
        duration_hr=duration_hr,
        ingress_hr=ingress_hr,
        snr=cand.snr,
        detrend_method=DEFAULT_METHOD,
        detrend_window_d=window_length,
        tool_version=__version__,
        known_toi_match=is_known,
        known_toi_id=toi_id,
        likely_eb=is_likely_eb(depth_ppt, ingress_hr, duration_hr),
        n_sectors_observed=n_sectors_observed,
        recurring_dip=recurring_dip,
    )
    post = estimate_period(
        t0_btjd=t0,
        t14_hr=duration_hr,
        ingress_hr=ingress_hr,
        ingress_err_hr=None,
        depth_ppt=depth_ppt,
        rho_star_cgs=rho_cgs,
        rho_err_cgs=rho_err_cgs,
        time_array=baseline_time if baseline_time is not None else time,
        now_btjd=now_btjd,
        snr=cand.snr,
        cadence_s=cadence_s,
    )
    rec = rec.model_copy(update={
        "stellar_density_cgs": rho_cgs,
        "period_constrained": post.period_constrained,
        "p_min_d": post.p_min_d,
        "p_best_d": post.p_best_d,
        "p_lo_d": post.p16_d,
        "p_hi_d": post.p84_d,
        "next_window_btjd": list(post.next_window_btjd) if post.next_window_btjd else None,
    })
    if make_plots:
        rec = rec.model_copy(update={"plot_path": _save_plot(outdir, rec, time, flat)})
    return rec


def run_target(
    tic: int,
    detector: Detector | None = None,
    window_length: float = DEFAULT_WINDOW_D,
    outdir: str = "candidates",
    make_plots: bool = True,
    sectors: list[int] | None = None,
    source: str = "spoc",
    summaries_dir: str | None = None,
) -> list[FindRecord]:
    """Search deduped sectors of one TIC; return validated candidate records.

    sectors: restrict to these sector numbers (None = all available).
    source: "spoc" (pre-made 2-min/QLP light curves) or "ffi" (extract from the
    Full-Frame Images via TESScut — reaches stars with no pre-made light curve).
    summaries_dir: if set, also write a StellarSummary (rotation / variability /
    flare / dipper) per sector there — a catalog product from the SAME download,
    at ~a few percent CPU overhead on the download-bound sweep.
    """
    detector = detector or BoxMatchedFilter()
    wanted = set(sectors) if sectors is not None else None
    if source == "ffi":
        sr, rows = search_tesscut(tic, sectors=wanted)

        def download(row: dict) -> object:
            return download_ffi_lightcurve(sr, row["_index"])
    else:
        sr, rows = search_tess(tic)
        if wanted is not None:
            rows = [r for r in rows if int(r["sector"]) in wanted]

        def download(row: dict) -> object:
            return download_lightcurve(sr, row["_index"])

    is_known, toi_id = known_toi(tic)
    rho_cgs, rho_err_cgs = get_stellar_density(tic)
    now_btjd = _now_btjd()

    # Pass 1 — stream sectors: detect candidates and accumulate every sector's
    # TIME coverage (times only; flux kept just for candidate-bearing sectors, so
    # memory stays bounded). Ephemeris waits for the full baseline (pass 2).
    all_times: list[np.ndarray] = []
    pending: list[dict] = []
    for row, lc in iter_lightcurves(rows, download):
        time = _values(lc.time.value if hasattr(lc.time, "value") else lc.time)
        flux = _values(lc.flux)
        # SPOC rows carry cadence from the search table; FFI rows are 0 -> measure it.
        cadence_s = int(row["cadence_s"]) or cadence_seconds(time)
        all_times.append(time)
        flat, _ = flatten(time, flux, window_length=window_length)
        if summaries_dir is not None:
            _write_summary(summaries_dir, tic, int(row["sector"]), cadence_s, time, flux, flat)
        for cand in detector.search(time, flat):
            pending.append({
                "sector": int(row["sector"]), "cadence_s": cadence_s,
                "cand": cand, "time": time, "flat": flat,
            })

    # Pass 2 — cross-sector context. A real long-period single transit shows in
    # ONE sector; dips in MULTIPLE sectors mean a periodic/variable star (EB), not
    # a clean mono-transit. The ephemeris uses the FULL multi-sector baseline, so a
    # 2nd transit ruled out across every observed sector raises p_min.
    full_time = np.concatenate(all_times) if all_times else None
    n_sectors = len(all_times)
    recurring = len({p["sector"] for p in pending}) > 1

    records: list[FindRecord] = [
        build_record(
            tic, p["sector"], p["cadence_s"], p["time"], p["flat"], p["cand"],
            is_known=is_known, toi_id=toi_id, rho_cgs=rho_cgs, rho_err_cgs=rho_err_cgs,
            now_btjd=now_btjd, window_length=window_length, baseline_time=full_time,
            n_sectors_observed=n_sectors, recurring_dip=recurring,
            outdir=outdir, make_plots=make_plots,
        )
        for p in pending
    ]

    # Exact period from the multiple transit times (a recurring target's real win):
    # >=3 transits pin the period uniquely; 2 use the rho*-based estimate to pick the
    # cycle count. Stamp it on every record of the target.
    if len(records) >= 2:
        guess = next((r.p_best_d for r in records if r.p_best_d), None)
        fit = period_from_transits([r.event_time_btjd for r in records], p_guess=guess)
        if fit is not None:
            period_d, _t0, n_tr = fit
            records = [
                r.model_copy(update={"measured_period_d": period_d, "n_transits_used": n_tr})
                for r in records
            ]
    return records
