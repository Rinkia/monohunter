"""T1 tests — FindRecord is the Swarm contract, so validation must be strict."""

import json

import pytest
from pydantic import ValidationError

from monohunter.record import SCHEMA_VERSION, FindRecord


def _valid_kwargs():
    return dict(
        tic=298663873,
        sector=25,
        cadence_s=120,
        event_time_btjd=1955.3,
        depth_ppt=4.2,
        duration_hr=24.0,
        snr=18.5,
        detrend_method="biweight",
        detrend_window_d=3.0,
        tool_version="0.1.0",
        known_toi_match=True,
        known_toi_id="TOI-2180",
    )


def test_valid_record_builds_and_versions():
    rec = FindRecord(**_valid_kwargs())
    assert rec.schema_version == SCHEMA_VERSION
    assert rec.tic == 298663873


def test_json_round_trip_preserves_fields():
    rec = FindRecord(**_valid_kwargs())
    back = FindRecord(**json.loads(rec.to_json()))
    assert back == rec


def test_unknown_field_is_rejected():
    # A drifted/typo'd field must be a hard error, not silently accepted.
    with pytest.raises(ValidationError):
        FindRecord(**_valid_kwargs(), planet_radius=6.7)


def test_missing_required_field_is_rejected():
    kwargs = _valid_kwargs()
    del kwargs["tic"]
    with pytest.raises(ValidationError):
        FindRecord(**kwargs)


def test_negative_depth_is_rejected():
    kwargs = _valid_kwargs()
    kwargs["depth_ppt"] = -1.0
    with pytest.raises(ValidationError):
        FindRecord(**kwargs)
