---
name: monohunter
description: >
  Activate when working on the monohunter project (the repo at
  C:\Projects\Varie\Space\lightKurve-wotan, github.com/Rinkia/monohunter): an
  open-source Python tool that finds single long-period ("mono-")transits and
  eclipsing binaries in public TESS light curves, predicts their next transit,
  AND turns each downloaded light curve into a stellar rotation/variability
  catalog. Triggers: editing monohunter modules (detect/box, characterize,
  ephemeris, pipeline, fetch, record, swarm/aggregate, watch, cli, ffi_batch,
  ground, anomaly, summary, completeness, novelty, vetting, triage, catalog_page);
  anything about TESS / exoplanet / transit / single-transit / light-curve
  detection; lightkurve, wotan, astroquery, TIC, BTJD; the leaderboard; the
  fresh-data watcher; FFI/TESScut extraction; ZTF/ASAS-SN; rotation periods;
  false-positive guards; VSX novelty; injection-recovery completeness; or running
  discovery sweeps over TESS sectors.
---

# monohunter

## Purpose
Amateur single-transit discovery pipeline over public TESS data. Strategic wedge:
**be FIRST to process fresh TESS data** + **make candidates confirmable** (predict
the next-transit window). End-to-end: fresh data → detect → characterize → period +
next-transit window → cross-facility confirmation → community leaderboard. Second
axis (proven high-value): **more science per download** — the same fetch that feeds
the transit scan also yields a rotation/variability/flare/dipper catalog.

## Architecture (module ownership)
```
fetch (search_tess, download_lightcurve+quality mask, get_stellar_density,
       search_tesscut/extract_ffi_lightcurve, socket timeout 180s)
  -> detrend (wotan biweight; window MUST be >> transit or it eats the dip)
  -> detect/ (Detector interface + BoxMatchedFilter; 7 guards + red-noise SNR;
              check_isolation toggle for the dipper path)
  -> characterize (fit_trapezoid; is_likely_eb: depth OR V-shape)
  -> crossmatch (known_toi, NASA Exoplanet Archive)
  -> ephemeris (estimate_period: posterior + next window + SNR/cadence gates,
                gap-aware p_min; period_from_transits: exact P from >=3 sectors)
  -> record (FindRecord pydantic, SCHEMA v6)  -> pipeline.build_record (SHARED)
  -> swarm/aggregate (contributions/ -> leaderboard JSON+HTML)
  -> watch (resumable, parallel --workers, --ffi, --summaries)
SIDE PRODUCTS (same download):
  summary (rotation via LombScargle on RAW flux + variability + flares + dippers)
    -> catalog CSV -> catalog_page (static HTML) -> Pages
  ffi_batch (one cutout -> many stars, crowding dedup, full records)
  ground (ZTF via IRSA + ASAS-SN via pyasassn: variability cross-check)
  anomaly (flares, dippers)   vetting (crowd label UI)   triage (ML rank)
  completeness (injection-recovery survey sensitivity)   novelty (VSX match)
  eb (orbital period from >=2 SAME-TYPE (primary) eclipses: eclipse_times, split by
      depth, period_from_transits on primaries only; lone primary+secondary =
      unrecoverable (eccentric secondary phase unknown) -> P None, no wrong period)
  rotation_plot (catalog CSV -> period-distribution + period-amplitude figure)
cli exposes: run aggregate watch ffi-batch ground anomaly vet triage-train
  triage summarize catalog catalog-page completeness novelty eb rotation-plot
```

## Key decisions
- **Detector is a seam.** BoxMatchedFilter is v1; keep detection out of fetch/cli.
- **Analytic over heavy.** Box scan not TLS; ~150-line numpy ephemeris not MonoTools.
- **Pure math modules, network in orchestrators.** ephemeris/detect/summary/
  completeness/anomaly cores take arrays -> unit-test offline; run_* fetch.
