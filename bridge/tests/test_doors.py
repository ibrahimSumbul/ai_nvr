"""DoorStateMachine testleri — alternating in/out, cooldown, dedup, Dahua alarm."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from bridge.dahua import DahuaAlarmError
from bridge.doors import DoorStateMachine
from bridge.events import FrigateEvent
from bridge.zone_config import ZoneConfig, ZoneRules


class FakeDB:
    def __init__(self) -> None:
        self.door_events: list[dict[str, Any]] = []
        self.closed: list[dict[str, Any]] = []

    async def insert_door_event(self, **kwargs: Any) -> int:
        self.door_events.append(kwargs)
        return len(self.door_events)

    async def close_door_event(self, door_event_id: int, **kwargs: Any) -> None:
        self.closed.append({"id": door_event_id, **kwargs})


class FakeSnapshots:
    async def fetch_event_snapshot(self, event_id: str) -> None:
        return None


class FakeDahua:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raises = raises

    async def trigger_external_alarm(
        self, channel: int, event_type: str, description: str, snapshot_path: str | None = None
    ) -> None:
        self.calls.append({"channel": channel, "event_type": event_type})
        if self._raises is not None:
            raise self._raises

    async def health_check(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class Clock:
    """Test edilebilir saat — advance ile zaman ilerletir."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _door_cfg(**overrides: Any) -> ZoneConfig:
    overrides.setdefault("cooldown_seconds", 3)
    overrides.setdefault("track_objects", ["person"])
    rules = ZoneRules(type="door", **overrides)
    return ZoneConfig(
        name="cam_kapi_zone", camera="cam_kapi", frigate_zone="cam_kapi_zone", rules=rules
    )


def _event(
    event_id: str = "evt-1",
    score: float = 0.85,
    in_zone: bool = True,
    type_: str = "new",
    label: str = "person",
) -> FrigateEvent:
    after = {
        "id": event_id,
        "camera": "cam_kapi",
        "label": label,
        "score": score,
        "frame_time": 0.0,
        "current_zones": ["cam_kapi_zone"] if in_zone else [],
        "entered_zones": [],
        "has_snapshot": False,
    }
    return FrigateEvent.model_validate({"type": type_, "after": after})


# ---- Tests ----


async def test_first_traversal_is_entry() -> None:
    """İlk geçiş → giriş (direction=in), oturum açılır, Dahua alarm."""
    db, snaps, dahua = FakeDB(), FakeSnapshots(), FakeDahua()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dsm = DoorStateMachine(_door_cfg(dahua_channel=5), db, snaps, clock=clock, dahua=dahua)  # type: ignore[arg-type]

    await dsm.on_event(_event(event_id="p1"))

    assert len(db.door_events) == 1
    assert db.door_events[0]["direction"] == "in"
    assert db.closed == []
    assert dahua.calls == [{"channel": 5, "event_type": "door_entry"}]


async def test_second_traversal_is_exit_with_duration() -> None:
    """2. geçiş → çıkış: oturum kapanır, duration_ms hesaplanır."""
    db, snaps, dahua = FakeDB(), FakeSnapshots(), FakeDahua()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dsm = DoorStateMachine(_door_cfg(), db, snaps, clock=clock, dahua=dahua)  # type: ignore[arg-type]

    await dsm.on_event(_event(event_id="p1"))  # giriş
    clock.advance(12)  # 12 sn kapıda
    await dsm.on_event(_event(event_id="p2"))  # çıkış

    assert len(db.door_events) == 1  # tek oturum (in)
    assert len(db.closed) == 1
    assert db.closed[0]["id"] == 1
    assert db.closed[0]["duration_ms"] == 12000
    assert [c["event_type"] for c in dahua.calls] == ["door_entry", "door_exit"]


async def test_alternating_in_out_in() -> None:
    """3 geçiş → in, out, in (yeni oturum)."""
    db, snaps = FakeDB(), FakeSnapshots()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dsm = DoorStateMachine(_door_cfg(), db, snaps, clock=clock)  # type: ignore[arg-type]

    for i, eid in enumerate(["p1", "p2", "p3"]):
        clock.advance(10 * i)
        await dsm.on_event(_event(event_id=eid))

    assert len(db.door_events) == 2  # iki "in" (1. ve 3.)
    assert len(db.closed) == 1  # bir "out" (2.)


