"""Rotation-plot tests — pure stats filtering + figure renders to a file."""

import os

from monohunter.rotation_plot import plot_rotation_distribution, rotation_stats


def _rows():
    return [
        {"rotation_period_d": "4.3", "var_amplitude_ppt": "8.0", "rotation_systematic": "False"},
        {"rotation_period_d": "12.0", "var_amplitude_ppt": "2.5", "rotation_systematic": "False"},
        {"rotation_period_d": "", "var_amplitude_ppt": "1.0", "rotation_systematic": "False"},  # no period
        {"rotation_period_d": "13.7", "var_amplitude_ppt": "3.0", "rotation_systematic": "True"},  # systematic
        {"rotation_period_d": "None", "var_amplitude_ppt": "0.5", "rotation_systematic": "False"},
    ]


def test_rotation_stats_filters_to_real_rotators():
    periods, amps = rotation_stats(_rows())
    assert periods.size == 2                     # only the two clean rotators
    assert sorted(periods.tolist()) == [4.3, 12.0]
    assert amps.size == 2


def test_plot_writes_png(tmp_path):
    out = tmp_path / "rotation.png"
    n = plot_rotation_distribution(_rows(), str(out), sector=15)
    assert n == 2
    assert os.path.exists(out) and out.stat().st_size > 0


def test_plot_handles_empty_catalog(tmp_path):
    out = tmp_path / "empty.png"
    n = plot_rotation_distribution([], str(out))
    assert n == 0
    assert os.path.exists(out)