- **build_record is SHARED** by run_target + ffi_batch (DRY; both emit identical
  leaderboard-ready v6 records). Factor per-candidate assembly there.
- **Label, don't reject** (likely_eb, recurring_dip). EBs are real finds.
- **ρ* gate + SNR gate + cadence gate on the ephemeris** — never a confident wrong
  period. Low SNR OR coarse cadence (ingress unreliable) -> blind-b prior.
- **Rotation on RAW flux** — the 3d transit detrend WIPES rotation; summary runs
  LombScargle pre-detrend, flares/dippers on the flattened flux.
- **Completeness needs a QUIET base star** (detector returns only best candidate)
  and is star-noise-dependent -> survey number = MEAN over a sample.

## Detector guards (each a real FP class found by RUNNING on real data)
1. **SNR floor 7**, red-noise-aware (depth / robust-MAD-of-box-averaged-series).
2. **Edge-ramp**: trim EDGE_TRIM_D(0.5d)+half-box from sector ends.
3. **Isolation** (max_secondary_ratio 0.5): reject if a 2nd near-equal dip exists.
   `check_isolation=False` disables it for the dipper counter (a dipper IS multi-dip).
4. **Gap-span**: reject if box time-span >> width*cadence (straddles a gap).
5. **Gap-flanking-ramp**: trim around every internal gap boundary (0.2d).
6. **Scatter-stripe**: reject if >5% of BOX points >3σ ABOVE baseline.
7. **Scatter-region** (NEW): widen #6 to the event's ~1-day NEIGHBORHOOD — kills
   the box-beside-a-momentum-dump-patch FP. Data-driven, general, up-only.

RESIDUAL FP class = low-SNR (7-13) edge/gap/end-region ramps at each sector's
systematic times. Human PNG-vetting is the backstop. Do NOT add sector-specific
guards (overfit). Triage now ranks survivors so vetting goes to the real ones.

## Conventions
- **SCHEMA_VERSION v7** (v5 = n_sectors_observed+recurring_dip; v6 = measured_period_d,
  n_transits_used; v7 = edge_gap_dist_d + baseline_scatter_ppt, the FP features that
  generalize triage off the S14 hardcode). Additive optional only; old records still load.
- **SUMMARY schema v2** (v2 = subclass: eclipsing|pulsator|rotator refinement via
  periodogram harmonics + eclipse shape). Additive; old catalogs still load.
- Tests: REALISTIC sector-length curves (~15000 cadences). Wide dips for the box
  (>=2h). One runnable check per non-trivial logic; guards get a regression test.
- Commits: conventional, terse body, Co-Authored-By line. Every change: pytest -q
  then commit+push. ~135 tests + 1 slow (full run ~3.5min).
- **Sweeps are now a first-class command, not scratchpad scripts:** `watch --csv-log`
  writes the resumable per-star status CSV (errored stars left un-processed so a re-run
  retries only failures); `--max-hours` is a watchdog that force-exits a wedged run.
  One reproducible command replaces the old ThreadPoolExecutor sweep scripts.

