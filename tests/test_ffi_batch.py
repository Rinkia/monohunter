"""FFI batch tests — per-position aperture photometry on a shared cutout (offline)."""

import numpy as np

from monohunter.ffi_batch import (
    BatchDetection,
    StarPixel,
    dedup_blends,
    extract_at_position,
    extract_batch,
)


def _det(tic, t, snr, depth):
    return BatchDetection(tic=tic, sector=14, event_time_btjd=t, depth_ppt=depth, duration_hr=4.0, snr=snr)


def test_dedup_collapses_crowding_blends():
    # Three stars "detect" the same eclipse at ~the same time (crowding); the
    # deepest/highest-SNR (best-centered) survives, the other two are blends.
    dets = [_det(1, 1686.64, 999.0, 191.0), _det(2, 1686.64, 170.0, 136.0), _det(3, 1686.66, 146.0, 123.0)]
    primaries, blended = dedup_blends(dets)
    assert len(primaries) == 1
    assert primaries[0].tic == 1        # highest SNR wins
    assert blended == 2


def test_dedup_keeps_distinct_time_events():
    dets = [_det(1, 1686.6, 100.0, 10.0), _det(2, 1702.5, 80.0, 8.0)]  # >0.1d apart
    primaries, blended = dedup_blends(dets)
    assert len(primaries) == 2 and blended == 0


def _two_star_cube(nt=200, ny=12, nx=12, sky=50.0):
    rng = np.random.default_rng(0)
    cube = np.full((nt, ny, nx), sky) + rng.normal(0, 0.5, (nt, ny, nx))
    # star A at (col=3, row=3), brightness 100, with a 10% dip mid-series
    sig_a = np.full(nt, 100.0)
    sig_a[80:120] -= 10.0
    cube[:, 3, 3] += sig_a
    # star B at (col=8, row=8), flat brightness 100
    cube[:, 8, 8] += 100.0
    return cube


def test_extract_recovers_source_and_subtracts_sky():
    cube = _two_star_cube()
    lc_a = extract_at_position(cube, col=3, row=3, radius=1)
    # sky (~9*50) subtracted -> baseline ~ the source's 100, dip visible.
    assert np.isclose(np.median(lc_a), 100.0, rtol=0.1)
    assert lc_a[100] < np.median(lc_a) * 0.95        # the dip is there


def test_extract_does_not_leak_neighbor_signal():
    cube = _two_star_cube()
    lc_b = extract_at_position(cube, col=8, row=8, radius=1)
    # star B is flat: A's dip (at a different pixel) must NOT appear here.
    assert np.isclose(np.median(lc_b), 100.0, rtol=0.1)
    assert lc_b[100] > np.median(lc_b) * 0.98


class _FakeTPF:
    def __init__(self, cube):
        self.flux = cube
        self.time = np.arange(cube.shape[0], dtype=float)


def test_extract_batch_normalizes_and_skips_edge_stars():
    cube = _two_star_cube()
    tpf = _FakeTPF(cube)
    stars = [
        StarPixel(1, col=3, row=3),     # in-bounds
        StarPixel(2, col=8, row=8),     # in-bounds
        StarPixel(3, col=0, row=0),     # on the edge -> aperture doesn't fit -> skipped
    ]
    out = {tic: (t, f) for tic, t, f in extract_batch(tpf, stars, radius=1)}
    assert set(out) == {1, 2}                       # edge star skipped
    _, flux_a = out[1]
    assert np.isclose(np.median(flux_a), 1.0, atol=1e-6)   # normalized to 1
    assert flux_a[100] < 0.95                              # dip survives normalization
