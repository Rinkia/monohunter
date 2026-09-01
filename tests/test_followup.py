"""Follow-up tracker tests — pure state model + JSON store, offline."""

import pytest

from monohunter.followup import (
    apply_update,
    is_valid_transition,
    load_all,
    load_followup,
    new_followup,
    save_followup,
)


def test_valid_and_invalid_transitions():
    assert is_valid_transition("pending", "observing")
    assert is_valid_transition("observing", "confirmed")
    assert is_valid_transition("confirmed", "rejected")     # a call can be overturned
    assert is_valid_transition("pending", "pending")        # no-op allowed
    assert not is_valid_transition("pending", "banana")     # unknown status
    assert not is_valid_transition("confirmed", "pending")  # terminal can't go back to pending


def test_new_followup_defaults_and_note():
    r = new_followup(298009554, 15, note="clean 1.4% transit, needs RV")
    assert r.status == "pending"
    assert r.kind == "planet_candidate"
    assert len(r.notes) == 1 and "needs RV" in r.notes[0]


def test_apply_update_transitions_and_logs():
    r = new_followup(400048097, 17)
    r2 = apply_update(r, status="observing", observer="Rinkia", note="scheduled 2026-08-29")
    assert r2.status == "observing"
    assert r2.observer == "Rinkia"
    assert len(r2.notes) == len(r.notes) + 1
    assert r2.updated_utc >= r.updated_utc
    # original untouched (immutable update)
    assert r.status == "pending" and r.observer is None


def test_apply_update_rejects_illegal_transition():
    r = new_followup(1, 1, status="confirmed")
    with pytest.raises(ValueError):
        apply_update(r, status="pending")


def test_store_roundtrip_and_load_all(tmp_path):
    a = new_followup(111, 1, note="a")
    b = apply_update(new_followup(222, 2), status="confirmed", note="second transit caught")
    save_followup(tmp_path, a)
    save_followup(tmp_path, b)

    got = load_followup(tmp_path, 111, 1)
    assert got is not None and got.tic == 111

    allrecs = load_all(tmp_path)
    assert {r.tic for r in allrecs} == {111, 222}
    # sorted newest-updated first (both within the same second here, so just check it's ordered)
    assert [r.updated_utc for r in allrecs] == sorted((r.updated_utc for r in allrecs), reverse=True)


def test_load_all_skips_bad_files(tmp_path):
    save_followup(tmp_path, new_followup(1, 1))
    (tmp_path / "tic999_s9.json").write_text("{ not valid json", encoding="utf-8")
    recs = load_all(tmp_path)
    assert [r.tic for r in recs] == [1]
