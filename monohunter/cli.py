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
    run.add_argument(
        "--summaries", default=None, metavar="DIR",
        help="also write a stellar summary (rotation/variability/flares/dipper) per "
        "sector here — a catalog product from the same download",
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

    fb = sub.add_parser(
        "ffi-batch",
        help="extract EVERY catalog star in one FFI cutout and scan each (reaches "
        "non-SPOC stars; one download amortized over many targets)",
    )
    fb.add_argument("--tic", type=int, required=True, help="TIC at the cutout center")
    fb.add_argument("--sector", type=int, required=True, help="sector to cut")
    fb.add_argument("--cutout", type=int, default=30, help="cutout side in pixels")
    fb.add_argument("--tmag-max", type=float, default=14.0, help="skip stars fainter than this")
    fb.add_argument("--outdir", default="ffi_candidates", help="where to write JSON + PNG")
    fb.add_argument("--no-plot", action="store_true", help="skip PNG generation")

    nv = sub.add_parser(
        "novelty",
        help="cross-match finds against the AAVSO Variable Star Index (VSX): known "
        "variable, or genuinely new?",
    )
    nv.add_argument("--tic", type=int, default=None, help="single target")
    nv.add_argument("--candidates", default=None, help="dir of record JSONs to batch-check")

    gr = sub.add_parser(
        "ground",
        help="cross-check a candidate against ground-survey photometry (ZTF): is "
        "the host quiet over years, or a variable star / EB?",
    )
    gr.add_argument("--tic", type=int, required=True, help="TESS Input Catalog id")
    gr.add_argument("--survey", default="ztf", choices=["ztf", "asassn"], help="ground survey")
    gr.add_argument(
        "--band", default=None,
        help="photometric band (default r for ztf, g for asassn; ZTF g/r/i, ASAS-SN g/V)",
    )

    comp = sub.add_parser(
        "completeness",
        help="survey sensitivity via injection-recovery: inject synthetic transits "
        "into a real light curve and measure the recovered fraction (use a QUIET star)",
    )
    comp.add_argument("--tic", type=int, default=None, help="single quiet star to inject into")
    comp.add_argument("--sector", type=int, required=True, help="sector")
    comp.add_argument("--n", type=int, default=20, help="injections per grid cell")
    comp.add_argument("--sample", type=int, default=None, metavar="M",
                      help="SURVEY mode: average over M stars stratified across the catalog's "
                      "noise range (needs --catalog)")
    comp.add_argument("--catalog", default=None, help="catalog CSV to draw the --sample from")

    sm = sub.add_parser(
        "summarize",
        help="per-star stellar summary from the same download: rotation, variability, "
        "flares, dipper (a catalog product, not just transit yes/no)",
    )
    sm.add_argument("--tic", type=int, required=True, help="TESS Input Catalog id")
    sm.add_argument("--sectors", type=int, nargs="+", default=None, help="restrict to sectors")
    sm.add_argument("--outdir", default="summaries", help="where to write summary JSON")

    ct = sub.add_parser("catalog", help="aggregate stellar summaries into one CSV catalog")
    ct.add_argument("--summaries", default="summaries", help="dir of summary JSONs")
    ct.add_argument("--out", default="catalog.csv", help="output CSV path")

    cp = sub.add_parser("catalog-page", help="render a catalog CSV into a static Pages HTML view")
    cp.add_argument("--csv", required=True, help="catalog CSV (from `catalog`)")
    cp.add_argument("--sector", type=int, required=True, help="sector number (for the title)")
    cp.add_argument("--out", default="_site/catalog.html", help="output HTML path")

    rp = sub.add_parser(
        "rotation-plot",
        help="population figure from a catalog CSV: rotation-period distribution + "
        "period-amplitude relation (a science plot from the sweep's rotators)",
    )
    rp.add_argument("--csv", required=True, help="catalog CSV (from `catalog`)")
    rp.add_argument("--sector", type=int, default=None, help="sector number (for the title)")
    rp.add_argument("--out", default="_site/rotation.png", help="output PNG path")

    eb = sub.add_parser(
        "eb",
        help="recover an eclipsing-binary orbital period from its in-sector eclipses "
        "(reuses the multi-transit period fit on eclipse times)",
    )
    eb.add_argument("--tic", type=int, required=True, help="TESS Input Catalog id")
    eb.add_argument("--window", type=float, default=3.0, help="detrend window in days")
    eb.add_argument("--sectors", type=int, nargs="+", default=None, help="restrict to sectors")

    tt = sub.add_parser("triage-train", help="train the ML triage model from labels + sweep CSVs")
    tt.add_argument("--labels", default="labels/seed_labels.csv", help="tic,label CSV (1=interesting)")
    tt.add_argument("--sweeps", default="sweeps", help="dir of sweep CSVs (feature source)")
    tt.add_argument("--out", default="triage_model.pkl", help="output model path")

    tr = sub.add_parser("triage", help="rank candidate records by P(worth vetting)")
    tr.add_argument("--model", default="triage_model.pkl", help="trained model path")
    tr.add_argument("--candidates", required=True, help="dir of candidate record JSONs")

    vet = sub.add_parser(
        "vet", help="build a static crowd-vetting page (candidate PNGs + label buttons)"
    )
    vet.add_argument("--candidates", default="candidates", help="dir of record JSONs + PNGs")
    vet.add_argument("--out", default="_vet", help="output dir for index.html + PNGs")

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
    wat.add_argument(
        "--summaries", default=None, metavar="DIR",
        help="also write a stellar summary per scanned star here (rotation/"
        "variability catalog from the same downloads)",
    )
    wat.add_argument(
        "--csv-log", default=None, metavar="CSV",
        help="append a provenance row per scanned star (tic,status,best_snr,...) "
        "here — the sweep scan-log a catalog/retry builds from. Errored stars are "
        "logged AND left un-processed so the next run retries them.",
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
            summaries_dir=args.summaries,
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
            rec_flag = "  [recurring: dips in >1 sector - periodic/variable]" if rec.recurring_dip else ""
            print(
                f"S{rec.sector}: depth={rec.depth_ppt:.2f}ppt "
                f"dur={rec.duration_hr:.0f}h SNR={rec.snr:.1f}{flag}{eb}{rec_flag} -> {path}"
            )
            if rec.measured_period_d:
                print(
                    f"    EXACT P = {rec.measured_period_d:.3f}d "
                    f"(fitted from {rec.n_transits_used} transit times)"
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

    if args.cmd == "novelty":
        from .novelty import check_novelty

        def _fmt(m):
            if m is None:
                return "not in VSX (novel)"
            p = f", P={m['period']:.3f}d" if m.get("period") else ""
            return f"KNOWN: VSX {m['name']} ({m['type']}{p}, {m['sep_arcsec']:.1f}\")"

        if args.candidates:
            import json as _json

            tics = []
            for jpath in sorted(Path(args.candidates).glob("*.json")):
                try:
                    tics.append(int(_json.loads(jpath.read_text(encoding="utf-8"))["tic"]))
                except Exception:
                    continue
            novel = 0
            for tic in sorted(set(tics)):
                m = check_novelty(tic)
                novel += m is None
                print(f"TIC {tic}: {_fmt(m)}")
            print(f"\n{novel}/{len(set(tics))} not in VSX (candidate discoveries).")
            return 0

        if args.tic is None:
            print("Give --tic <id> or --candidates <dir>.")
            return 1
        print(f"TIC {args.tic}: {_fmt(check_novelty(args.tic))}")
        return 0

    if args.cmd == "ground":
        from .ground import run_ground_check

        res = run_ground_check(args.tic, survey=args.survey, band=args.band)
        if res is None:
            print(f"No {args.survey.upper()} photometry for TIC {args.tic}.")
            return 0
        v = res.variability
        survey_name = {"ztf": "ZTF", "asassn": "ASAS-SN"}.get(args.survey, args.survey.upper())
        verdict = (
            "VARIABLE host -> likely a variable star / EB, not a clean mono-transit"
            if v.is_variable
            else "quiet host -> consistent with a clean single transit"
        )
        print(
            f"{survey_name} {res.band}-band TIC {args.tic}: "
            f"{v.n_epochs} epochs over {v.baseline_days:.0f}d, "
            f"amplitude {v.frac_amplitude * 100:.1f}% -> {verdict}"
        )
        return 0

    if args.cmd == "ffi-batch":
        from .ffi_batch import run_ffi_batch

        records, n_blended = run_ffi_batch(
            args.tic, args.sector, cutout_px=args.cutout, tmag_max=args.tmag_max,
            outdir=args.outdir, make_plots=not args.no_plot,
        )
        blend_note = f" ({n_blended} crowding blends collapsed)" if n_blended else ""
        print(
            f"FFI batch S{args.sector} around TIC {args.tic} "
            f"({args.cutout}x{args.cutout}px): {len(records)} detection(s){blend_note}"
        )
        os.makedirs(args.outdir, exist_ok=True)
        for rec in sorted(records, key=lambda r: -r.snr):
            path = os.path.join(args.outdir, f"tic{rec.tic}_s{rec.sector}.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(rec.to_json(indent=2))
            flag = f"  [known {rec.known_toi_id}]" if rec.known_toi_match else "  [not a known TOI]"
            eb = "  [likely EB]" if rec.likely_eb else ""
            print(
                f"  TIC {rec.tic}: depth={rec.depth_ppt:.2f}ppt dur={rec.duration_hr:.0f}h "
                f"SNR={rec.snr:.1f}{flag}{eb} -> {path}"
            )
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

    if args.cmd == "completeness":
        import csv as _csv

        from .completeness import (
            DEFAULT_DEPTHS_PPT,
            DEFAULT_DURATIONS_HR,
            completeness_depth,
            run_completeness,
            run_completeness_sample,
        )

        if args.sample:
            if not args.catalog:
                print("--sample needs --catalog (a catalog CSV to draw stars from).")
                return 1
            # stratify across the noise range so the sample represents the survey
            stars = [r for r in _csv.DictReader(open(args.catalog))
                     if r.get("var_class") == "quiet" and int(r.get("n_epochs", 0)) > 15000]
            stars.sort(key=lambda r: float(r["var_amplitude_ppt"]))
            if len(stars) < args.sample:
                print(f"Only {len(stars)} usable quiet stars in the catalog.")
                return 1
            step = len(stars) / args.sample
            tics = [int(stars[int(i * step)]["tic"]) for i in range(args.sample)]
            grid, n_used = run_completeness_sample(tics, args.sector, n=args.n)
            if grid is None:
                print("No usable stars (all had their own signal or failed to fetch).")
                return 0
            print(f"SURVEY injection-recovery: mean over {n_used} stars, S{args.sector}, "
                  f"{args.n} injections/cell. Recovered fraction:")
        else:
            if args.tic is None:
                print("Give --tic <quiet star>, or --sample M --catalog CSV for survey mode.")
                return 1
            grid, n_epochs, base_clean = run_completeness(args.tic, args.sector, n=args.n)
            if grid is None:
                print(f"No sector {args.sector} light curve for TIC {args.tic}.")
                return 0
            if not base_clean:
                print("WARNING: base star has its own detected signal — pick a quiet star "
                      "(low var_amplitude, no transit) or the grid will read low.")
            print(f"Injection-recovery on TIC {args.tic} S{args.sector} ({n_epochs} epochs), "
                  f"{args.n} injections/cell. Recovered fraction:")
        header = "depth\\dur | " + " ".join(f"{d:>5.0f}h" for d in DEFAULT_DURATIONS_HR)
        print(header)
        for depth in DEFAULT_DEPTHS_PPT:
            cells = " ".join(f"{grid[(depth, dur)]*100:>5.0f}%" for dur in DEFAULT_DURATIONS_HR)
            print(f"{depth:>6.1f}ppt | {cells}")
        for dur in DEFAULT_DURATIONS_HR:
            d50 = completeness_depth(grid, dur, 0.5)
            d90 = completeness_depth(grid, dur, 0.9)
            print(f"  {dur:.0f}h transit: 50% complete at "
                  f"{f'{d50:.1f}ppt' if d50 else '>10ppt'}, "
                  f"90% at {f'{d90:.1f}ppt' if d90 else '>10ppt'}")
        return 0

    if args.cmd == "summarize":
        from .summary import run_summary

        summaries = run_summary(args.tic, sectors=args.sectors)
        if not summaries:
            print(f"No light curves for TIC {args.tic}.")
            return 0
        os.makedirs(args.outdir, exist_ok=True)
        for s in summaries:
            path = os.path.join(args.outdir, f"tic{s.tic}_s{s.sector}.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(s.to_json(indent=2))
            rot = f"{s.rotation_period_d:.2f}d (power {s.rotation_power:.2f})" if s.rotation_period_d else (
                "systematic" if s.rotation_systematic else "none")
            print(
                f"S{s.sector}: {s.var_class} | amp {s.var_amplitude_ppt:.1f}ppt | "
                f"rotation {rot} | {s.n_flares} flare(s) | dipper={s.is_dipper} -> {path}"
            )
        return 0

    if args.cmd == "catalog":
        import collections as _c

        from .summary import load_summaries, write_catalog_csv

        rows = load_summaries(args.summaries)
        if not rows:
            print(f"No summaries found in {args.summaries}.")
            return 0
        write_catalog_csv(rows, args.out)
        by_class = _c.Counter(r.get("var_class", "quiet") for r in rows)
        print(f"{len(rows)} stars -> {args.out}  ({dict(by_class)})")
        return 0

    if args.cmd == "catalog-page":
        import shutil

        import re

        from .catalog_page import load_catalog, render_catalog_html
        from .rotation_plot import plot_rotation_distribution

        rows = load_catalog(args.csv)
        csv_name = os.path.basename(args.csv)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        # sibling sectors for the nav bar: every sectorN.csv beside this one
        sectors = sorted(
            int(m.group(1))
            for f in Path(args.csv).parent.glob("sector*.csv")
            if (m := re.fullmatch(r"sector(\d+)", f.stem))
        )
        # rotation-distribution figure next to the page, embedded in it
        plot_name = f"rotation_s{args.sector}.png"
        n_rot = plot_rotation_distribution(rows, str(out.parent / plot_name), sector=args.sector)
        out.write_text(
            render_catalog_html(rows, args.sector, csv_name, plot_name=plot_name, sectors=sectors),
            encoding="utf-8",
        )
        shutil.copy(args.csv, out.parent / csv_name)   # ship the CSV next to the page for download
        print(f"{len(rows)} stars ({n_rot} rotators) -> {out} (+ {csv_name}, {plot_name})")
        return 0

    if args.cmd == "rotation-plot":
        import csv as _csv

        from .rotation_plot import plot_rotation_distribution

        rows = list(_csv.DictReader(open(args.csv, encoding="utf-8")))
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        n = plot_rotation_distribution(rows, str(out), sector=args.sector)
        print(f"{n} rotators from {len(rows)} stars -> {out}")
        return 0

    if args.cmd == "eb":
        from .eb import run_eb

        results = run_eb(args.tic, sectors=args.sectors, window_length=args.window)
        if not results:
            print(f"No light curves for TIC {args.tic}.")
            return 0
        for sector, res in results:
            if res is None:
                print(f"S{sector}: no eclipse detected")
                continue
            sec = " (primary+secondary)" if res.secondary_detected else " (primaries only)"
            if res.orbital_period_d is not None:
                print(
                    f"S{sector}: {res.n_eclipses} eclipses ({res.n_primary} primary){sec} "
                    f"-> orbital P = {res.orbital_period_d:.3f}d"
                )
            else:
                print(
                    f"S{sector}: {res.n_eclipses} eclipses ({res.n_primary} primary){sec} "
                    f"-> period needs >=2 same-type eclipses (unrecoverable from this sector)"
                )
        return 0

    if args.cmd == "triage-train":
        from .triage import cross_val_accuracy, load_training_data, save_model, train

        X, y, tics = load_training_data(args.sweeps, args.labels)
        if len(y) < 4:
            print(f"Not enough labelled survivors found ({len(y)}); need >=4.")
            return 1
        acc = cross_val_accuracy(X, y)
        model = train(X, y)
        save_model(model, args.out)
        pos = int(sum(y))
        print(
            f"trained on {len(y)} labelled survivors ({pos} interesting / {len(y) - pos} junk), "
            f"leave-one-out accuracy {acc:.0%} -> {args.out}"
        )
        return 0

    if args.cmd == "triage":
        from .triage import load_model, rank_candidates

        model = load_model(args.model)
        ranked = rank_candidates(model, args.candidates)
        print(f"{len(ranked)} candidate(s) ranked by P(worth vetting):")
        for tic, sector, p in ranked:
            print(f"  P={p:.2f}  TIC {tic} S{sector}")
        return 0

    if args.cmd == "vet":
        from .vetting import build_vetting_site

        n = build_vetting_site(args.candidates, args.out)
        print(f"{n} candidate(s) -> {Path(args.out) / 'index.html'}")
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
            summaries_dir=args.summaries,
            csv_log=args.csv_log,
        )
        print(
            f"sector {res.sector}: scanned {res.scanned}, "
            f"{len(res.novel)} novel, {res.errors} error (will retry), "
            f"{res.remaining} remaining"
        )
        for rec in sorted(res.novel, key=lambda r: -r.snr):
            print(f"  NOVEL TIC {rec.tic} S{rec.sector} SNR {rec.snr:.0f} depth {rec.depth_ppt:.2f}ppt")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
