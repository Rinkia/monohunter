"""T6 — CLI: `monohunter run --tic <id>`.

End-to-end: search TESS -> detrend -> detect single transits -> write one JSON
find-record + PNG per candidate into the output dir.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .pipeline import run_target


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

    args = parser.parse_args(argv)

    if args.cmd == "run":
        records = run_target(
            args.tic,
            window_length=args.window,
            outdir=args.outdir,
            make_plots=not args.no_plot,
            sectors=args.sectors,
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
            print(
                f"S{rec.sector}: depth={rec.depth_ppt:.2f}ppt "
                f"dur={rec.duration_hr:.0f}h SNR={rec.snr:.1f}{flag} -> {path}"
            )
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