## Commands
```bash
.venv/Scripts/python.exe -m pytest -q            # offline
monohunter run --tic <id> [--sectors N] [--ffi] [--summaries DIR]
monohunter watch --sector N [--workers 3] [--ffi] [--summaries DIR] \
   [--csv-log sweeps/sectorN.csv] [--max-hours 4]   # <- the sweep tool (resumable)
monohunter ffi-batch --tic <center> --sector N   # many stars, one cutout
monohunter summarize --tic <id>                   # rotation/variability/flares/dipper
monohunter summarize --from-catalog catalogs/sectorN.csv --outdir DIR --workers 4
   # batch-resummarize a catalog's stars (repopulate subclass etc.); resumable on a dir
monohunter catalog --summaries DIR --out csv      # parallel, pydantic-free
monohunter catalog-page --csv catalogs/sectorN.csv --sector N --out _site/catalog.html
monohunter ground --tic <id> --survey ztf|asassn  # variability cross-check
monohunter anomaly --tic <id>                     # flares + dippers
monohunter vet --candidates DIR --out _vet        # crowd label page
monohunter triage-train --labels labels/seed_labels.csv --sweeps sweeps
monohunter triage --candidates DIR                # rank by P(worth vetting)
monohunter completeness --tic <quiet> --sector N  # or --sample M --catalog CSV
monohunter novelty --tic <id> | --candidates DIR  # VSX known-vs-new
monohunter aggregate --contributions contributions --out _site
monohunter clean-cache [--dry-run]                # delete truncated partial FITS stubs
monohunter run --tic <id> --dry-run               # list available sectors, no download
monohunter watch --sector N --dry-run             # pool size + done/remaining, no download
monohunter triage --candidates DIR --top 10       # vetting short-list (N highest-ranked)
# release: bump pyproject.toml + monohunter/__init__.py + CHANGELOG.md
git tag vX.Y.Z && git push origin vX.Y.Z    # -> release.yml (PyPI OIDC) + docker.yml (GHCR)
# 24/7 deploy: docker compose up -d   (restart:always watcher on newest sector, ./data volume)
docker run --rm -v ./data:/data ghcr.io/rinkia/monohunter watch --sector N --csv-log ...
```
Sector pool: `Observations.query_criteria(obs_collection='TESS',
dataproduct_type='timeseries',sequence_number=N,t_exptime=120)`.

## Pitfalls (learned the hard way this session)
- **MAST download had NO timeout** -> a hung connection froze a sweep worker ~9h.
  Fixed: `socket.setdefaulttimeout(180)` in fetch.py. Under sweep CONTENTION,
  other MAST calls (completeness sample) can still time out -> guard per-star.
- **Truncated/corrupt FITS** raises `lightkurve.utils.LightkurveError` (NOT
  TypeError) inside entry.download() when it reads a cached partial. Caught in
  download_lightcurve -> None -> skip. Corrupt 64KB partials cache at
  `~/.cache/lightkurve/mastDownload/` — clear with `find ... -size 65536c -delete`.
- **Catalog build slowness was FILE I/O, not pydantic** (cold-disk open of 1000s
  of tiny files, ~45ms/file on Windows; a warm-cache benchmark hid it). Fixed:
  parallel reads + pydantic-free (load_summaries/write_catalog_csv). Local-only;
  CI reads the committed catalogs/sectorN.csv.
- **FFI period bias** was COARSE CADENCE not low SNR: a flooring of ingress error
  can't fix a biased ingress VALUE. Fix = cadence gate (blind-b if ingress spanned
  by <10 cadences). SNR gate is separate (noise-dominated ingress).
- **Completeness base star must be QUIET** (TOI-2180's own transit gave a false
  step-at-10ppt). Sensitivity is star-noise-dependent -> survey = mean over sample.
- **bg command stdout gets closed mid-run** (worker/astroquery stream) -> guard
  prints or write results to a file. bg commands DON'T inherit `cd` -> absolute
  venv path + os.chdir in-script.
- Detrend window too short EATS the transit. Ingress over-trust biases P high.
  Single-transit P is factor-few uncertain (report a RANGE). LF->CRLF warnings benign.
- **MAST transient outage looks like a code bug but ISN'T.** S16 sweep errored 60%
  yesterday; error text was a SQL-Server pre-login-handshake / "routing destination"
  message relayed from MAST's backend (its DB, not HTTP). Fast-fails, not 180s hangs.
  Recovered on retry (0 errors). Don't add code guards for it; just re-run. Sweep CSV
  stored only status=error (no message) -> the retry script logs the exception text.
- **Don't kill a sweep on the opening error burst.** I killed the S16 retry after
  seeing 25/25 error, but it had already recovered (MAST blip) and was ~56% success.
  Re-clean kept the good rows; relaunched. Watch for the rate to RECOVER before acting.
