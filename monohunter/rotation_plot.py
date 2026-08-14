"""Rotation-period distribution figure from a stellar catalog.

The sweep's catalog CSV holds a rotation period for every rotator (>1000 stars
over one sector). Two population-level views fall straight out of that column and
are a publishable science figure — no new data:

  1. period distribution      (histogram, log period)
  2. period-amplitude relation (scatter: fast rotators are more spotted/active)

rotation_stats is pure (filters + returns arrays, unit-tested offline);
plot_rotation_distribution renders the matplotlib figure.
"""

from __future__ import annotations

import numpy as np


def rotation_stats(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """(periods_d, amplitudes_ppt) for real rotators in a catalog.

    A row counts when it has a finite rotation_period_d and is not flagged
    systematic (instrumental period). Pure.
    """
    periods: list[float] = []
    amps: list[float] = []
    for r in rows:
        p = r.get("rotation_period_d")
        if p in (None, "", "None"):
            continue
        if str(r.get("rotation_systematic", "")).lower() in ("true", "1"):
            continue
        try:
            pv = float(p)
            av = float(r.get("var_amplitude_ppt", "nan"))
        except (TypeError, ValueError):
            continue
        if np.isfinite(pv) and pv > 0 and np.isfinite(av):
            periods.append(pv)
            amps.append(av)
    return np.array(periods), np.array(amps)


def plot_rotation_distribution(rows: list[dict], out_path: str, sector: int | None = None) -> int:
    """Render the period distribution + period-amplitude figure to out_path (PNG).
    Returns the number of rotators plotted."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    periods, amps = rotation_stats(rows)
    n = periods.size
    title = "TESS rotation periods" + (f" — Sector {sector}" if sector is not None else "")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    fig.suptitle(f"{title}  (N={n} rotators)")

    if n:
        bins = np.logspace(np.log10(max(periods.min(), 1e-2)), np.log10(periods.max()), 30)
        ax1.hist(periods, bins=bins, color="#3b6", edgecolor="#151")
        ax1.set_xscale("log")
        ax2.scatter(periods, amps, s=6, alpha=0.35, color="#37a")
        ax2.set_xscale("log")
        ax2.set_yscale("log")
    ax1.set_xlabel("rotation period [d]")
    ax1.set_ylabel("stars")
    ax1.set_title("period distribution")
    ax2.set_xlabel("rotation period [d]")
    ax2.set_ylabel("variability amplitude [ppt]")
    ax2.set_title("period–amplitude relation")

    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return n
