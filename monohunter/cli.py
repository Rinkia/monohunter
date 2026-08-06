"""T6 — CLI: `monohunter run --tic <id>`.

End-to-end: search TESS -> detrend -> detect single transits -> write one JSON
find-record + PNG per candidate into the output dir.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .pipeline import run_target
from .swarm import aggregate, load_records, render_html, render_json


def _btjd_to_date(btjd: float) -> str:
    """BTJD -> calendar date (UTC, day precision). Falls back to raw BTJD."""
    try:
        from astropy.time import Time

        return str(Time(btjd + 2457000.0, format="jd").iso)[:10]
    except Exception:
        return f"BTJD {btjd:.0f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="monohunter",
        description="Hunt single long-period (mono-)transits in public TESS light curves.",
    )
    parser.add_argument("--version", action="version", version=f"monohunter {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="search one target by TIC id")
    run.add_argument("--tic", type=int, required=True, help="TESS Input Catalog id")
    run.add_argument("--window", type=float, default=3.0, help="detrend window in days (>> transit)")
    run.add_argument("--outdir", default="candidates", help="where to write JSON + PNG")
    run.add_argument("--no-plot", action="store_true", help="skip PNG generation")
    run.add_argument(
        "--sectors",
        type=int,
        nargs="+",
        default=None,
        help="restrict to these sector numbers (default: all available)",
    )
    run.add_argument(
        "--ffi",
        action="store_true",
        help="extract from TESS Full-Frame Images via TESScut (reaches stars with "
        "no pre-made SPOC/QLP light curve); cadence is measured from the data",
    )

    ano = sub.add_parser(
        "anomaly", help="scan a target for flares (brightenings) and dipper behavior"
    )
    ano.add_argument("--tic", type=int, required=True, help="TESS Input Catalog id")
    ano.add_argument("--window", type=float, default=3.0, help="detrend window in days")
    ano.add_argument(
        "--sectors", type=int, nargs="+", default=None,
        help="restrict to these sector numbers (default: all available)",
    )

    agg = sub.add_parser(
        "aggregate", help="build the community leaderboard from contributions/"
    )
    agg.add_argument("--contributions", default="contributions", help="submissions dir")
    agg.add_argument("--out", default="_site", help="output dir for leaderboard.json + index.html")

    wat = sub.add_parser(
        "watch", help="incrementally scan a fresh TESS sector (resumable; run on a schedule)"
    )
    wat.add_argument(
        "--sector",
        type=int,
        default=None,
        help="sector to process (omit to auto-detect the newest; see --hint)",
    )
    wat.add_argument(
        "--hint",
        type=int,
        default=1,
        help="starting sector for newest-sector probing when --sector is omitted "
        "(set near the current sector to avoid a slow probe from 1)",
    )
    wat.add_argument("--max", type=int, default=50, help="targets to scan this run")
    wat.add_argument("--out", default="watch_out", help="candidate output dir")
    wat.add_argument("--state", default="watch_state.json", help="resume state file")
    wat.add_argument(
        "--ffi",
        action="store_true",
        help="extract from Full-Frame Images via TESScut (note: the default pool "
        "is SPOC targets, which already have light curves)",
    )
    wat.add_argument(
        "--workers",
        type=int,
        default=4,
        help="parallel MAST downloads (network-bound; keep modest, 4-8)",
    )

    args = parser.parse_args(argv)

    if args.cmd == "run":
        records = run_target(
            args.tic,
            window_length=args.window,
            outdir=args.outdir,
            make_plots=not args.no_plot,
            sectors=args.sectors,
            source="ffi" if args.ffi else "spoc",
        )
        if not records:
            print(f"No candidates for TIC {args.tic} (nothing above SNR threshold).")
            return 0

        os.makedirs(args.outdir, exist_ok=True)
        for rec in records:
            path = os.path.join(args.outdir, f"tic{rec.tic}_s{rec.sector}.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(rec.to_json(indent=2))
            flag = f"  [known {rec.known_toi_id}]" if rec.known_toi_match else "  [not a known TOI]"
            eb = "  [likely EB]" if rec.likely_eb else ""
            print(
                f"S{rec.sector}: depth={rec.depth_ppt:.2f}ppt "
                f"dur={rec.duration_hr:.0f}h SNR={rec.snr:.1f}{flag}{eb} -> {path}"
            )
            if rec.period_constrained and rec.p_best_d:
                nxt = ""
                if rec.next_window_btjd:
                    nxt = f", next transit ~{_btjd_to_date(rec.next_window_btjd[1])}"
                print(
                    f"    P~{rec.p_best_d:.0f}d ({rec.p_lo_d:.0f}-{rec.p_hi_d:.0f}d, "
                    f"P_min {rec.p_min_d:.0f}d){nxt}"
                )
            elif rec.period_constrained is False:
                print("    period unconstrained (no reliable stellar density)")
        return 0

    if args.cmd == "anomaly":
        from .anomaly import run_anomaly

        results = run_anomaly(args.tic, sectors=args.sectors, window_length=args.window)
        if not results:
            print(f"No light curves for TIC {args.tic}.")
            return 0
        for sector, flares, dip in results:
            print(f"S{sector}: {len(flares)} flare(s); "
                  f"dipper={dip.is_dipper} ({dip.n_dips} guarded dips, "
                  f"interval CV {dip.interval_cv:.2f})")
            for fl in flares:
                print(f"    flare @ {fl.t_peak_btjd:.2f} BTJD  "
                      f"+{fl.amplitude_ppt:.1f}ppt  {fl.duration_hr:.1f}h  ({fl.n_points} pts)")
        return 0

    if args.cmd == "aggregate":
        candidates = aggregate(load_records(args.contributions))
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "leaderboard.json").write_text(render_json(candidates), encoding="utf-8")
        (out / "index.html").write_text(render_html(candidates), encoding="utf-8")
        novel = sum(1 for c in candidates if c.novel)
        print(
            f"{len(candidates)} candidates ({novel} not-yet-known) -> "
            f"{out / 'index.html'}"
        )
        return 0

    if args.cmd == "watch":
        from .watch import latest_sector, watch

        sector = args.sector
        if sector is None:
            sector = latest_sector(hint=args.hint)
            if sector is None:
                print(f"Could not detect a sector with data from hint {args.hint}.")
                return 1
            print(f"auto-detected newest sector: {sector}")
        res = watch(
            sector,
            outdir=args.out,
            state_path=args.state,
            max_targets=args.max,
            source="ffi" if args.ffi else "spoc",
            workers=args.workers,
        )
        print(
            f"sector {res.sector}: scanned {res.scanned}, "
            f"{len(res.novel)} novel, {res.remaining} remaining"
        )
        for rec in sorted(res.novel, key=lambda r: -r.snr):
            print(f"  NOVEL TIC {rec.tic} S{rec.sector} SNR {rec.snr:.0f} depth {rec.depth_ppt:.2f}ppt")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
