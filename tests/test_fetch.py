"""T4 tests — sector dedup (prefer 2-min) and streaming, no network."""

from monohunter.fetch import (
    DEFAULT_QUALITY_BITMASK,
    download_lightcurve,
    iter_lightcurves,
    resolve_sectors,
)


class _FakeLC:
    def remove_nans(self):
        return self

    def normalize(self):
        return self


class _FakeEntry:
    """download() accepts quality_bitmask and records it."""

    def __init__(self, sink):
        self._sink = sink

    def download(self, quality_bitmask=None):
        self._sink["bitmask"] = quality_bitmask
        return _FakeLC()


class _FakeEntryNoBitmask:
    """download() has no quality_bitmask param — passing it raises TypeError."""

    def download(self):
        return _FakeLC()


class _FakeSR:
    def __init__(self, entry):
        self._entry = entry

    def __getitem__(self, index):
        return self._entry


def test_download_applies_hard_quality_bitmask():
    sink = {}
    download_lightcurve(_FakeSR(_FakeEntry(sink)), 0)
    assert sink["bitmask"] == DEFAULT_QUALITY_BITMASK == "hard"


def test_download_falls_back_when_bitmask_unsupported():
    # A product whose download() rejects the kwarg must still work, not crash.
    result = download_lightcurve(_FakeSR(_FakeEntryNoBitmask()), 0)
    assert result is not None


def test_prefers_2min_and_dedups_by_sector():
    rows = [
        {"sector": 25, "cadence_s": 20},
        {"sector": 25, "cadence_s": 120},   # 2-min duplicate of S25 — should win
        {"sector": 26, "cadence_s": 20},    # only 20-sec available for S26
    ]
    resolved = resolve_sectors(rows)
    assert [(r["sector"], r["cadence_s"]) for r in resolved] == [(25, 120), (26, 20)]


def test_sorted_by_sector():
    rows = [{"sector": 40, "cadence_s": 120}, {"sector": 14, "cadence_s": 120}]
    assert [r["sector"] for r in resolve_sectors(rows)] == [14, 40]


def test_iter_streams_deduped_rows_one_at_a_time():
    rows = [
        {"sector": 25, "cadence_s": 20},
        {"sector": 25, "cadence_s": 120},
        {"sector": 26, "cadence_s": 120},
    ]
    downloaded = []

    def fake_download(row):
        downloaded.append((row["sector"], row["cadence_s"]))
        return f"lc-{row['sector']}"

    out = list(iter_lightcurves(rows, fake_download))

    # Only the deduped set was downloaded (no 20-sec S25 duplicate).
    assert downloaded == [(25, 120), (26, 120)]
    assert out[0][1] == "lc-25"
    assert out[1][1] == "lc-26"
