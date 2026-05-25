"""Frigate event Pydantic modelleri için testler."""

from __future__ import annotations

import pytest

from bridge.events import FrigateEvent, FrigateObject


def _base_after() -> dict[str, object]:
    return {
        "id": "1700000000.123456-abcde",
        "camera": "pilot_kamera",
        "label": "person",
        "score": 0.85,
        "frame_time": 1700000000.5,
        "current_zones": ["zone_pilot"],
        "entered_zones": ["zone_pilot"],
        "has_snapshot": True,
    }


def test_frigate_event_minimal() -> None:
    """Frigate 'new' event parse edilir."""
    payload = {"type": "new", "before": None, "after": _base_after()}
    event = FrigateEvent.model_validate(payload)
    assert event.type == "new"
    assert event.event_id == "1700000000.123456-abcde"
    assert event.camera == "pilot_kamera"
    assert event.label == "person"
    assert event.score == 0.85
    assert event.current_zones == ["zone_pilot"]
    assert event.is_first_in_zone is True


def test_frigate_event_update_no_entered_zones() -> None:
    """Update'te entered_zones boşsa is_first_in_zone False."""
    after = _base_after() | {"entered_zones": []}
    payload = {"type": "update", "before": _base_after(), "after": after}
    event = FrigateEvent.model_validate(payload)
    assert event.type == "update"
    assert event.is_first_in_zone is False


def test_frigate_event_end() -> None:
    """End event."""
    after = _base_after() | {"current_zones": []}
    payload = {"type": "end", "before": _base_after(), "after": after}
    event = FrigateEvent.model_validate(payload)
    assert event.type == "end"
    assert event.current_zones == []


def test_frigate_event_extra_fields_tolerated() -> None:
    """Frigate yeni sürüm: bilinmeyen alanlar hata vermez."""
    after = _base_after() | {"future_field_added_in_0_18": "lala"}
    payload = {"type": "new", "after": after}
    event = FrigateEvent.model_validate(payload)
    assert event.label == "person"


def test_frigate_event_invalid_score() -> None:
    """Score 0-1 dışındaysa validation hatası."""
    after = _base_after() | {"score": 1.5}
    with pytest.raises(ValueError):
        FrigateObject.model_validate(after)


def test_frigate_event_invalid_type() -> None:
    """Type 'new'|'update'|'end' dışındaysa hata."""
    with pytest.raises(ValueError):
        FrigateEvent.model_validate({"type": "snapshot", "after": _base_after()})
