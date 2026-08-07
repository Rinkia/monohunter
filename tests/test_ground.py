"""Ground-survey tests — mag->flux conversion and variability (offline)."""

import numpy as np

from monohunter.ground import _select_asassn_source, mag_to_flux, variability


def test_asassn_source_selection_picks_best_good_band():
    import pandas as pd

    df = pd.DataFrame({
        "asas_sn_id": [1, 1, 1, 2, 1, 1],
        "jd":         [2459.0, 2458.0, 2460.0, 2461.0, 2462.0, 2463.0],
        "mag":        [11.0, 11.1, 10.9, 15.0, 11.2, 11.05],
        "quality":    ["G", "G", "G", "G", "B", "G"],       # one bad epoch
        "phot_filter": ["g", "g", "g", "g", "g", "V"],       # one wrong band
    })
    jd, mag = _select_asassn_source(df, band="g")
    # source 1 (4 good g epochs) beats source 2 (1); bad-quality + V-band dropped
    assert len(jd) == 3
    assert list(jd) == sorted(jd)                # returned time-sorted
    assert 15.0 not in mag                       # the other source excluded


def test_asassn_source_selection_empty_when_no_band_match():
    import pandas as pd

    df = pd.DataFrame({
        "asas_sn_id": [1], "jd": [2459.0], "mag": [11.0],
        "quality": ["G"], "phot_filter": ["V"],
    })
    jd, mag = _select_asassn_source(df, band="g")
    assert jd.size == 0 and mag.size == 0


def test_mag_to_flux_constant_is_unity():
    flux = mag_to_flux(np.full(50, 15.3))
    assert np.allclose(flux, 1.0)


def test_mag_to_flux_dimming_dips_below_one():
    # A 0.75-mag dimming (fainter) is a factor-2 flux drop; brightening rises.
    mag = np.full(11, 15.0)
    mag[5] += 0.7526  # +0.7526 mag ~ half the flux
    flux = mag_to_flux(mag)
    assert np.isclose(np.median(flux), 1.0, atol=1e-6)
    assert np.isclose(flux[5], 0.5, atol=0.02)     # dimming -> flux < 1


def test_variability_flat_star_is_quiet():
    rng = np.random.default_rng(0)
    t = np.sort(rng.uniform(0, 900, 300))          # ~2.5 yr, nightly-ish
    flux = 1.0 + rng.normal(0, 0.008, t.size)      # ~0.8% ground noise
    v = variability(t, flux)
    assert v.is_variable is False
    assert v.frac_amplitude < 0.03
    assert v.baseline_days > 800


def test_variability_variable_star_flags():
    rng = np.random.default_rng(1)
    t = np.sort(rng.uniform(0, 900, 300))
    flux = 1.0 + 0.15 * np.sin(2 * np.pi * t / 12.3) + rng.normal(0, 0.01, t.size)
    v = variability(t, flux)
    assert v.is_variable is True                   # 15% sine -> clearly variable
    assert v.frac_amplitude > 0.05


def test_variability_too_few_epochs():
    v = variability([1.0, 2.0], [1.0, 1.0])
    assert v.is_variable is False and v.n_epochs == 2
