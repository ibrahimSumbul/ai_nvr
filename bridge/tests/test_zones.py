"""ZoneStateMachine için testler — state transitions + dedup + exit timeout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from bridge.events import FrigateEvent
from bridge.zone_config import ZoneConfig, ZoneRules
from bridge.zones import ZoneStateMachine

# --- Test fixtures (mock'lar) ---


class FakeDB:
    """Bridge.db.Database davranışını taklit eden minimal mock."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.last_event: dict[str, Any] | None = None

    async def insert_zone_event(self, **kwargs: Any) -> int:  # noqa: D401
        self.events.append(kwargs)
        return len(self.events)

    async def get_zone_last_event(self, zone: str) -> dict[str, Any] | None:
        return self.last_event


class FakeSnapshots:
    """SnapshotStore mock'u."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    async def fetch_event_snapshot(self, event_id: str) -> None:
        self.fetched.append(event_id)
        return None  # mock — path döndürmüyor


def _zone_cfg(**overrides: Any) -> ZoneConfig:
    """ZoneRules default'larını kullan, sadece override gelenleri ayarla."""
    rules = ZoneRules(**overrides)
    return ZoneConfig(
        name="pilot_zone",
        camera="pilot_kamera",
        frigate_zone="zone_pilot",
        rules=rules,
    )


def _event(
    type_: str = "new",
    score: float = 0.85,
    current_zones: list[str] | None = None,
    entered_zones: list[str] | None = None,
    event_id: str = "evt-1",
    label: str = "person",
) -> FrigateEvent:
    after = {
        "id": event_id,
        "camera": "pilot_kamera",
        "label": label,
        "score": score,
        "frame_time": 0.0,
        "current_zones": current_zones if current_zones is not None else ["zone_pilot"],
        "entered_zones": entered_zones if entered_zones is not None else [],
        "has_snapshot": True,
    }
    return FrigateEvent.model_validate({"type": type_, "after": after})


# --- Tests ---


async def test_empty_to_occupied_on_first_entry() -> None:
    """Boş alana ilk giriş → OCCUPIED + first_entry insert + snapshot fetch."""
    cfg = _zone_cfg()
    db = FakeDB()
    snaps = FakeSnapshots()
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    zsm = ZoneStateMachine(cfg, db, snaps, clock=lambda: now)  # type: ignore[arg-type]

    await zsm.on_event(_event(event_id="evt-1"))

    assert zsm.state == "OCCUPIED"
    assert len(db.events) == 1
    assert db.events[0]["event_type"] == "first_entry"
    assert db.events[0]["frigate_event_id"] == "evt-1"
    assert snaps.fetched == ["evt-1"]


async def test_occupied_heartbeat_does_not_insert() -> None:
    """OCCUPIED iken aynı veya farklı obje ID → DB'ye yeni event yazılmaz."""
    cfg = _zone_cfg()
    db = FakeDB()
    snaps = FakeSnapshots()
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    zsm = ZoneStateMachine(cfg, db, snaps, clock=lambda: now)  # type: ignore[arg-type]

    await zsm.on_event(_event(event_id="evt-1"))
    await zsm.on_event(_event(event_id="evt-1", type_="update"))  # heartbeat
    await zsm.on_event(_event(event_id="evt-2"))  # ikinci kişi

    assert zsm.state == "OCCUPIED"
    assert len(db.events) == 1  # sadece ilk first_entry


async def test_low_score_filtered() -> None:
    """min_person_score altındaki event yok sayılır."""
    cfg = _zone_cfg(min_person_score=0.7)
    db = FakeDB()
    snaps = FakeSnapshots()
    zsm = ZoneStateMachine(cfg, db, snaps)

    await zsm.on_event(_event(score=0.5))

    assert zsm.state == "EMPTY"
    assert len(db.events) == 0


async def test_wrong_label_filtered() -> None:
    """track_objects dışındaki label'lar yok sayılır."""
    cfg = _zone_cfg()
    db = FakeDB()
    snaps = FakeSnapshots()
    zsm = ZoneStateMachine(cfg, db, snaps)

    await zsm.on_event(_event(label="car"))

    assert zsm.state == "EMPTY"
    assert len(db.events) == 0


