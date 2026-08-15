"""T6/T7 tests — pipeline assembles a valid FindRecord end to end, no network.

We fake the two network touchpoints (search_tess, known_toi) and feed a light
curve with an injected dip through the real detrend + detect + record path.
"""

import numpy as np

from monohunter import pipeline
from monohunter.record import FindRecord


class _FakeQuantity:
    def __init__(self, arr):
        self.value = np.asarray(arr, dtype=float)


class _FakeLC:
    def __init__(self, time, flux):
        self.time = _FakeQuantity(time)
        self.flux = _FakeQuantity(flux)

    def remove_nans(self):
        return self

    def normalize(self):
        return self


class _FakeSel:
    def __init__(self, lc):
        self._lc = lc

    def download(self):
        return self._lc


class _FakeSR:
    def __init__(self, lc):
        self._lc = lc

    def __getitem__(self, idx):
        return _FakeSel(self._lc)


def _lc_with_dip(t0_offset_d=0.0, seed=3, with_dip=True):
    dt = 2.0 / (60 * 24)  # 2-min cadence in days
    time = np.arange(15000) * dt + t0_offset_d  # realistic ~21-day sector length
    rng = np.random.default_rng(seed)
    flux = 1.0 + rng.normal(0, 5e-4, size=time.size)
    if with_dip:
        c = time.size // 2
        flux[c - 360 : c + 360] -= 6e-3  # ~24h, 6 ppt dip
    return time, flux


class _FakeMultiSR:
    """Maps each row's _index to its own (time, flux) light curve."""

    def __init__(self, lcs_by_index):
        self._lcs = lcs_by_index

    def __getitem__(self, idx):
        return _FakeSel(_FakeLC(*self._lcs[idx]))


def test_run_target_builds_valid_record(monkeypatch, tmp_path):
    time, flux = _lc_with_dip()
    fake_sr = _FakeSR(_FakeLC(time, flux))
    rows = [{"sector": 25, "cadence_s": 120, "_index": 0}]

    monkeypatch.setattr(pipeline, "search_tess", lambda tic: (fake_sr, rows))
    monkeypatch.setattr(pipeline, "known_toi", lambda tic: (True, "TOI-2180"))
    monkeypatch.setattr(pipeline, "get_stellar_density", lambda tic: (0.3, 0.05))

    records = pipeline.run_target(
        298663873, outdir=str(tmp_path), make_plots=True
    )

    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, FindRecord)
    assert rec.tic == 298663873
    assert rec.sector == 25
    assert rec.known_toi_match is True
    assert rec.known_toi_id == "TOI-2180"
    assert rec.snr >= 7.0
    assert rec.plot_path is not None
    # ephemeris populated (ρ* supplied)
    assert rec.stellar_density_cgs == 0.3
    assert rec.likely_eb is False          # 6 ppt dip is planet-depth, not an EB
    assert rec.period_constrained is True
    assert rec.p_best_d and rec.p_best_d > rec.p_min_d
    assert rec.next_window_btjd and len(rec.next_window_btjd) == 3
    # single sector -> not recurring
    assert rec.n_sectors_observed == 1
    assert rec.recurring_dip is False
    # plot actually written
    import os

    assert os.path.exists(rec.plot_path)


def test_missing_density_leaves_period_unconstrained(monkeypatch, tmp_path):
    time, flux = _lc_with_dip()
    fake_sr = _FakeSR(_FakeLC(time, flux))
    rows = [{"sector": 25, "cadence_s": 120, "_index": 0}]
    monkeypatch.setattr(pipeline, "search_tess", lambda tic: (fake_sr, rows))
    monkeypatch.setattr(pipeline, "known_toi", lambda tic: (False, None))
    monkeypatch.setattr(pipeline, "get_stellar_density", lambda tic: (None, None))

    rec = pipeline.run_target(1, outdir=str(tmp_path), make_plots=False, sectors=[25])[0]
    assert rec.period_constrained is False
    assert rec.p_best_d is None
    assert rec.p_min_d and rec.p_min_d > 0  # still reported


def test_sectors_filter_excludes_others(monkeypatch, tmp_path):
    time, flux = _lc_with_dip()
    fake_sr = _FakeSR(_FakeLC(time, flux))
    rows = [
        {"sector": 25, "cadence_s": 120, "_index": 0},
        {"sector": 40, "cadence_s": 120, "_index": 0},
    ]
    monkeypatch.setattr(pipeline, "search_tess", lambda tic: (fake_sr, rows))
    monkeypatch.setattr(pipeline, "known_toi", lambda tic: (False, None))
    monkeypatch.setattr(pipeline, "get_stellar_density", lambda tic: (0.3, 0.05))

    records = pipeline.run_target(
        1, outdir=str(tmp_path), make_plots=False, sectors=[25]
    )
    assert {r.sector for r in records} == {25}


