"""Vetting page tests — static HTML generation (pure, offline)."""

from monohunter.vetting import LABELS, build_vetting_html


def _cand(tic=123, sector=14, **kw):
    base = dict(
        tic=tic, sector=sector, png=f"tic{tic}_s{sector}.png",
        depth_ppt=4.2, duration_hr=24.0, snr=39.5, period_d=856, likely_eb=False,
        known_toi_id=None,
    )
    base.update(kw)
    return base


def test_html_has_a_card_per_candidate():
    html = build_vetting_html([_cand(1), _cand(2), _cand(3)])
    assert html.count('class="card"') == 3
    assert "TIC 1" in html and "TIC 2" in html and "TIC 3" in html


def test_card_has_every_label_button_and_the_png():
    html = build_vetting_html([_cand(tic=99, sector=7)])
    for value, _text in LABELS:
        assert f'data-label="{value}"' in html          # every label offered
    assert "tic99_s7.png" in html                       # the diagnostic image is shown


def test_badges_reflect_known_and_eb():
    novel = build_vetting_html([_cand(likely_eb=False, known_toi_id=None)])
    assert ">NEW<" in novel
    eb = build_vetting_html([_cand(likely_eb=True, known_toi_id="TOI-999.01")])
    assert "TOI-999.01" in eb and ">EB?<" in eb


def test_has_localstorage_vote_and_export_hooks():
    html = build_vetting_html([_cand()])
    # the label factory: votes persist locally and export to a submittable JSON
    assert "localStorage" in html
    assert "function vote(" in html
    assert "function exportLabels(" in html
    assert "labels_" in html          # export filename prefix


def test_empty_queue_is_safe():
    html = build_vetting_html([])
    assert "No candidates to vet." in html