async def test_exit_after_timeout() -> None:
    """OCCUPIED + last_seen 60s'den fazla geçince exit + EMPTY."""
    cfg = _zone_cfg(exit_timeout_seconds=60)
    db = FakeDB()
    snaps = FakeSnapshots()
    times = iter([
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),  # first_entry
        datetime(2026, 1, 1, 12, 1, 30, tzinfo=UTC),  # tick 90s sonra
    ])
    zsm = ZoneStateMachine(cfg, db, snaps, clock=lambda: next(times))  # type: ignore[arg-type]

    await zsm.on_event(_event(event_id="evt-1"))
    assert zsm.state == "OCCUPIED"

    await zsm.tick()
    assert zsm.state == "EMPTY"
    assert len(db.events) == 2
    assert db.events[1]["event_type"] == "exit"


async def test_no_exit_before_timeout() -> None:
    """OCCUPIED ama exit_timeout dolmadıysa, tick exit yapmaz."""
    cfg = _zone_cfg(exit_timeout_seconds=60)
    db = FakeDB()
    snaps = FakeSnapshots()
    times = iter([
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC),  # 30s sonra
    ])
    zsm = ZoneStateMachine(cfg, db, snaps, clock=lambda: next(times))  # type: ignore[arg-type]

    await zsm.on_event(_event(event_id="evt-1"))
    await zsm.tick()
    assert zsm.state == "OCCUPIED"
    assert len(db.events) == 1


async def test_object_outside_zone_ignored() -> None:
    """current_zones'da hedef zone yoksa state değişmez."""
    cfg = _zone_cfg()
    db = FakeDB()
    snaps = FakeSnapshots()
    zsm = ZoneStateMachine(cfg, db, snaps)

    await zsm.on_event(_event(current_zones=["other_zone"]))

    assert zsm.state == "EMPTY"
    assert len(db.events) == 0


async def test_restore_from_db_occupied() -> None:
    """Son event first_entry ve < 60s ise OCCUPIED restore."""
    cfg = _zone_cfg(exit_timeout_seconds=60)
    db = FakeDB()
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    db.last_event = {
        "event_type": "first_entry",
        "ts": now - timedelta(seconds=20),
        "frigate_event_id": "evt-old",
    }
    snaps = FakeSnapshots()
    zsm = ZoneStateMachine(cfg, db, snaps, clock=lambda: now)  # type: ignore[arg-type]

    await zsm.restore_from_db()

    assert zsm.state == "OCCUPIED"


async def test_restore_from_db_empty_when_stale() -> None:
    """Son first_entry >60s eskiyse EMPTY kalır."""
    cfg = _zone_cfg(exit_timeout_seconds=60)
    db = FakeDB()
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    db.last_event = {
        "event_type": "first_entry",
        "ts": now - timedelta(seconds=300),
        "frigate_event_id": "evt-old",
    }
    snaps = FakeSnapshots()
    zsm = ZoneStateMachine(cfg, db, snaps, clock=lambda: now)  # type: ignore[arg-type]

    await zsm.restore_from_db()

    assert zsm.state == "EMPTY"


def test_active_hours_normal_range() -> None:
    """active_hours parsing — normal aralık."""
    from bridge.zones import _is_within_active_hours

    now = datetime(2026, 1, 1, 10, 30, tzinfo=UTC)
    assert _is_within_active_hours(now, "08:00-18:00") is True
    assert _is_within_active_hours(now, "12:00-18:00") is False


def test_active_hours_overnight() -> None:
    """active_hours parsing — çapraz gece (18:00-08:00)."""
    from bridge.zones import _is_within_active_hours

    morning = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    evening = datetime(2026, 1, 1, 20, 0, tzinfo=UTC)
    daytime = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    assert _is_within_active_hours(morning, "18:00-08:00") is True
    assert _is_within_active_hours(evening, "18:00-08:00") is True
    assert _is_within_active_hours(daytime, "18:00-08:00") is False


def test_active_hours_always_on() -> None:
    """'00:00-23:59' default = her saat True."""
    from bridge.zones import _is_within_active_hours

    now = datetime(2026, 1, 1, 3, 14, tzinfo=UTC)
    assert _is_within_active_hours(now, "00:00-23:59") is True