def test_recurring_dip_across_two_sectors(monkeypatch, tmp_path):
    # Same star dips in TWO sectors -> periodic/variable, not a clean mono-transit.
    lc0 = _lc_with_dip(seed=3)
    lc1 = _lc_with_dip(t0_offset_d=40.0, seed=4)   # a second sector, also dipping
    fake_sr = _FakeMultiSR({0: lc0, 1: lc1})
    rows = [
        {"sector": 25, "cadence_s": 120, "_index": 0},
        {"sector": 40, "cadence_s": 120, "_index": 1},
    ]
    monkeypatch.setattr(pipeline, "search_tess", lambda tic: (fake_sr, rows))
    monkeypatch.setattr(pipeline, "known_toi", lambda tic: (False, None))
    monkeypatch.setattr(pipeline, "get_stellar_density", lambda tic: (0.3, 0.05))

    records = pipeline.run_target(1, outdir=str(tmp_path), make_plots=False)
    assert {r.sector for r in records} == {25, 40}
    assert all(r.recurring_dip is True for r in records)      # flagged in every record
    assert all(r.n_sectors_observed == 2 for r in records)


def test_quiet_second_sector_not_recurring_and_baseline_not_worse(monkeypatch, tmp_path):
    # Dip in sector 25 only; sector 40 observed but quiet. NOT recurring, and the
    # full multi-sector baseline can only raise (never lower) the p_min bound.
    dip = _lc_with_dip(seed=3)
    quiet = _lc_with_dip(t0_offset_d=40.0, seed=7, with_dip=False)

    monkeypatch.setattr(pipeline, "known_toi", lambda tic: (False, None))
    monkeypatch.setattr(pipeline, "get_stellar_density", lambda tic: (0.3, 0.05))

    # single sector
    monkeypatch.setattr(pipeline, "search_tess",
                        lambda tic: (_FakeMultiSR({0: dip}), [{"sector": 25, "cadence_s": 120, "_index": 0}]))
    single = pipeline.run_target(1, outdir=str(tmp_path), make_plots=False)[0]

    # add a quiet later sector
    rows = [
        {"sector": 25, "cadence_s": 120, "_index": 0},
        {"sector": 40, "cadence_s": 120, "_index": 1},
    ]
    monkeypatch.setattr(pipeline, "search_tess",
                        lambda tic: (_FakeMultiSR({0: dip, 1: quiet}), rows))
    multi = pipeline.run_target(1, outdir=str(tmp_path), make_plots=False)

    assert len(multi) == 1                          # only the dipping sector yields a candidate
    rec = multi[0]
    assert rec.recurring_dip is False               # a quiet 2nd sector is not recurrence
    assert rec.n_sectors_observed == 2
    assert rec.p_min_d >= single.p_min_d            # more coverage never lowers the bound


def test_summaries_dir_writes_a_stellar_summary(monkeypatch, tmp_path):
    import json

    from monohunter.summary import StellarSummary

    time, flux = _lc_with_dip()
    fake_sr = _FakeSR(_FakeLC(time, flux))
    rows = [{"sector": 25, "cadence_s": 120, "_index": 0}]
    monkeypatch.setattr(pipeline, "search_tess", lambda tic: (fake_sr, rows))
    monkeypatch.setattr(pipeline, "known_toi", lambda tic: (False, None))
    monkeypatch.setattr(pipeline, "get_stellar_density", lambda tic: (0.3, 0.05))

    sdir = tmp_path / "summaries"
    pipeline.run_target(42, outdir=str(tmp_path), make_plots=False, summaries_dir=str(sdir))

    spath = sdir / "tic42_s25.json"
    assert spath.exists()                                  # summary written from the same download
    s = StellarSummary(**json.loads(spath.read_text()))
    assert s.tic == 42 and s.sector == 25
    assert s.var_class in {"quiet", "rotator", "variable", "flaring", "dipper"}


def test_cli_run_wires_through(monkeypatch, tmp_path, capsys):
    from monohunter import cli

    time, flux = _lc_with_dip()
    fake_sr = _FakeSR(_FakeLC(time, flux))
    rows = [{"sector": 25, "cadence_s": 120, "_index": 0}]
    monkeypatch.setattr(pipeline, "search_tess", lambda tic: (fake_sr, rows))
    monkeypatch.setattr(pipeline, "known_toi", lambda tic: (False, None))
    monkeypatch.setattr(pipeline, "get_stellar_density", lambda tic: (0.3, 0.05))

    rc = cli.main(
        ["run", "--tic", "298663873", "--outdir", str(tmp_path), "--no-plot"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "S25" in out
    assert (tmp_path / "tic298663873_s25.json").exists()


def test_write_summary_populates_subclass(tmp_path):
    """_write_summary must carry SummaryResult.subclass into the written JSON —
    a rotator light curve must not fall back to the default 'quiet'."""
    import json

    t = np.arange(15000) * (2.0 / (60 * 24))
    rng = np.random.default_rng(0)
    # spot-shaped (non-sinusoidal) rotator: sine + strong 2nd harmonic
    raw = (1.0 + 0.02 * np.sin(2 * np.pi * t / 6.0)
           + 0.012 * np.sin(4 * np.pi * t / 6.0 + 0.7) + rng.normal(0, 5e-4, t.size))
    flat = 1.0 + rng.normal(0, 5e-4, t.size)
    pipeline._write_summary(str(tmp_path), 42, 16, 120, t, raw, flat)
    rec = json.loads((tmp_path / "tic42_s16.json").read_text())
    assert rec["var_class"] == "rotator"
    assert rec["subclass"] in ("rotator", "pulsator")   # computed, not default 'quiet'
