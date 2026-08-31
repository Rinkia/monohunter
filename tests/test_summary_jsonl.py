"""JSONL summaries — append one line per star, load a dir OR a .jsonl file back.

Kills the thousands-of-tiny-files I/O cost on a big sweep: _write_summary appends
to a single .jsonl when the target ends in .jsonl, and load_summaries reads it.
"""

import numpy as np

from monohunter.pipeline import _write_summary
from monohunter.summary import load_summaries


def _lc(n=15000):
    t = np.arange(n) * (2.0 / (60 * 24))       # ~21 d at 2-min cadence
    flux = np.ones(n)                          # quiet, flat -> a valid summary
    return t, flux, flux


def test_jsonl_append_roundtrips_many_stars(tmp_path):
    t, raw, flat = _lc()
    jsonl = tmp_path / "sweep.jsonl"
    for tic in (111, 222, 333):
        _write_summary(str(jsonl), tic, 16, 120, t, raw, flat)

    # one file, not three
    assert jsonl.exists()
    assert sum(1 for _ in jsonl.open()) == 3

    # load by direct .jsonl path
    rows = load_summaries(str(jsonl))
    assert sorted(r["tic"] for r in rows) == [111, 222, 333]

    # load by containing dir (globs *.jsonl too)
    rows_dir = load_summaries(str(tmp_path))
    assert sorted(r["tic"] for r in rows_dir) == [111, 222, 333]


def test_dir_of_json_still_works_and_mixes_with_jsonl(tmp_path):
    t, raw, flat = _lc()
    _write_summary(str(tmp_path), 111, 16, 120, t, raw, flat)          # per-file JSON
    _write_summary(str(tmp_path / "extra.jsonl"), 222, 16, 120, t, raw, flat)

    rows = load_summaries(str(tmp_path))
    assert sorted(r["tic"] for r in rows) == [111, 222]
