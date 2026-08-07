"""Ground-survey tests — mag->flux conversion and variability (offline)."""

import numpy as np

from monohunter.ground import mag_to_flux, variability


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