- **Eclipse finder fragments one dip into many** when a shallow/jagged eclipse crosses
  the threshold repeatedly (TIC 120239458: 1 secondary -> 4 "eclipses"). Fixed: merge
  runs within MIN_ECLIPSE_SEP_D (0.3d), keep deepest. Eclipse minima are argmin (jitter
  ~half width) -> EB_RESID_FRAC=0.05 loosens period_from_transits vs sharp transits.

## Reference facts
- Repo public. **PyPI: monohunter v0.5.1** (OIDC trusted publishing; releases cut by
  `git tag vX.Y.Z && git push` -> release.yml + docker.yml). Version history:
  v0.3.x = eb/rotation-plot/subclass/eclipse-merge; **v0.4.0** = watch-is-the-sweep-tool
  (`--csv-log` + auto-retry), triage generalized off S14 (schema v7), Gaia DR3 ρ*
  fallback, cross-sector EB periods, Colab quickstart + issue-form adoption;
  **v0.5.0** = Docker image + GHCR publish + 24/7 homelab compose watcher, `watch
  --max-hours` watchdog, Sector 18 catalog + vetted candidates. GHCR image:
  `ghcr.io/rinkia/monohunter:{X.Y.Z,latest}` built on every v* tag. **v0.5.1** =
  QoL CLI (summarize --from-catalog batch-resummarize, clean-cache, run/watch --dry-run,
  .jsonl summaries, triage --top).