async def test_heartbeat_same_id_dedup() -> None:
    """Aynı tracking_id tekrar → tek geçiş (heartbeat yutulur)."""
    db, snaps = FakeDB(), FakeSnapshots()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dsm = DoorStateMachine(_door_cfg(), db, snaps, clock=clock)  # type: ignore[arg-type]

    await dsm.on_event(_event(event_id="p1"))
    await dsm.on_event(_event(event_id="p1"))  # aynı ID, heartbeat
    await dsm.on_event(_event(event_id="p1"))

    assert len(db.door_events) == 1  # tek giriş


async def test_cooldown_skips_rapid_traversal() -> None:
    """Cooldown içindeki ikinci (farklı) geçiş yutulur."""
    db, snaps = FakeDB(), FakeSnapshots()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dsm = DoorStateMachine(_door_cfg(cooldown_seconds=3), db, snaps, clock=clock)  # type: ignore[arg-type]

    await dsm.on_event(_event(event_id="p1"))  # giriş
    clock.advance(1)  # cooldown(3) içinde
    await dsm.on_event(_event(event_id="p2"))  # yutulmalı

    assert len(db.door_events) == 1
    assert len(db.closed) == 0  # ikinci geçiş çıkış sayılmadı


async def test_not_in_zone_no_traversal() -> None:
    """Kişi kapı zone'unda değilse geçiş üretilmez."""
    db, snaps = FakeDB(), FakeSnapshots()
    dsm = DoorStateMachine(_door_cfg(), db, snaps)  # type: ignore[arg-type]

    await dsm.on_event(_event(event_id="p1", in_zone=False))

    assert db.door_events == []


async def test_low_score_ignored() -> None:
    """score < min_person_score → geçiş yok."""
    db, snaps = FakeDB(), FakeSnapshots()
    dsm = DoorStateMachine(_door_cfg(min_person_score=0.6), db, snaps)  # type: ignore[arg-type]

    await dsm.on_event(_event(event_id="p1", score=0.3))

    assert db.door_events == []


async def test_dahua_none_still_logs_event() -> None:
    """dahua=None → alarm yok ama door_event yine yazılır."""
    db, snaps = FakeDB(), FakeSnapshots()
    dsm = DoorStateMachine(_door_cfg(), db, snaps, dahua=None)  # type: ignore[arg-type]

    await dsm.on_event(_event(event_id="p1"))

    assert len(db.door_events) == 1  # event yazıldı


async def test_end_event_clears_dedup_set() -> None:
    """end event → tracking_id _processed_ids'ten çıkar (bellek sızıntısı önlemi)."""
    db, snaps = FakeDB(), FakeSnapshots()
    dsm = DoorStateMachine(_door_cfg(), db, snaps)  # type: ignore[arg-type]

    await dsm.on_event(_event(event_id="p1"))
    assert "p1" in dsm._processed_ids
    # end event nesne hâlâ zone içindeyken gelse bile temizlenmeli
    await dsm.on_event(_event(event_id="p1", type_="end"))
    assert "p1" not in dsm._processed_ids


async def test_end_then_reentry_counts_as_new_traversal() -> None:
    """end sonrası aynı kişi tekrar girerse yeni geçiş (alternating → çıkış)."""
    db, snaps = FakeDB(), FakeSnapshots()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dsm = DoorStateMachine(_door_cfg(cooldown_seconds=0), db, snaps, clock=clock)  # type: ignore[arg-type]

    await dsm.on_event(_event(event_id="p1"))  # giriş (in)
    await dsm.on_event(_event(event_id="p1", type_="end"))  # tracking bitti
    clock.advance(5)
    await dsm.on_event(_event(event_id="p1"))  # tekrar → alternating çıkış (out)

    assert len(db.door_events) == 1  # bir giriş
    assert len(db.closed) == 1  # tekrar-giriş çıkış olarak işlendi


async def test_dahua_failure_does_not_break() -> None:
    """Dahua alarm hatası geçiş kaydını bozmaz (best-effort)."""
    db, snaps = FakeDB(), FakeSnapshots()
    dahua = FakeDahua(raises=DahuaAlarmError("NVR yok"))
    dsm = DoorStateMachine(_door_cfg(), db, snaps, dahua=dahua)  # type: ignore[arg-type]

    await dsm.on_event(_event(event_id="p1"))

    assert len(db.door_events) == 1  # alarm hatasına rağmen event yazıldı
    assert len(dahua.calls) == 1
