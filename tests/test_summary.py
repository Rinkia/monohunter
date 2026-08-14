"""Summary tests — Lomb-Scargle rotation + classification (pure, offline)."""

import numpy as np

from monohunter.summary import (
    TESS_SYSTEMATIC_PERIODS_D,
    _classify,
    rotation_period,
    summarize,
)


def _time(n=15000):
    return np.arange(n) * (2.0 / (60 * 24))  # ~21 d at 2-min cadence


def test_rotation_recovers_injected_period():
    t = _time()
    rng = np.random.default_rng(0)
    p = 4.3
    flux = 1.0 + 0.02 * np.sin(2 * np.pi * t / p) + rng.normal(0, 5e-4, t.size)
    period, power, systematic = rotation_period(t, flux)
    assert systematic is False
    assert period is not None
    assert abs(period - p) < 0.1
    assert power > 0.1


def test_flat_star_has_no_rotation():
    t = _time()
    rng = np.random.default_rng(1)
    flux = 1.0 + rng.normal(0, 5e-4, t.size)
    period, power, systematic = rotation_period(t, flux)
    assert period is None and systematic is False


def test_tess_orbit_period_is_flagged_systematic():
    t = _time()
    rng = np.random.default_rng(2)
    p = TESS_SYSTEMATIC_PERIODS_D[0]  # ~13.7 d spacecraft orbit
    flux = 1.0 + 0.03 * np.sin(2 * np.pi * t / p) + rng.normal(0, 5e-4, t.size)
    period, power, systematic = rotation_period(t, flux)
    assert systematic is True          # not reported as a rotation period
    assert period is None


def test_classify_priority():
    assert _classify(period=4.0, amp_ppt=20, n_flares=0, is_dipper=True) == "dipper"
    assert _classify(period=4.0, amp_ppt=20, n_flares=5, is_dipper=False) == "flaring"
    assert _classify(period=4.0, amp_ppt=20, n_flares=0, is_dipper=False) == "rotator"
    assert _classify(period=None, amp_ppt=20, n_flares=0, is_dipper=False) == "variable"
    assert _classify(period=None, amp_ppt=1.0, n_flares=0, is_dipper=False) == "quiet"


def test_load_summaries_and_write_catalog(tmp_path):
    import csv

    from monohunter.summary import StellarSummary, load_summaries, write_catalog_csv

    # two summary JSONs on disk (as the sweep writes them)
    for tic, cls in [(1, "rotator"), (2, "quiet")]:
        s = StellarSummary(tic=tic, sector=15, cadence_s=120, n_epochs=17000,
                           var_amplitude_ppt=9.0, var_class=cls)
        (tmp_path / f"tic{tic}_s15.json").write_text(s.to_json(), encoding="utf-8")
    (tmp_path / "junk.json").write_text("not json", encoding="utf-8")  # skipped, not fatal

    rows = load_summaries(str(tmp_path))
    assert len(rows) == 2                                  # bad file dropped
    assert {r["tic"] for r in rows} == {1, 2}

    out = tmp_path / "catalog.csv"
    write_catalog_csv(rows, str(out))
    got = list(csv.DictReader(open(out)))
    assert len(got) == 2
    assert set(got[0].keys()) == set(StellarSummary.model_fields.keys())  # canonical columns


def test_summarize_rotator():
    t = _time()
    rng = np.random.default_rng(3)
    raw = 1.0 + 0.02 * np.sin(2 * np.pi * t / 4.3) + rng.normal(0, 5e-4, t.size)
    # a transit-flattened copy: the rotation removed, flat baseline (no flares/dips)
    flat = 1.0 + rng.normal(0, 5e-4, t.size)
    res = summarize(t, raw, flat)
    assert res.var_class == "rotator"
    assert res.rotation_period_d is not None
    assert res.var_amplitude_ppt > 5.0     # 2% sine is clearly variable


def test_harmonic_ratio_pure_sine_is_small():
    from monohunter.summary import harmonic_ratio

    t = _time()
    flux = 1.0 + 0.02 * np.sin(2 * np.pi * t / 6.0)
    assert harmonic_ratio(t, flux, 6.0) < 0.1


def test_subclass_pulsator_vs_rotator():
    from monohunter.summary import _subclass

    t = _time()
    rng = np.random.default_rng(7)
    flat = 1.0 + rng.normal(0, 5e-4, t.size)     # no eclipses
    # pure long-period sinusoid -> pulsator
    puls = 1.0 + 0.02 * np.sin(2 * np.pi * t / 8.0) + rng.normal(0, 5e-4, t.size)
    assert _subclass("rotator", 8.0, t, puls, flat) == "pulsator"
    # sine + strong 2nd harmonic (spot-shaped) -> rotator
    spot = (1.0 + 0.02 * np.sin(2 * np.pi * t / 8.0)
            + 0.012 * np.sin(4 * np.pi * t / 8.0 + 0.7) + rng.normal(0, 5e-4, t.size))
    assert _subclass("rotator", 8.0, t, spot, flat) == "rotator"


def test_subclass_eclipsing_wins():
    from monohunter.summary import _subclass

    t = _time()
    flat = 1.0 + np.random.default_rng(8).normal(0, 5e-4, t.size)
    for tc in (5.0, 12.0):
        flat[np.abs(t - tc) < 0.05] -= 0.1       # two eclipses in the flattened curve
    raw = 1.0 + 0.02 * np.sin(2 * np.pi * t / 8.0)
    assert _subclass("rotator", 8.0, t, raw, flat) == "eclipsing"
