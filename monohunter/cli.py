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


def _summarize_from_catalog(args) -> int:
    """Batch-resummarize every (tic,sector) in a catalog CSV, in parallel.

    Repopulates fields the CSV can't hold (e.g. subclass) from the light curves.
    Downloads run in a thread pool; writes happen on the main thread as each future
    lands (dir per-file, or locked append for a .jsonl outdir). Resumable for a dir
    target (already-written stars skipped); per-TIC failures are counted, not fatal.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from contextlib import nullcontext

    from .progress import ProgressReporter, Watchdog
    from .summary import load_summaries, run_summary, tics_from_catalog, write_summary

    work = tics_from_catalog(args.from_catalog)
    if not work:
        print(f"No (tic,sector) rows in {args.from_catalog}.")
        return 1

    target = args.outdir
    is_jsonl = str(target).endswith(".jsonl")
    done: set[tuple[int, int]] = set()
    if not is_jsonl:
        done = {(int(r["tic"]), int(r["sector"])) for r in load_summaries(target)
                if "tic" in r and "sector" in r}
    todo = [ts for ts in work if ts not in done]
    skip_note = f" ({len(done)} already present, skipped)" if done else ""
    print(f"resummarize {len(todo)}/{len(work)} stars from {args.from_catalog} -> {target}{skip_note}")
    if not todo:
        return 0

    def _one(ts: tuple[int, int]):
        tic, sector = ts
        try:
            return ts, run_summary(tic, sectors=[sector]), None
        except Exception as exc:  # transient MAST / bad star -> count, keep going
            return ts, None, exc

    reporter = ProgressReporter(len(todo), label="stars",
                                slow_after_s=getattr(args, "slow_warn", 120.0))
    n_ok = n_err = 0
    # Optional wall-clock watchdog. Safe to hard-exit: a directory --outdir is resumable
    # (already-written stars are skipped on re-run), so nothing already done is lost.
    max_hours = getattr(args, "max_hours", None)
    watchdog = (
        Watchdog(max_hours, marker_path=str(target) + ".watchdog",
                 progress=lambda: f"{reporter.i}/{len(todo)} done, {n_err} failed")
        if max_hours and max_hours > 0 else nullcontext()
    )
    with watchdog:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(_one, ts): ts for ts in todo}
            for fut in as_completed(futures):
                ts, summaries, err = fut.result()
                if err is not None or not summaries:
                    n_err += 1
                    reporter.tick(f"TIC {ts[0]} S{ts[1]}", "failed/empty")
                    continue
                for s in summaries:
                    write_summary(target, s)
                n_ok += 1
                reporter.tick(f"TIC {ts[0]} S{ts[1]}", "ok")
    reporter.done()
    print(f"done: {n_ok} summarized, {n_err} failed/empty (re-run to retry).")
    return 0


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
        "--dry-run", action="store_true",
        help="list the sectors available for this TIC and exit (no download/detect)",
    )
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
        "sector here — a catalog product from the same download. A path ending in "
        ".jsonl appends one line per star to that single file instead of a dir of "
        "many small JSONs (faster to build a catalog from on a big sweep).",
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
    comp.add_argument("--plot", default=None, metavar="PNG",
                      help="also render the depth x duration recovery heatmap here "
                      "(the publishable survey-sensitivity figure)")
    comp.add_argument("--slow-warn", type=float, default=600.0, metavar="S",
                      help="warn when a single star's injection grid takes longer than "
                      "S seconds (a stall short of the network timeout)")

    sm = sub.add_parser(
        "summarize",
        help="per-star stellar summary from the same download: rotation, variability, "
        "flares, dipper (a catalog product, not just transit yes/no)",
    )
    sm.add_argument("--tic", type=int, default=None, help="TESS Input Catalog id (single star)")
    sm.add_argument("--sectors", type=int, nargs="+", default=None, help="restrict to sectors")
    sm.add_argument(
        "--from-catalog", default=None, metavar="CSV",
        help="batch: resummarize every (tic,sector) in a catalog CSV — repopulates "
        "fields the CSV can't hold (e.g. subclass) from the light curves. Resumable "
        "when --outdir is a directory (already-written stars are skipped); a .jsonl "
        "--outdir is one-shot (delete it before re-running to avoid duplicate rows).",
    )
    sm.add_argument("--workers", type=int, default=4,
                    help="parallel MAST downloads for --from-catalog (network-bound; 4-8)")
    sm.add_argument("--outdir", default="summaries", help="where to write summary JSON "
                    "(a path ending in .jsonl appends one line per star to one file)")
    sm.add_argument("--max-hours", type=float, default=None, metavar="H",
                    help="--from-catalog watchdog: force-exit past H hours (a hung socket "
                    "can wedge a worker). Resumable with a directory --outdir — re-run to continue.")
    sm.add_argument("--slow-warn", type=float, default=120.0, metavar="S",
                    help="--from-catalog: warn when a single star takes longer than S seconds")

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
    tr.add_argument("--min-prob", type=float, default=0.0, metavar="P",
                    help="only show candidates scoring >= P (auto-cut the junk tail)")
    tr.add_argument("--top", type=int, default=None, metavar="N",
                    help="show only the N highest-ranked candidates (the vetting short-list)")

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
        "variability catalog from the same downloads). A path ending in .jsonl appends "
        "one line per star to a single file — one open, not thousands of tiny files.",
    )
    wat.add_argument(
        "--csv-log", default=None, metavar="CSV",
        help="append a provenance row per scanned star (tic,status,best_snr,...) "
        "here — the sweep scan-log a catalog/retry builds from. Errored stars are "
        "logged AND left un-processed so the next run retries them.",
    )
    wat.add_argument(
        "--max-hours", type=float, default=None, metavar="H",
        help="safety net: force-exit if the run exceeds H hours (a hung MAST socket "
        "can wedge a worker forever). Resumable — re-run to continue. Set a bit above "
        "the expected runtime (e.g. 5 for a ~4h sweep).",
    )
    wat.add_argument(
        "--dry-run", action="store_true",
        help="report the sector's target-pool size, how many are already done, and "
        "how many this run would scan — then exit (no download). Sanity before a sweep.",
    )
    wat.add_argument(
        "--target-pool", default=None, metavar="FILE",
        help="scan the TIC ids in this file (one per line) instead of the sector's "
        "2-min SPOC pool — e.g. an ffi-pool list, with --ffi, for a true FFI sweep",
    )
    wat.add_argument("--slow-warn", type=float, default=120.0, metavar="S",
                     help="warn when a single star takes longer than S seconds (a stall)")

    fp = sub.add_parser(
        "ffi-pool",
        help="enumerate the non-SPOC FFI star pool for a sky region of a sector "
        "(catalog stars with no 2-min light curve) — feed to watch --ffi --target-pool",
    )
    fp.add_argument("--sector", type=int, required=True, help="sector to exclude the SPOC pool of")
    fp.add_argument("--tic", type=int, default=None, help="center on this TIC's RA/Dec")
    fp.add_argument("--ra", type=float, default=None, help="region center RA deg (or use --tic)")
    fp.add_argument("--dec", type=float, default=None, help="region center Dec deg")
    fp.add_argument("--radius", type=float, default=0.2, help="cone radius deg (keep small)")
    fp.add_argument("--tmag-max", type=float, default=14.0, help="skip stars fainter than this")
    fp.add_argument("--out", default="ffi_pool.txt", help="output TIC list (one per line)")

    cc = sub.add_parser(
        "clean-cache",
        help="delete truncated partial FITS (exact-size download stubs) from the "
        "lightkurve cache — a corrupt stub raises on read and can wedge a sweep",
    )
    cc.add_argument("--cache-dir", default=None,
                    help="cache root (default: lightkurve's own download cache)")
    cc.add_argument("--size", type=int, default=None, metavar="BYTES",
                    help="exact byte size of the partial stub to delete (default 65536)")
    cc.add_argument("--dry-run", action="store_true",
                    help="list what would be deleted, delete nothing")

    ob = sub.add_parser(
        "observe",
        help="is a predicted transit catchable from your site? Turn a next-transit "
        "window into 'target up + sky dark' clock-time intervals for a lat/lon",
    )
    ob.add_argument("--tic", type=int, default=None,
                    help="fetch the target's RA/Dec from MAST (or give --ra/--dec)")
    ob.add_argument("--ra", type=float, default=None, help="target RA deg (skip the MAST lookup)")
    ob.add_argument("--dec", type=float, default=None, help="target Dec deg")
    ob.add_argument("--record", default=None, metavar="JSON",
                    help="a candidate record JSON — pulls its TIC + next-transit window")
    ob.add_argument("--start", default=None, help="window start (ISO UTC or a raw BTJD float)")
    ob.add_argument("--end", default=None, help="window end (ISO UTC or a raw BTJD float)")
    ob.add_argument("--lat", type=float, required=True, help="observer latitude deg (+N)")
    ob.add_argument("--lon", type=float, required=True, help="observer longitude deg (+E)")
    ob.add_argument("--elev", type=float, default=0.0, help="observer elevation m")
    ob.add_argument("--min-alt", type=float, default=30.0, help="minimum target altitude deg")
    ob.add_argument("--sun-alt", type=float, default=-18.0,
                    help="Sun below this altitude deg = dark (-18 astronomical, -12 nautical)")
    ob.add_argument("--step", type=float, default=10.0, help="sampling step minutes")

    args = parser.parse_args(argv)

    if args.cmd == "run":
        if args.dry_run:
            if args.ffi:
                from .fetch import search_tesscut
                _sr, rows = search_tesscut(args.tic, sectors=set(args.sectors) if args.sectors else None)
            else:
                from .fetch import search_tess
                _sr, rows = search_tess(args.tic)
                if args.sectors:
                    rows = [r for r in rows if int(r["sector"]) in set(args.sectors)]
            secs = sorted({int(r["sector"]) for r in rows})
            src = "FFI" if args.ffi else "SPOC"
            print(f"TIC {args.tic}: {len(secs)} {src} sector(s) available: {secs or '(none)'}")
            return 0
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
        from .novelty import check_novelty, gaia_novelty

        def _fmt(m, g):
            parts = []
            if m is None:
                parts.append("not in VSX")
            else:
                p = f", P={m['period']:.3f}d" if m.get("period") else ""
                parts.append(f"VSX {m['name']} ({m['type']}{p}, {m['sep_arcsec']:.1f}\")")
            if g is None:
                parts.append("not a Gaia variable")
            else:
                parts.append(f"Gaia variable {g['class']} ({g['sep_arcsec']:.1f}\")")
            verdict = "NOVEL" if (m is None and g is None) else "KNOWN"
            return f"{verdict}: " + "; ".join(parts)

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
                m, g = check_novelty(tic), gaia_novelty(tic)
                novel += m is None and g is None
                print(f"TIC {tic}: {_fmt(m, g)}")
            print(f"\n{novel}/{len(set(tics))} unknown to BOTH VSX and Gaia (candidate discoveries).")
            return 0

        if args.tic is None:
            print("Give --tic <id> or --candidates <dir>.")
            return 1
        print(f"TIC {args.tic}: {_fmt(check_novelty(args.tic), gaia_novelty(args.tic))}")
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
        for r in results:
            dip = r.dipper
            print(f"S{r.sector}: anomaly score {r.anomaly_score:.2f} | "
                  f"{len(r.flares)} flare(s); "
                  f"dipper={dip.is_dipper} ({dip.n_dips} guarded dips, CV {dip.interval_cv:.2f})")
            if r.deep.is_deep_dipper:
                print(f"    DEEP DIMMING (Boyajian-like): {r.deep.n_dips} dips, "
                      f"max depth {r.deep.max_depth_ppt:.0f}ppt, CV {r.deep.interval_cv:.2f}")
            if r.heartbeat.is_heartbeat:
                print(f"    HEARTBEAT: P={r.heartbeat.period_d:.2f}d, "
                      f"pulse concentration {r.heartbeat.concentration:.2f}")
            for ob in r.outbursts:
                print(f"    OUTBURST @ {ob.t_start_btjd:.2f} BTJD  "
                      f"+{ob.amplitude_ppt:.0f}ppt  {ob.duration_hr:.1f}h")
            for fl in r.flares:
                print(f"    flare @ {fl.t_peak_btjd:.2f} BTJD  "
                      f"+{fl.amplitude_ppt:.1f}ppt  {fl.duration_hr:.1f}h  ({fl.n_points} pts)")
        return 0

    if args.cmd == "completeness":
        import csv as _csv

        from .completeness import (
            DEFAULT_DEPTHS_PPT,
            DEFAULT_DURATIONS_HR,
            completeness_depth,
            plot_completeness_grid,
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

            from .progress import ProgressReporter

            reporter = ProgressReporter(len(tics), label="stars", slow_after_s=args.slow_warn)
            grid, n_used = run_completeness_sample(
                tics, args.sector, n=args.n,
                progress=lambda i, total, tic, status: reporter.tick(f"TIC {tic}", status),
            )
            reporter.done()
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
        if args.plot:
            title = (f"Completeness — S{args.sector} survey"
                     if args.sample else f"Completeness — TIC {args.tic} S{args.sector}")
            plot_completeness_grid(grid, args.plot, title=title)
            print(f"heatmap -> {args.plot}")
        return 0

    if args.cmd == "summarize":
        from .summary import run_summary, write_summary

        if args.from_catalog:
            return _summarize_from_catalog(args)

        if args.tic is None:
            print("Give --tic <id> (single star) or --from-catalog <CSV> (batch).")
            return 1
        summaries = run_summary(args.tic, sectors=args.sectors)
        if not summaries:
            print(f"No light curves for TIC {args.tic}.")
            return 0
        for s in summaries:
            write_summary(args.outdir, s)
            rot = f"{s.rotation_period_d:.2f}d (power {s.rotation_power:.2f})" if s.rotation_period_d else (
                "systematic" if s.rotation_systematic else "none")
            print(
                f"S{s.sector}: {s.var_class}/{s.subclass} | amp {s.var_amplitude_ppt:.1f}ppt | "
                f"rotation {rot} | {s.n_flares} flare(s) | dipper={s.is_dipper}"
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

        per_sector, combined = run_eb(args.tic, sectors=args.sectors, window_length=args.window)
        if not per_sector:
            print(f"No light curves for TIC {args.tic}.")
            return 0
        for sector, res in per_sector:
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
        if combined is not None and combined.orbital_period_d is not None:
            print(
                f"ALL SECTORS: {combined.n_eclipses} eclipses ({combined.n_primary} primary) "
                f"-> stitched orbital P = {combined.orbital_period_d:.4f}d "
                f"(may be an integer multiple of the true period — sparse cross-sector "
                f"eclipses alias to P*k)"
            )
        elif combined is not None:
            print(
                f"ALL SECTORS: {combined.n_eclipses} eclipses ({combined.n_primary} primary) "
                f"-> still unrecoverable (need >=3 primaries, or 2 + a period guess)"
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
        shown = [r for r in ranked if r[2] >= args.min_prob]
        cut = len(ranked) - len(shown)
        notes = []
        if cut:
            notes.append(f"{cut} below P={args.min_prob:.2f}")
        if args.top is not None and len(shown) > args.top:
            notes.append(f"top {args.top} of {len(shown)}")
            shown = shown[:args.top]
        note = f" ({'; '.join(notes)})" if notes else ""
        print(f"{len(shown)}/{len(ranked)} candidate(s) by P(worth vetting){note}:")
        for tic, sector, p in shown:
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
        pool = None
        if args.target_pool:
            pool = [int(x) for x in Path(args.target_pool).read_text().split() if x.strip()]
        if args.dry_run:
            from .watch import load_state, pending_targets, sector_targets

            tics = pool if pool is not None else sector_targets(sector)
            label = "target-pool" if pool is not None else "SPOC"
            state = load_state(args.state)
            remaining = pending_targets(state, sector, tics, None)
            this_run = pending_targets(state, sector, tics, args.max)
            done = len(tics) - len(remaining)
            print(
                f"sector {sector}: pool {len(tics)} {label} targets, {done} done, "
                f"{len(remaining)} remaining; this run would scan {len(this_run)} "
                f"(--max {args.max})."
            )
            return 0
        res = watch(
            sector,
            outdir=args.out,
            state_path=args.state,
            max_targets=args.max,
            target_pool=pool,
            source="ffi" if args.ffi else "spoc",
            workers=args.workers,
            summaries_dir=args.summaries,
            csv_log=args.csv_log,
            max_hours=args.max_hours,
            show_progress=True,
            slow_after_s=args.slow_warn,
        )
        print(
            f"sector {res.sector}: scanned {res.scanned}, "
            f"{len(res.novel)} novel, {res.errors} error (will retry), "
            f"{res.remaining} remaining"
        )
        for rec in sorted(res.novel, key=lambda r: -r.snr):
            print(f"  NOVEL TIC {rec.tic} S{rec.sector} SNR {rec.snr:.0f} depth {rec.depth_ppt:.2f}ppt")
        return 0

    if args.cmd == "clean-cache":
        from .fetch import CORRUPT_FITS_SIZE, clean_cache, default_cache_dir, find_corrupt_fits

        cache = Path(args.cache_dir) if args.cache_dir else default_cache_dir()
        size = args.size if args.size is not None else CORRUPT_FITS_SIZE
        hits = find_corrupt_fits(cache, size)
        if not hits:
            print(f"No {size}-byte partial FITS under {cache}.")
            return 0
        if args.dry_run:
            for p in hits:
                print(f"  would delete {p}")
            print(f"{len(hits)} file(s), {len(hits) * size / 1024:.0f} KiB (dry-run; nothing deleted).")
            return 0
        n, freed = clean_cache(cache, size, dry_run=False)
        print(f"deleted {n} partial FITS, freed {freed / 1024:.0f} KiB from {cache}.")
        return 0

    if args.cmd == "ffi-pool":
        from .ffi_batch import ffi_star_pool

        ra, dec = args.ra, args.dec
        if ra is None or dec is None:
            if args.tic is None:
                print("Give --ra/--dec or --tic for the region center.")
                return 1
            from .fetch import fetch_coords

            ra, dec = fetch_coords(int(args.tic))
            if ra is None:
                print(f"Could not fetch coordinates for TIC {args.tic}.")
                return 1
        pool = ffi_star_pool(args.sector, ra, dec, args.radius, tmag_max=args.tmag_max)
        Path(args.out).write_text("\n".join(str(t) for t in pool) + "\n", encoding="utf-8")
        print(
            f"S{args.sector} FFI pool around RA {ra:.4f} Dec {dec:.4f} r={args.radius}deg: "
            f"{len(pool)} non-SPOC stars -> {args.out}\n"
            f"sweep them: monohunter watch --sector {args.sector} --ffi --target-pool {args.out}"
        )
        return 0

    if args.cmd == "observe":
        return _observe(args)

    return 1


def _parse_time_to_btjd(s: str) -> float:
    """A raw BTJD float passes through; anything else is parsed as an ISO UTC time."""
    try:
        return float(s)
    except ValueError:
        from astropy.time import Time

        from .observability import _BTJD_OFFSET

        return float(Time(s, scale="utc").tdb.jd) - _BTJD_OFFSET


def _observe(args) -> int:
    import json as _json

    from .observability import btjd_to_utc_iso, interval_hours, observable_windows

    # --- target coordinates: explicit --ra/--dec, else a TIC (from --record or --tic) ---
    ra, dec = args.ra, args.dec
    tic = args.tic
    window = None
    if args.record:
        rec = _json.loads(Path(args.record).read_text(encoding="utf-8"))
        tic = tic or rec.get("tic")
        window = rec.get("next_window_btjd")
    if (ra is None or dec is None):
        if tic is None:
            print("Give --ra/--dec, or --tic/--record so the RA/Dec can be looked up.")
            return 1
        from .fetch import fetch_coords

        ra, dec = fetch_coords(int(tic))
        if ra is None:
            print(f"Could not fetch coordinates for TIC {tic}.")
            return 1

    # --- window: explicit --start/--end, else the record's next-transit window ---
    if args.start and args.end:
        t0, t1 = _parse_time_to_btjd(args.start), _parse_time_to_btjd(args.end)
    elif window:
        t0, t1 = float(window[0]), float(window[-1])   # [5%, ..., 95%] -> full span
    else:
        print("Give --start and --end, or --record with a next-transit window.")
        return 1

    ivals = observable_windows(
        ra, dec, t0, t1, args.lat, args.lon,
        elevation_m=args.elev, min_alt_deg=args.min_alt,
        sun_alt_deg=args.sun_alt, step_min=args.step,
    )
    who = f"TIC {tic}" if tic else f"RA {ra:.4f} Dec {dec:.4f}"
    print(
        f"{who} at lat {args.lat:+.2f} lon {args.lon:+.2f}: window "
        f"{btjd_to_utc_iso(t0)} -> {btjd_to_utc_iso(t1)}, "
        f"alt>={args.min_alt:.0f} & Sun<={args.sun_alt:.0f}:"
    )
    if not ivals:
        print("  not observable — target never both up and dark during the window.")
        return 0
    for a, b in ivals:
        print(f"  {btjd_to_utc_iso(a)} -> {btjd_to_utc_iso(b)}  ({(b - a) * 24:.1f}h)")
    print(f"  total observable: {interval_hours(ivals):.1f}h across {len(ivals)} window(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
