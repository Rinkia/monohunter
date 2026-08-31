"""FFI pool tests — the non-SPOC set difference (pure, offline).

The FFI star pool is the catalog stars in a region MINUS the sector's 2-min SPOC
pool (already covered by the fast path). The network cone/SPOC queries aren't tested
here; the set logic is.
"""

from monohunter.ffi_batch import _non_spoc


def test_removes_spoc_stars_and_sorts():
    cone = [500, 100, 300, 200, 400]
    spoc = {200, 400}
    assert _non_spoc(cone, spoc) == [100, 300, 500]


def test_dedups_and_coerces_ints():
    cone = ["100", 100, 200, 200, 300]
    spoc = {300}
    assert _non_spoc(cone, spoc) == [100, 200]


def test_empty_cone_is_empty():
    assert _non_spoc([], {1, 2, 3}) == []


def test_no_overlap_returns_all():
    assert _non_spoc([1, 2, 3], {9, 8}) == [1, 2, 3]
