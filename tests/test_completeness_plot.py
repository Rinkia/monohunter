"""Completeness heatmap render test — synthetic grid, offline (no MAST)."""

from monohunter.completeness import (
    DEFAULT_DEPTHS_PPT,
    DEFAULT_DURATIONS_HR,
    plot_completeness_grid,
)


def _synthetic_grid():
    # deeper + longer -> higher recovery; a plausible sensitivity surface
    grid = {}
    for i, d in enumerate(DEFAULT_DEPTHS_PPT):
        for j, dur in enumerate(DEFAULT_DURATIONS_HR):
            grid[(d, dur)] = min(1.0, 0.1 * (i + 1) + 0.15 * j)
    return grid


def test_plot_writes_a_nonempty_png(tmp_path):
    out = tmp_path / "completeness.png"
    ret = plot_completeness_grid(_synthetic_grid(), str(out), title="test")
    assert ret == str(out)
    assert out.exists()
    assert out.stat().st_size > 1000        # a real figure, not an empty file
