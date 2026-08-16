# Follow-up targets

Vetted monohunter candidates that warrant follow-up (radial velocity, stellar
characterization, or catching a second transit). A candidate here is a *real,
human-vetted* single-transit-like event that is **not** a known TOI and **not**
in the AAVSO Variable Star Index (VSX) — i.e. potentially unclassified. A
candidate is not a discovery: confirming a planet needs follow-up beyond this
tool.

---

## TIC 400048097 — clean 2.5% single transit (priority)

The best single-candidate result of the survey so far: a bright, uncatalogued
star showing one clean, flat-bottomed transit.

| Property | Value |
|---|---|
| RA / Dec (J2000) | 18.46387°, +31.81948°  (01h13m51.3s, +31°49′10″) |
| Tmag | 9.53 (bright — accessible to modest RV facilities) |
| Sector | TESS S17 (2-min SPOC) |
| Transit epoch t0 | BTJD 1778.7007 (≈ 2019-11-13 UTC) |
| Depth | 24.6 ppt (2.5%) |
| Duration (T14) | 8.4 h |
| Ingress | 1.44 h — **sharp / flat-bottomed, not V-shaped** |
| SNR | 172 |
| likely_eb | False (depth < 3%, not V-shaped) |
| Known TOI | No |
| VSX | **Not in VSX (uncatalogued)** |
| Period | **P ≈ 29 d** (18–59 d, 16–84%) — from a Gaia DR3 ρ\* (TIC had none) |
| ρ\* | 0.35 g/cm³ (≈0.25 ρ⊙; from Gaia DR3 logg + radius) |
| Next transit | **≈ 2026-08-29** (5–95% window; wide — the period range is broad) |
| P_min | 14.0 d (a second transit would have shown within the sector baseline) |
| n_sectors | 1 (single sector; not recurring) |

### Why it's interesting
- **Not a known variable, not a known planet.** Clears both the VSX and TOI
  cross-checks — the actual discovery target, not another catalogued EB.
- **Shape favours a transit over a grazing EB.** The ingress is a small fraction
  of the duration (1.4 h of 8.4 h) → flat-bottomed, central (b≈0), not the
  V-shape of a grazing eclipse. Depth 2.5% is consistent with a large planet /
  brown dwarf / small star; RV separates these.
- **Bright (Tmag 9.5).** A single spectrum yields stellar parameters (hence a
  period estimate) and RV is feasible.

### What's needed
1. **Second transit to pin the period.** The Gaia-ρ\* estimate gives P ≈ 29 d
   (18–59 d) and a next-transit window around **2026-08-29** — wide, so a few
   nights of photometric monitoring bracketing that date could catch transit #2
   and collapse the period. Later TESS sectors also help.
2. **Radial velocity** to measure the companion mass (planet vs brown dwarf vs
   star) — the star is bright (Tmag 9.5), so this is feasible.
3. **Tighter stellar parameters** (a spectrum) would narrow ρ\*, hence the period
   and the transit window.

### Provenance
Found in the S17 discovery sweep (5000 SPOC targets, 2026-08). One of 30 novel
survivors; PNG-vetted (clean isolated transit on a flat baseline), VSX-novel.
On the leaderboard: `contributions/Rinkia/tic400048097_s17.json`.

---

## TIC 22945095 — novel 2.7% transit, near-term window (Sector 18)

A second strong single-transit candidate — novel (not in VSX), not EB-flagged, and
with a **tighter** period than 400048097 thanks to a Gaia-derived ρ\*.

| Property | Value |
|---|---|
| Sector | TESS S18 (2-min SPOC) |
| Depth | 27 ppt (2.7%) |
| Duration (T14) | 2.4 h (short — fast transit) |
| Ingress | 0.89 h |
| SNR | 77 |
| likely_eb | False |
| VSX | **Not in VSX (uncatalogued)** |
| Period | **P ≈ 12.5 d** (9.5–26 d) — from a Gaia DR3 ρ\* |
| Next transit | **≈ 2026-08-23** (window is narrower than 400048097's) |
| Baseline scatter | 0.68 ppt (clean host) |

The short 2.4 h duration at 2.7 % depth hints at a small/dense host or a grazing
geometry; RV separates the cases. The next-transit window is only ~a week out and
narrower than 400048097's, so ground photometric follow-up is more tractable here.
On the leaderboard: `contributions/Rinkia/tic22945095_s18.json`.

## Other novel finds (lower priority)

- **TIC 73487688** (S18) — new deep ~7% eclipsing binary (VSX-novel). A new EB.

- **TIC 118182747** (S17) — genuinely new deep 16% eclipsing binary (not in VSX).
  Too deep for a planet; a new EB, worth a note but not planet follow-up.
