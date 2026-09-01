"""Extended anomaly detectors — beyond flares/dippers into rarer light-curve classes.

Five model-light detectors, all pure math on arrays (offline-testable). None hits the
network; they run on the SAME already-downloaded flux the transit scan and summary use,
so a sweep classifies these at ~a few percent extra CPU. Each carries a `ponytail:`
comment naming the heuristic ceiling and the rigorous upgrade.

  1. deep irregular dimming  — Boyajian/KIC 8462852-like: deep (%-level) aperiodic dips.
  2. heartbeat stars         — eccentric binaries: a localized bipolar tidal pulse/orbit.
  3. pulsator subclass       — RR Lyrae / delta Scuti / gamma Dor from period+amp+shape.
  4. cataclysmic outbursts   — dwarf-nova/nova brightenings: sustained bright level-shifts.
  5. generalized anomaly score — a model-agnostic 0-1 "weirdness", the novelty ranker.

Guards: every detector masks non-finite input, returns a safe default below a minimum
sample size, and never divides by a zero scale — a degenerate light curve yields "no
anomaly", never a crash or a NaN verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .anomaly import _MAD_TO_SIGMA, _robust_sigma, _runs, find_flares, pull_guarded_dips

# ---- 1. deep irregular dimming (Boyajian-like) ---------------------------
# A "deep dipper" is the dipper class but with %-level depth on an otherwise quiet
# star — the KIC 8462852 signature. Depth is what separates it from ordinary young-star
# dippers; aperiodicity is what separates it from an eclipsing binary.
DEEP_DIP_MIN_PPT = 30.0       # >=3% — a genuinely deep dip, not a shallow YSO flicker
DEEP_DIP_MIN_COUNT = 2
DEEP_DIP_IRREGULAR_CV = 0.25  # spacing coefficient-of-variation above this = aperiodic


@dataclass(frozen=True)
class DeepDimmingResult:
    is_deep_dipper: bool
    n_dips: int
    max_depth_ppt: float
    interval_cv: float
    dip_times_btjd: tuple[float, ...]


def find_deep_dimming(
    time: np.ndarray, flux: np.ndarray, min_depth_ppt: float = DEEP_DIP_MIN_PPT,
) -> DeepDimmingResult:
    """Deep, aperiodic dimming events (Boyajian-star-like). Reuses the guarded dip pull,
    then keeps dips deeper than min_depth_ppt and asks whether they are many + irregular.

    ponytail: depth + spacing-CV heuristic. A dust-model / IR-excess cross-check (real
    dimming is dusty, not grey) is the rigorous confirmation — out of scope for photometry.
    """
    dips = pull_guarded_dips(time, flux)
    deep = [d for d in dips if d[1] >= min_depth_ppt]
    n = len(deep)
    max_depth = float(max((d[1] for d in deep), default=0.0))
    times = sorted(d[0] for d in deep)
    if n < 2:
        return DeepDimmingResult(False, n, max_depth, float("nan"), tuple(times))
    intervals = np.diff(times)
    mean_iv = float(np.mean(intervals))
    cv = float(np.std(intervals) / mean_iv) if mean_iv > 0 else float("nan")
    is_deep = n >= DEEP_DIP_MIN_COUNT and cv >= DEEP_DIP_IRREGULAR_CV and max_depth >= min_depth_ppt
    return DeepDimmingResult(is_deep, n, max_depth, cv, tuple(times))


# ---- 2. heartbeat stars --------------------------------------------------
# Eccentric binaries pulse once per orbit at periastron: a brief, phase-localized
# feature that is BIPOLAR (a brightening adjacent to a dip) rather than sinusoidal.
HEARTBEAT_MIN_PERIOD_D = 0.5
HEARTBEAT_MAX_PERIOD_D = 30.0
HEARTBEAT_PULSE_PHASE_FRAC = 0.15   # the pulse must live in <=15% of the orbital phase
HEARTBEAT_MIN_CONCENTRATION = 0.5   # >=50% of the folded variance inside that window
HEARTBEAT_BIPOLAR_SIGMA = 2.0       # both a + and - excursion beyond this many sigma


@dataclass(frozen=True)
class HeartbeatResult:
    is_heartbeat: bool
    period_d: float | None
    concentration: float            # fraction of folded variance inside the pulse window
    bipolar: bool


def _dominant_period(time, flux, p_min, p_max):
    from astropy.timeseries import LombScargle

    t = np.asarray(time, float)
    f = np.asarray(flux, float)
    good = np.isfinite(t) & np.isfinite(f)
    t, f = t[good], f[good]
    if t.size < 50:
        return None
    baseline = float(t.max() - t.min())
    if baseline <= 0:
        return None
    freq, power = LombScargle(t, f).autopower(
        minimum_frequency=1.0 / min(p_max, baseline),
        maximum_frequency=1.0 / p_min,
        samples_per_peak=5,
    )
    if power.size == 0:
        return None
    return float(1.0 / freq[int(np.argmax(power))])


def find_heartbeat(
    time: np.ndarray, raw_flux: np.ndarray,
    p_min: float = HEARTBEAT_MIN_PERIOD_D, p_max: float = HEARTBEAT_MAX_PERIOD_D,
) -> HeartbeatResult:
    """A phase-localized, bipolar pulse once per orbit = heartbeat star. Folds at the
    dominant period; the pulse is the narrowest phase window holding most of the folded
    variance, and it must contain BOTH a brightening and a dip.

    ponytail: shape heuristic (concentration + bipolarity). The rigorous test is fitting
    Kumar's analytic tidal-pulse model vs orbital phase — heavier, for a confirmed short list.
    """
    t = np.asarray(time, float)
    f = np.asarray(raw_flux, float)
    good = np.isfinite(t) & np.isfinite(f)
    t, f = t[good], f[good]
    if t.size < 100:
        return HeartbeatResult(False, None, 0.0, False)
    p0 = _dominant_period(t, f, p_min, p_max)
    if not p0 or p0 <= 0:
        return HeartbeatResult(False, None, 0.0, False)

    resid = f - np.median(f)
    total_var = float(np.sum(resid**2))
    if total_var <= 0:
        return HeartbeatResult(False, p0, 0.0, False)
    sigma = _robust_sigma(f)

    def _fold_concentration(period):
        """Best pulse window at this period: (concentration, bipolar)."""
        phase = ((t - t[0]) / period) % 1.0
        order = np.argsort(phase)
        ph, rs = phase[order], resid[order]
        width = HEARTBEAT_PULSE_PHASE_FRAC
        best_conc, best_lo = 0.0, 0.0
        for lo in np.linspace(0.0, 1.0 - width, 40):
            inside = (ph >= lo) & (ph < lo + width)
            conc = float(np.sum(rs[inside] ** 2)) / total_var
            if conc > best_conc:
                best_conc, best_lo = conc, lo
        win = rs[(ph >= best_lo) & (ph < best_lo + width)]
        bip = bool(sigma > 0 and win.size
                   and win.max() > HEARTBEAT_BIPOLAR_SIGMA * sigma
                   and win.min() < -HEARTBEAT_BIPOLAR_SIGMA * sigma)
        return best_conc, bip

    # LombScargle often locks onto a HARMONIC of the orbital period (a narrow pulse
    # spreads power to k/P). The true fundamental folds to ONE pulse/cycle = maximal
    # concentration, so test integer multiples of the LS peak and keep the best.
    candidates = [p0 * k for k in (1, 2, 3, 4, 5) if p_min <= p0 * k <= p_max]
    best = max(((c, b, p) for p in candidates for c, b in [_fold_concentration(p)]),
               key=lambda cbp: cbp[0], default=(0.0, False, p0))
    concentration, bipolar, period = best
    is_hb = concentration >= HEARTBEAT_MIN_CONCENTRATION and bipolar
    return HeartbeatResult(is_hb, period, concentration, bipolar)


# ---- 3. physical pulsator subclass ---------------------------------------
# Refine a periodic pulsator into RR Lyrae / delta Scuti / gamma Dor from period +
# amplitude + fold asymmetry. RR Lyrae (RRab) are the giveaway: large amplitude AND a
# sawtooth (fast rise, slow decline) that makes the folded curve strongly skewed.
RRL_PERIOD_D = (0.2, 1.0)
RRL_MIN_AMP_PPT = 50.0
RRL_MIN_SKEW = 0.3
DELTA_SCUTI_MAX_PERIOD_D = 0.3
GAMMA_DOR_PERIOD_D = (0.3, 3.0)


def fold_skew(time, flux, period) -> float:
    """Skewness of the phase-folded flux. A sawtooth (RR Lyrae) folds to a strongly
    skewed distribution; a pure sinusoid folds to ~0 skew. Pure."""
    t = np.asarray(time, float)
    f = np.asarray(flux, float)
    good = np.isfinite(t) & np.isfinite(f)
    t, f = t[good], f[good]
    if t.size < 20 or not period or period <= 0:
        return 0.0
    x = f - np.mean(f)
    s = float(np.std(x))
    if s <= 0:
        return 0.0
    return float(np.mean((x / s) ** 3))


def pulsator_subclass(period_d: float | None, amp_ppt: float, skew: float) -> str:
    """RR Lyrae / delta Scuti / gamma Dor / (generic) pulsator from period+amp+shape.

    ponytail: threshold cuts in the classic period-amplitude plane. A Fourier-parameter
    (R21/phi31) classifier is the standard rigorous method; these cuts catch the obvious
    RRab / high-amplitude delta Scuti without it.
    """
    if not period_d or period_d <= 0:
        return "pulsator"
    if (RRL_PERIOD_D[0] <= period_d <= RRL_PERIOD_D[1]
            and amp_ppt >= RRL_MIN_AMP_PPT and abs(skew) >= RRL_MIN_SKEW):
        return "rr_lyrae"
    if period_d < DELTA_SCUTI_MAX_PERIOD_D:
        return "delta_scuti"
    if GAMMA_DOR_PERIOD_D[0] <= period_d <= GAMMA_DOR_PERIOD_D[1]:
        return "gamma_dor"
    return "pulsator"


# ---- 4. cataclysmic / nova outbursts -------------------------------------
# A dwarf-nova outburst is a sustained brightening lasting DAYS — the opposite of a
# flare's minutes-hours decay. It must run on RAW flux: a 3-day detrend window flattens
# a multi-day outburst away.
OUTBURST_SIGMA = 5.0
OUTBURST_MIN_HOURS = 6.0        # >> a flare; a sustained level shift, not a spike


@dataclass(frozen=True)
class OutburstEvent:
    t_start_btjd: float
    duration_hr: float
    amplitude_ppt: float        # peak above quiescent baseline
    n_points: int


def find_outbursts(time: np.ndarray, raw_flux: np.ndarray) -> list[OutburstEvent]:
    """Sustained (>= OUTBURST_MIN_HOURS) bright level-shifts on RAW flux — candidate
    cataclysmic-variable / nova outbursts. Duration is what separates these from flares.

    ponytail: threshold + run-length on the quiescent MAD. A proper CV search would model
    the fast-rise/slow-decay outburst profile and the quiescent orbital hump.
    """
    t = np.asarray(time, float)
    f = np.asarray(raw_flux, float)
    good = np.isfinite(t) & np.isfinite(f)
    t, f = t[good], f[good]
    if t.size < 10:
        return []
    base = float(np.median(f))
    sigma = _robust_sigma(f)
    if sigma <= 0:
        return []
    above = f > base + OUTBURST_SIGMA * sigma
    out: list[OutburstEvent] = []
    for s, e in _runs(above):
        dur_hr = float((t[e] - t[s]) * 24.0)
        if dur_hr < OUTBURST_MIN_HOURS:
            continue
        seg = f[s : e + 1]
        out.append(OutburstEvent(
            t_start_btjd=float(t[s]),
            duration_hr=dur_hr,
            amplitude_ppt=float((float(np.max(seg)) - base) * 1e3),
            n_points=int(e - s + 1),
        ))
    return out


# ---- 5. generalized anomaly score ----------------------------------------
# A model-agnostic 0-1 "weirdness": a weighted blend of independent light-curve
# oddness indicators, each saturating so no single term dominates. Not a trained model
# — a transparent ranker so a sweep can surface the strangest curves for human eyes.
@dataclass(frozen=True)
class AnomalyScore:
    score: float                        # 0 (quiet) .. 1 (very unusual)
    components: dict = field(default_factory=dict)


def _sat(x: float, scale: float) -> float:
    """Saturating 0..1 map: x/scale clipped, so one big term can't blow past 1."""
    if scale <= 0:
        return 0.0
    return float(min(1.0, max(0.0, x / scale)))