- Leaderboard https://rinkia.github.io/monohunter/ + per-sector catalog pages
  (catalog_s15/16/17/18.html; catalog.html redirects to S15). pages.yml triggers on
  contributions/**, monohunter/swarm/**, catalog_page.py, catalogs/** and LOOPS every
  catalogs/sector*.csv -> one catalog_s<N>.html each (future sectors auto-publish, no
  CI edit). Each page embeds rotation_s<N>.png + a sector-nav button bar.
- **Survey to date: ~19,700 stars in committed catalogs over Sectors 15+16+17+18**
  (S14 also swept, not in a committed catalog). Many EBs (nearly all VSX-known),
  0 confirmed planets (expected survey-scale). 20 candidates on the leaderboard.
- **Live discovery targets (novel, VSX-clear, awaiting RV / 2nd transit):**
  - **TIC 400048097 (S17)** — bright Tmag 9.5, clean 2.5% flat-bottomed single transit,
    sharp ingress (not grazing), Gaia-ρ* period P~29d, next transit ~2026-08-29.
  - **TIC 22945095 (S18)** — 2.7% single transit, Gaia-ρ* P~12.5d, next transit
    ~2026-08-23 (tighter window than 400048097). Both in docs/followup-targets.md.
  - Historical best: TIC 298009554 (S15, 1.4% SNR 123, VSX-novel).
- **Vetting results by sector:** S16 8 novels -> **0 real** (all residual low-SNR FP;
  vetted 2026-08-31). S17 30 novels -> 4 vetted, 2 VSX-novel (400048097, 118182747
  deep-16%-EB). S18 36 novels -> 4 vetted (22945095 novel transit; 73487688 new 7% EB;
  13389059 = VSX NY Cep, eb recovered P=15.270d vs 15.276d; 125755686 deep EB).
- Canonical: TOI-2180 b = TIC 298663873 (transit S19, ~24h, P260.8d). TOI-813 b =
  TIC 55525572 (multi-sector; period_from_transits recovers 83.896d vs true 83.9d).
  Eccentric-EB regression: TIC 271763138 (VSX P=44.8d EA; in-sector eb returns None;
  cross-sector combined = 134.48d = 3x VSX 44.83d, documented sparse-epoch alias).
- Throughput ~1300 stars/hr at workers=3 (MAST-bound); workers>3-4 risks truncation.
- Committed catalogs (stars): sector15 8999, sector16 3382, sector17 3276, sector18
  4054. sector18 has subclass populated (875 rotator/492 variable/214 flaring/32 dipper);
  sector15/16 subclass predate the v0.3.2 fix (repopulate on a fresh sweep).
  labels/seed_labels.csv = 49 hand-vetted triage labels (LOO 96% after S18 retrain;
  log_baseline_scatter now carries a real negative weight).

## Publishing flow (vetted -> leaderboard; sweep -> catalog) — ALREADY WIRED
- **Vetted candidate -> leaderboard:** drop the candidate's record JSON into
  `contributions/<user>/` and push. pages.yml runs `aggregate` on contributions/**,
  rebuilding leaderboard.json + index.html. The vetting decision (human) is the only
  manual gate; there is no auto-promote from vet labels -> contributions (by design).
- **Sweep -> catalog:** build a catalog CSV from the sweep's summaries
  (`catalog --summaries <dir> --out catalogs/sector<N>.csv`), commit it. pages.yml's
  loop auto-builds catalog_s<N>.html + rotation_s<N>.png + adds it to every page's nav.

## Completed work (v0.2.0 + post-release)
Everything in v0.1.0 PLUS this session:
- **Guard #7** scatter-region; **ephemeris** SNR gate + cadence gate (FFI fix) +
  gap-aware p_min; **exact period** from multi-sector transit times.
- **Multi-sector validation** (recurring_dip, full-baseline p_min) v5; measured_period v6.
- **Anomaly** flares + guarded dippers. **FFI** single (--ffi) + **batch** (one
  cutout -> many stars, crowding dedup, full records via build_record).
- **Ground** ZTF (IRSA) + ASAS-SN (pyasassn, [ground] extra). **V-shape** in EB flag.
- **Crowd vetting UI** (static label page). **ML triage** (LogisticRegression on
  record features, LOO 92%). **Stellar summary** (rotation catalog) wired into the
  sweep loop -> catalog + catalog-page published to Pages.
- **Completeness** (injection-recovery, survey sensitivity). **Novelty** (VSX match:
  7/7 EBs = known variables incl alpha Dra; isolates true-new candidates).
- v0.2.0 RELEASED to PyPI + README/CHANGELOG + release banner on leaderboard.

## Completed this session (v0.3.0 -> v0.3.2)
- **eb** (EB orbital period from >=2 same-type eclipses; eclipse_times + primary/
  secondary depth split + period_from_transits on primaries; fragment-merge fix).
- **rotation-plot** (period distribution + period-amplitude figure from a catalog CSV).
- **subclass** (schema v2: eclipsing/pulsator/rotator via periodogram harmonics),
  wired into BOTH summary paths (run_summary + pipeline._write_summary — the sweep
  path was the v0.3.2 bug: computed subclass but dropped it -> all "quiet").
- **Sector 16 sweep resumed** (2976/5000 errored yesterday on a transient MAST
  outage; retry recovered all -> 4992 none + 8 novel, 0 error). Catalog rebuilt
  (3382 stars, merged yesterday's + retry summaries), committed as sector16.csv.
- **Pages:** rotation figure embedded in catalog pages; per-sector auto-build loop;
  sector-nav buttons; catalog.html redirect; leaderboard banner refreshed to 0.3.x;
  README documents eb/rotation-plot/subclass.

## v0.4.0 (RELEASED — 5 improvements)
1. **watch IS the sweep tool** — `--csv-log` writes the per-star status CSV (sweep
   schema); errored stars logged AND left un-processed so re-running retries only
   failures (kills the S16 manual-clean dance). One-command sweep. No more scratchpad
   sweep scripts to rebuild.
2. **Triage generalized off S14 hardcode (schema v7)** — records carry edge_gap_dist_d
   + baseline_scatter_ppt (computed in build_record); triage uses edge_gap_dist_d
   instead of S14_SYSTEMATIC_TIMES (legacy fallback keeps 92% LOO). Ranks ANY sector.
   `triage --min-prob` auto-cuts. NOTE scatter weight is latent until a new-schema
   sweep gets labelled; edge_gap generalization is active now.
3. **Gaia DR3 rho* fallback** (fetch.rho_from_logg_radius, = 3g/4piGR) when TIC has
   no density -> unblocks period for bright uncatalogued hosts. TIC 400048097:
   unconstrained -> P~29d + next transit ~2026-08-29.
4. **Cross-sector EB periods** — run_eb returns (per_sector, combined); combined
   stitches all sectors' eclipse times (eb_period_from_eclipses assume_adjacent=False).
   TIC 271763138 -> 134.48d = 3x VSX 44.83d (documented sparse-epoch integer alias).
5. **Adoption** — notebooks/monohunter_quickstart.ipynb (zero-install Colab + badge);
   .github/ISSUE_TEMPLATE/candidate.yml (issue-form submission for non-coders).
   SKIPPED: recent-finds gallery (needs committed PNGs).

## v0.5.0 (RELEASED — always-on deployment)
1. **Docker image + GHCR publish** — Dockerfile (python:3.12-slim, HOME+WORKDIR=/data
   shared volume, MPLBACKEND=Agg); docker.yml builds+pushes ghcr.io/rinkia/monohunter
   (:X.Y.Z + :latest) on every v* tag.
2. **24/7 homelab watcher** — docker-compose.yml restart:always service loops
   `monohunter watch` on the newest sector (auto-detected), resumable + self-healing
   (errored stars retry next cycle, corrupt FITS pruned), persists in ./data.
3. **`watch --max-hours` watchdog** — daemon-timer force-exits a run wedged on a hung
   MAST socket a worker thread can't kill; per-star state saved so nothing is lost.
4. **Sector 18 published** — 4054-star catalog + 4 vetted candidates (see reference facts);
   9 S18 labels retrain triage to 96% LOO, log_baseline_scatter gains real weight.
- Also shipped between v0.3.2 and v0.4.0: **S16 + S17 catalogs published to Pages**,
  **4 vetted S17 candidates** promoted (400048097 priority), followup-targets.md.

## Next steps / open
- **PRIORITY: the two live discovery targets** (400048097 S17, 22945095 S18) —
  ground photometry near their next-transit windows (~2026-08-23/29) to catch transit
  #2 and collapse the period; RV to get companion mass. This is the actual science
  output pending. See docs/followup-targets.md.
- **S19+ sweeps** — the pipeline is now one command (`watch --csv-log --max-hours`) and
  the compose watcher auto-picks the newest sector; just needs MAST headroom to run.
- **S16 8 novels VETTED (2026-08-31) -> 0 real.** PNG-checked all 7 low-SNR (7-9.6)
  survivors: every one is the residual edge/gap/scatter FP class (start-of-sector ramp,
  pre-gap scatter stripe, mid-gap flank). None promoted. TIC 120239458 = known deep EB.
  Nothing to contributions/. Confirms the skill's residual-FP prediction; don't re-vet.
- **Repopulate subclass on S15/S16** — now tooled: `summarize --from-catalog
  catalogs/sector15.csv --outdir DIR --workers 4` re-summarizes exactly those stars
  (resumable on a dir), then `catalog --summaries DIR --out catalogs/sector15.csv` +
  commit. Just needs the MAST headroom to run (~9k + 3.4k stars = hours).
- Live SURVEY-completeness demo (needs MAST headroom, no competing sweep).
- Gaia DR3 variability as a 2nd novelty source.
- Non-SPOC FFI POOL enumeration for a true FFI sweep. astroplan observability gate
  (compute whether a next-transit window is observable from a site). MonoTools --deep.
- If the catalog spans many sectors: sweep appends summaries to ONE JSONL (kill the
  small-files problem) instead of a file per star.
- DONE this line of work (don't re-open): triage generalized off S14 (v0.4.0 schema v7);
  cross-sector EB periods (v0.4.0); Gaia ρ* fallback (v0.4.0); S16/S17/S18 vetted.
```
