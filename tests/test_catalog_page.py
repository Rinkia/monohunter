"""Catalog page tests — CSV rows -> static HTML (pure, offline)."""

from monohunter.catalog_page import render_catalog_html


def _rows():
    return [
        {"tic": "1", "var_class": "rotator", "rotation_period_d": "9.6", "rotation_power": "0.97", "var_amplitude_ppt": "129", "n_flares": "0"},
        {"tic": "2", "var_class": "rotator", "rotation_period_d": "2.7", "rotation_power": "0.60", "var_amplitude_ppt": "25", "n_flares": "0"},
        {"tic": "3", "var_class": "variable", "rotation_period_d": "", "rotation_power": "0.05", "var_amplitude_ppt": "40", "n_flares": "0"},
        {"tic": "4", "var_class": "flaring", "rotation_period_d": "", "rotation_power": "0.04", "var_amplitude_ppt": "8", "n_flares": "12"},
        {"tic": "5", "var_class": "quiet", "rotation_period_d": "", "rotation_power": "0.03", "var_amplitude_ppt": "0.7", "n_flares": "0"},
    ]


def test_catalog_html_has_counts_and_download():
    h = render_catalog_html(_rows(), sector=15, csv_name="sector15.csv")
    assert "Sector 15 variability catalog" in h
    assert "rotator: 2" in h and "quiet: 1" in h        # class breakdown
    assert 'href="sector15.csv"' in h                   # full CSV download link


def test_rotators_sorted_by_power_and_top_stars_present():
    h = render_catalog_html(_rows(), sector=15, csv_name="sector15.csv")
    # strongest rotator (power 0.97) appears before the weaker one
    assert h.index(">1<") < h.index(">2<")
    assert "129" in h                                   # its amplitude rendered
    assert ">12<" in h                                  # flare count of the flare star


def test_blank_rotation_period_is_safe():
    # variable/quiet stars have no rotation period; must not crash the renderer
    h = render_catalog_html([{"tic": "9", "var_class": "quiet", "rotation_period_d": "",
                              "rotation_power": "", "var_amplitude_ppt": "", "n_flares": ""}],
                            sector=15, csv_name="s.csv")
    assert "quiet: 1" in h
