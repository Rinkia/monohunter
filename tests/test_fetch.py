"""T4 tests — sector dedup (prefer 2-min) and streaming, no network."""

from monohunter.fetch import iter_lightcurves, resolve_sectors


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