def anomaly_score(time: np.ndarray, raw_flux: np.ndarray, flat_flux: np.ndarray) -> AnomalyScore:
    """Blend independent oddness indicators into a single 0-1 novelty score.

    Components (each saturated): variability amplitude, heavy-tailedness (excess
    kurtosis) of the flattened flux, flare count, deep-dip count, and outburst count.
    Higher = stranger. The transparent breakdown says WHY a star scored high.

    ponytail: hand-weighted composite, deliberately model-agnostic. A trained isolation
    forest over the catalog's feature table is the upgrade once enough sweeps are labelled.
    """
    t = np.asarray(time, float)
    raw = np.asarray(raw_flux, float)
    flat = np.asarray(flat_flux, float)
    gr = np.isfinite(t) & np.isfinite(raw)
    gf = np.isfinite(t) & np.isfinite(flat)
    if gr.sum() < 20:
        return AnomalyScore(0.0, {})

    amp_ppt = _MAD_TO_SIGMA * float(np.median(np.abs(raw[gr] - np.median(raw[gr])))) * 1e3
    x = flat[gf] - np.mean(flat[gf])
    s = float(np.std(x))
    ex_kurt = float(np.mean((x / s) ** 4) - 3.0) if s > 0 and x.size else 0.0
    n_flares = len(find_flares(t, flat))
    deep = find_deep_dimming(t, flat)
    n_out = len(find_outbursts(t, raw))

    comp = {
        "variability": _sat(amp_ppt, 20.0),        # 20 ppt = clearly variable
        "heavy_tails": _sat(ex_kurt, 10.0),         # fat-tailed flat flux (bursts/dips)
        "flares": _sat(n_flares, 5.0),
        "deep_dips": _sat(deep.n_dips, 3.0),
        "outbursts": _sat(n_out, 1.0),
    }
    weights = {"variability": 0.25, "heavy_tails": 0.2, "flares": 0.2,
               "deep_dips": 0.2, "outbursts": 0.15}
    score = float(sum(weights[k] * comp[k] for k in weights))
    return AnomalyScore(round(score, 4), {k: round(v, 3) for k, v in comp.items()})
