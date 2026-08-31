"""summarize --from-catalog: dedup work-list + parallel resummarize with resume.

run_summary is monkeypatched so these stay offline; the batch orchestration (dedup,
resume-skip, dir vs .jsonl write, per-star failure counting) is what's under test.
"""

import csv
import types

import monohunter.summary as S
from monohunter import cli
from monohunter.summary import StellarSummary, load_summaries, tics_from_catalog


def _catalog(tmp_path, rows):
    p = tmp_path / "cat.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tic", "sector", "var_class"])
        for t, s in rows:
            w.writerow([t, s, "quiet"])
    return p


def _fake_run_summary(tic, sectors=None):
    sec = (sectors or [16])[0]
    return [StellarSummary(tic=tic, sector=sec, cadence_s=120, n_epochs=1000,
                           var_amplitude_ppt=1.0, subclass="rotator")]


def test_tics_from_catalog_dedups_and_orders(tmp_path):
    p = _catalog(tmp_path, [(1, 16), (2, 16), (1, 16), (3, 17)])
    assert tics_from_catalog(str(p)) == [(1, 16), (2, 16), (3, 17)]


def test_from_catalog_writes_then_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "run_summary", _fake_run_summary)
    cat = _catalog(tmp_path, [(1, 16), (2, 16)])
    out = tmp_path / "sums"
    args = types.SimpleNamespace(from_catalog=str(cat), outdir=str(out), workers=1)

    assert cli._summarize_from_catalog(args) == 0
    assert sorted(r["tic"] for r in load_summaries(str(out))) == [1, 2]

    # every star already present -> a second run skips them all, writes nothing new
    monkeypatch.setattr(S, "run_summary", lambda *a, **k: (_ for _ in ()).throw(AssertionError("refetched")))
    assert cli._summarize_from_catalog(args) == 0
    assert sorted(r["tic"] for r in load_summaries(str(out))) == [1, 2]


def test_from_catalog_jsonl_single_file(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "run_summary", _fake_run_summary)
    cat = _catalog(tmp_path, [(10, 18), (11, 18), (12, 18)])
    out = tmp_path / "s18.jsonl"
    args = types.SimpleNamespace(from_catalog=str(cat), outdir=str(out), workers=2)

    assert cli._summarize_from_catalog(args) == 0
    assert out.exists()
    assert sum(1 for _ in out.open()) == 3
    assert sorted(r["tic"] for r in load_summaries(str(out))) == [10, 11, 12]
