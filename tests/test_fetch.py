"""T4 tests — sector dedup (prefer 2-min) and streaming, no network."""

import numpy as np

from monohunter.fetch import (
    DEFAULT_QUALITY_BITMASK,
    cadence_seconds,
    download_lightcurve,
    extract_ffi_lightcurve,
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


class _FakeTruncatedLC:
    """remove_nans() raises like astropy on a truncated FITS ('buffer too small')."""

    def remove_nans(self):
        raise TypeError("buffer is too small for requested array")


class _FakeTruncatedEntry:
    def download(self, quality_bitmask=None):
        return _FakeTruncatedLC()


def test_download_returns_none_on_truncated_fits():
    # A partial MAST download must be a graceful skip, not an uncaught TypeError.
    assert download_lightcurve(_FakeSR(_FakeTruncatedEntry()), 0) is None


def test_iter_skips_none_downloads():
    rows = [{"sector": 25, "cadence_s": 120}, {"sector": 26, "cadence_s": 120}]

    def download(row):
        return None if row["sector"] == 25 else f"lc-{row['sector']}"

    out = list(iter_lightcurves(rows, download))
    assert [r[0]["sector"] for r in out] == [26]   # truncated S25 skipped
    assert out[0][1] == "lc-26"


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


def test_cadence_seconds_measures_median_spacing():
    # 200s FFI cadence expressed in days, with one gap that the median ignores.
    day = 200.0 / 86400.0
    t = np.array([0.0, day, 2 * day, 2 * day + 5.0, 2 * day + 5.0 + day])
    assert cadence_seconds(t) == 200


class _FakeFFILightCurve:
    """Minimal LightCurve: supports `- array` on flux, remove_nans, normalize."""

    def __init__(self, flux):
        self.flux = np.asarray(flux, dtype=float)

    def __sub__(self, other):
        return _FakeFFILightCurve(self.flux - np.asarray(other, dtype=float))

    def remove_nans(self):
        return _FakeFFILightCurve(self.flux[~np.isnan(self.flux)])

    def normalize(self):
        return _FakeFFILightCurve(self.flux / np.nanmedian(self.flux))


class _FakeTPF:
    """3 cadences, 2x2 pixels: one bright source pixel over a constant sky."""

    def __init__(self, sky):
        self._sky = sky
        # pixel [0,0] is the star (sky + signal), the other three are pure sky.
        self.flux = np.array(
            [
                [[sky + 100.0, sky], [sky, sky]],
                [[sky + 80.0, sky], [sky, sky]],  # a dip in the source
                [[sky + 100.0, sky], [sky, sky]],
            ],
            dtype=float,
        )

    def create_threshold_mask(self, threshold=3.0):
        # only the bright pixel clears any positive threshold
        return np.array([[True, False], [False, False]])

    def to_lightcurve(self, aperture_mask):
        return _FakeFFILightCurve(self.flux[:, aperture_mask].sum(axis=1))


def test_extract_ffi_subtracts_sky_background():
    # With sky subtracted, the two 100-signal cadences equal each other and the
    # 80-signal dip is preserved; normalize puts the baseline at 1.0.
    lc = extract_ffi_lightcurve(_FakeTPF(sky=500.0))
    # aperture sum before subtraction is sky+signal; after, only the signal remains.
    # median signal = 100 -> normalized baseline 1.0, dip cadence = 0.8.
    assert np.isclose(np.nanmedian(lc.flux), 1.0)
    assert np.isclose(lc.flux.min(), 0.8)


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


def test_rho_from_logg_radius_sun_and_guards():
    from monohunter.fetch import rho_from_logg_radius
    # Sun: logg 4.44, R=1 Rsun -> ~1.41 g/cm^3
    rho = rho_from_logg_radius(4.44, 1.0)
    assert abs(rho - 1.41) < 0.1
    # a giant (low logg, big R) is much less dense than the Sun
    assert rho_from_logg_radius(2.5, 10.0) < 0.01
    # non-physical input -> None
    assert rho_from_logg_radius(4.44, 0.0) is None
    assert rho_from_logg_radius(None, 1.0) is None
