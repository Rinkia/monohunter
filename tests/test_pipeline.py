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


def _lc_with_dip():
    dt = 2.0 / (60 * 24)  # 2-min cadence in days
    time = np.arange(2000) * dt
    rng = np.random.default_rng(3)
    flux = 1.0 + rng.normal(0, 5e-4, size=time.size)
    c = time.size // 2
    flux[c - 360 : c + 360] -= 6e-3  # ~24h, 6 ppt dip
    return time, flux


def test_run_target_builds_valid_record(monkeypatch, tmp_path):
    time, flux = _lc_with_dip()
    fake_sr = _FakeSR(_FakeLC(time, flux))
    rows = [{"sector": 25, "cadence_s": 120, "_index": 0}]

    monkeypatch.setattr(pipeline, "search_tess", lambda tic: (fake_sr, rows))
    monkeypatch.setattr(pipeline, "known_toi", lambda tic: (True, "TOI-2180"))

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
    # plot actually written
    import os

    assert os.path.exists(rec.plot_path)


def test_sectors_filter_excludes_others(monkeypatch, tmp_path):
    time, flux = _lc_with_dip()
    fake_sr = _FakeSR(_FakeLC(time, flux))
    rows = [
        {"sector": 25, "cadence_s": 120, "_index": 0},
        {"sector": 40, "cadence_s": 120, "_index": 0},
    ]
    monkeypatch.setattr(pipeline, "search_tess", lambda tic: (fake_sr, rows))
    monkeypatch.setattr(pipeline, "known_toi", lambda tic: (False, None))

    records = pipeline.run_target(
        1, outdir=str(tmp_path), make_plots=False, sectors=[25]
    )
    assert {r.sector for r in records} == {25}


def test_cli_run_wires_through(monkeypatch, tmp_path, capsys):
    from monohunter import cli

    time, flux = _lc_with_dip()
    fake_sr = _FakeSR(_FakeLC(time, flux))
    rows = [{"sector": 25, "cadence_s": 120, "_index": 0}]
    monkeypatch.setattr(pipeline, "search_tess", lambda tic: (fake_sr, rows))
    monkeypatch.setattr(pipeline, "known_toi", lambda tic: (False, None))

    rc = cli.main(
        ["run", "--tic", "298663873", "--outdir", str(tmp_path), "--no-plot"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "S25" in out
    assert (tmp_path / "tic298663873_s25.json").exists()
