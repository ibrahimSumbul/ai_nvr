"""FrigateMonitor testleri — available online/offline, alarm tek-uyarı, recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bridge.dahua import DahuaAlarmError
from bridge.frigate_monitor import SERVICE, FrigateMonitor


class FakeDB:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.online_calls: list[str] = []
        self.offline_calls: list[str] = []

    async def get_service_status(self, service: str) -> dict[str, Any] | None:
        row = self.rows.get(service)
        return dict(row) if row else None

    async def mark_service_online(self, service: str, now: datetime) -> None:
        # Gerçek SQL CASE semantiğini yansıt: last_change_at yalnız geçişte güncellenir.
        self.online_calls.append(service)
        prev = self.rows.get(service)
        last_change = prev["last_change_at"] if prev and prev["is_online"] else now
        self.rows[service] = {
            "service": service,
            "is_online": True,
            "last_change_at": last_change,
            "offline_alert_sent": False,
        }

    async def mark_service_offline(self, service: str, now: datetime) -> None:
        self.offline_calls.append(service)
        prev = self.rows.get(service)
        last_change = prev["last_change_at"] if prev and not prev["is_online"] else now
        self.rows[service] = {
            "service": service,
            "is_online": False,
            "last_change_at": last_change,
            "offline_alert_sent": True,
        }


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


def _clock() -> datetime:
    return datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self.now += timedelta(seconds=seconds)


def _monitor(db: FakeDB, dahua: FakeDahua | None = None, channel: int = 1) -> FrigateMonitor:
    return FrigateMonitor(db, dahua=dahua, channel=channel, clock=_clock)  # type: ignore[arg-type]


# ---- Tests ----


async def test_online_marks_online_no_alarm() -> None:
    db = FakeDB()
    dahua = FakeDahua()
    m = _monitor(db, dahua)

    await m.on_availability("online")

    assert db.online_calls == [SERVICE]
    assert db.rows[SERVICE]["is_online"] is True
    assert dahua.calls == []


async def test_offline_first_seen_alarms_once() -> None:
    db = FakeDB()
    dahua = FakeDahua()
    m = _monitor(db, dahua)

    await m.on_availability("offline")  # baseline yok → offline + alarm
    await m.on_availability("offline")  # hâlâ offline → tekrar uyarmaz

    assert db.offline_calls == [SERVICE, SERVICE]  # her mesajda işaretlenir
    assert len(dahua.calls) == 1  # ama alarm yalnız bir kez
    assert dahua.calls[0]["event_type"] == "frigate_offline"


async def test_online_then_offline_alarms() -> None:
    db = FakeDB()
    dahua = FakeDahua()
    m = _monitor(db, dahua)

    await m.on_availability("online")
    await m.on_availability("offline")

    assert len(dahua.calls) == 1
    assert db.rows[SERVICE]["is_online"] is False


async def test_recovery_then_offline_realarms() -> None:
    db = FakeDB()
    dahua = FakeDahua()
    m = _monitor(db, dahua)

    await m.on_availability("online")
    await m.on_availability("offline")  # alarm 1
    await m.on_availability("online")  # recovery (flag reset)
    await m.on_availability("offline")  # alarm 2

    assert len(dahua.calls) == 2


async def test_offline_uses_configured_channel() -> None:
    db = FakeDB()
    dahua = FakeDahua()
    m = _monitor(db, dahua, channel=5)

    await m.on_availability("offline")

    assert dahua.calls[0]["channel"] == 5


async def test_alarm_failure_does_not_break() -> None:
    db = FakeDB()
    dahua = FakeDahua(raises=DahuaAlarmError("NVR yok"))
    m = _monitor(db, dahua)

    await m.on_availability("offline")

    assert db.offline_calls == [SERVICE]  # alarm hatasına rağmen offline işaretlendi
    assert len(dahua.calls) == 1


async def test_no_dahua_no_crash() -> None:
    db = FakeDB()
    m = _monitor(db, dahua=None)

    await m.on_availability("offline")

    assert db.rows[SERVICE]["is_online"] is False  # offline işaretlendi, push yok


async def test_payload_case_and_whitespace_insensitive() -> None:
    db = FakeDB()
    dahua = FakeDahua()
    m = _monitor(db, dahua)

    await m.on_availability("  ONLINE\n")  # baseline online
    await m.on_availability("Offline")  # → offline + alarm

    assert db.rows[SERVICE]["is_online"] is False
    assert len(dahua.calls) == 1


async def test_last_change_at_only_updates_on_transition() -> None:
    """Tekrar mesajlarda (retained redelivery / reconnect) last_change_at kaymaz."""
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    m = FrigateMonitor(db, dahua=FakeDahua(), channel=1, clock=clock)  # type: ignore[arg-type]

    await m.on_availability("online")  # t0: geçiş → last_change_at = t0
    t0 = db.rows[SERVICE]["last_change_at"]
    clock.advance(120)
    await m.on_availability("online")  # tekrar online (reconnect retained) → değişmemeli
    assert db.rows[SERVICE]["last_change_at"] == t0

    clock.advance(60)
    await m.on_availability("offline")  # gerçek geçiş → last_change_at güncellenir
    t_off = db.rows[SERVICE]["last_change_at"]
    assert t_off == clock.now
    clock.advance(300)
    await m.on_availability("offline")  # tekrar offline → değişmemeli
    assert db.rows[SERVICE]["last_change_at"] == t_off


async def test_unknown_payload_ignored() -> None:
    """`online`/`offline` dışı payload (örn. bozuk mesaj) yok sayılır — false-alarm yok."""
    db = FakeDB()
    dahua = FakeDahua()
    m = _monitor(db, dahua)

    await m.on_availability("garbage")
    await m.on_availability("")

    assert db.online_calls == []
    assert db.offline_calls == []
    assert dahua.calls == []
