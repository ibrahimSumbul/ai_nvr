"""DiskMonitor testleri — örnekleme/eşik alarmı/histerezis/recovery/budama."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bridge.config import Settings
from bridge.dahua import DahuaAlarmError
from bridge.disk import DiskMonitor


class FakeDB:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.upsert_pcts: list[float] = []
        self.alert_sets: list[tuple[str, bool]] = []

    async def get_disk_status(self, mount: str) -> dict[str, Any] | None:
        row = self.rows.get(mount)
        return dict(row) if row else None

    async def upsert_disk_status(
        self,
        mount: str,
        checked_at: datetime,
        used_pct: float,
        used_bytes: int,
        total_bytes: int,
        snapshot_bytes: int,
        snapshot_files: int,
        last_pruned_at: datetime | None,
        pruned_files_last: int,
    ) -> None:
        row = self.rows.get(mount, {"alert_sent": False})  # alert_sent çakışmada korunur
        row.update(
            {
                "mount": mount,
                "checked_at": checked_at,
                "used_pct": used_pct,
                "used_bytes": used_bytes,
                "total_bytes": total_bytes,
                "snapshot_bytes": snapshot_bytes,
                "snapshot_files": snapshot_files,
                "last_pruned_at": last_pruned_at,
                "pruned_files_last": pruned_files_last,
            }
        )
        self.rows[mount] = row
        self.upsert_pcts.append(used_pct)

    async def set_disk_alert_sent(self, mount: str, sent: bool) -> None:
        self.rows[mount]["alert_sent"] = sent
        self.alert_sets.append((mount, sent))


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
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "disk_warn_threshold_pct": 85.0,
        "disk_recover_margin_pct": 5.0,  # recover eşiği = 80
        "snapshot_retention_days": 90,
        "snapshot_prune_interval_s": 3600.0,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def _usage(pct: float, total: int = 10_000) -> Any:
    """`(total, used, free)` usage_fn — used = pct%×total, free = total−used.

    free = total−used (rezerve=0, APFS gibi) → used/(used+free) = used/total = pct.
    total=10_000 → 2 ondalık eşik (örn. 79.99) tam-sayı yuvarlamadan etkilenmez.
    """
    used = int(round(pct / 100.0 * total))
    return lambda _path: (total, used, total - used)


def _monitor(
    db: FakeDB,
    snap_dir: Path,
    clock: Clock,
    pct: float,
    dahua: FakeDahua | None = None,
    **settings_overrides: Any,
) -> DiskMonitor:
    return DiskMonitor(
        _settings(**settings_overrides),
        db,  # type: ignore[arg-type]
        snap_dir,
        clock=clock,
        dahua=dahua,  # type: ignore[arg-type]
        usage_fn=_usage(pct),
    )


def _write(path: Path, mtime_ts: float, content: bytes = b"xxxx") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (mtime_ts, mtime_ts))


# ---- Örnekleme + eşik ----


async def test_sample_writes_status_no_alarm_under_threshold(tmp_path: Path) -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dahua = FakeDahua()
    m = _monitor(db, tmp_path, clock, pct=50.0, dahua=dahua)

    await m.check()

    assert db.upsert_pcts == [50.0]
    assert dahua.calls == []
    assert db.rows[m.mount]["alert_sent"] is False


async def test_threshold_exceeded_fires_alarm_once(tmp_path: Path) -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dahua = FakeDahua()
    m = _monitor(db, tmp_path, clock, pct=90.0, dahua=dahua)

    await m.check()  # eşik aşıldı → alarm
    await m.check()  # hâlâ %90 ama tekrar uyarmaz

    assert len(dahua.calls) == 1
    assert dahua.calls[0]["event_type"] == "disk_full"
    assert db.rows[m.mount]["alert_sent"] is True


async def test_alarm_uses_default_channel(tmp_path: Path) -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dahua = FakeDahua()
    m = _monitor(db, tmp_path, clock, pct=95.0, dahua=dahua)

    await m.check()

    assert dahua.calls[0]["channel"] == 1  # settings.dahua_alarm_channel default


async def test_alarm_fires_exactly_at_warn_threshold(tmp_path: Path) -> None:
    """Tam eşikte (used_pct == warn=85) alarm ateşlenir — `>=` inclusive sınırı."""
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dahua = FakeDahua()
    m = _monitor(db, tmp_path, clock, pct=85.0, dahua=dahua)

    await m.check()

    assert len(dahua.calls) == 1
    assert db.rows[m.mount]["alert_sent"] is True


async def test_no_recover_exactly_at_recover_threshold(tmp_path: Path) -> None:
    """Tam recover eşiğinde (== 80) flag DÜŞMEZ; hemen altı (79.99) → reset. `<` strict."""
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dahua = FakeDahua()
    m = _monitor(db, tmp_path, clock, pct=90.0, dahua=dahua)
    await m.check()  # armed (alert_sent=True)

    m._usage_fn = _usage(80.0)  # type: ignore[assignment]
    await m.check()
    assert db.rows[m.mount]["alert_sent"] is True  # tam sınırda reset YOK

    m._usage_fn = _usage(79.99)  # type: ignore[assignment]
    await m.check()
    assert db.rows[m.mount]["alert_sent"] is False  # sınırın hemen altı → reset


async def test_recover_margin_override(tmp_path: Path) -> None:
    """disk_recover_margin_pct override → recover eşiği warn−margin'den türer (85−10=75)."""
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dahua = FakeDahua()
    m = _monitor(db, tmp_path, clock, pct=90.0, dahua=dahua, disk_recover_margin_pct=10.0)
    await m.check()  # armed

    m._usage_fn = _usage(78.0)  # type: ignore[assignment]  # 75 < 78 < 85 → band içi
    await m.check()
    assert db.rows[m.mount]["alert_sent"] is True  # default margin (5) olsaydı reset olurdu

    m._usage_fn = _usage(74.0)  # type: ignore[assignment]  # recover(75) altı
    await m.check()
    assert db.rows[m.mount]["alert_sent"] is False


async def test_upsert_records_used_and_total_bytes(tmp_path: Path) -> None:
    """used_bytes/total_bytes doğru kolonlara yazılır (arg-sırası swap regresyonu)."""
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    m = _monitor(db, tmp_path, clock, pct=50.0)  # total=10_000 → used=5_000

    await m.check()

    assert db.rows[m.mount]["used_bytes"] == 5_000
    assert db.rows[m.mount]["total_bytes"] == 10_000


async def test_hysteresis_no_reset_between_recover_and_warn(tmp_path: Path) -> None:
    """%82 (recover 80 < x < warn 85) → flag düşmez, yeni alarm yok."""
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dahua = FakeDahua()
    m = _monitor(db, tmp_path, clock, pct=90.0, dahua=dahua)
    await m.check()  # alarm

    m._usage_fn = _usage(82.0)  # type: ignore[assignment]
    await m.check()  # histerezis bandında

    assert len(dahua.calls) == 1
    assert db.rows[m.mount]["alert_sent"] is True  # hâlâ set


async def test_recovery_resets_then_realarms(tmp_path: Path) -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dahua = FakeDahua()
    m = _monitor(db, tmp_path, clock, pct=90.0, dahua=dahua)
    await m.check()  # alarm 1

    m._usage_fn = _usage(70.0)  # type: ignore[assignment]  # recover (80) altı
    await m.check()
    assert db.rows[m.mount]["alert_sent"] is False  # reset

    m._usage_fn = _usage(90.0)  # type: ignore[assignment]
    await m.check()  # tekrar eşik → alarm 2

    assert len(dahua.calls) == 2


async def test_alarm_failure_does_not_break_upsert(tmp_path: Path) -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    dahua = FakeDahua(raises=DahuaAlarmError("NVR yok"))
    m = _monitor(db, tmp_path, clock, pct=90.0, dahua=dahua)

    await m.check()  # alarm hata atar ama check tamamlanır

    assert db.upsert_pcts == [90.0]
    assert db.rows[m.mount]["alert_sent"] is True
    assert len(dahua.calls) == 1


async def test_no_dahua_no_crash(tmp_path: Path) -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    m = _monitor(db, tmp_path, clock, pct=95.0, dahua=None)

    await m.check()

    assert db.rows[m.mount]["alert_sent"] is True  # flag yine set (push yok)


async def test_zero_total_no_div_by_zero(tmp_path: Path) -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    m = DiskMonitor(
        _settings(),
        db,  # type: ignore[arg-type]
        tmp_path,
        clock=clock,
        usage_fn=lambda _p: (0, 0, 0),
    )

    await m.check()

    assert db.upsert_pcts == [0.0]


# ---- Snapshot budama ----


async def test_prune_deletes_old_keeps_new(tmp_path: Path) -> None:
    db = FakeDB()
    now = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
    clock = Clock(now)
    cutoff = (now - timedelta(days=90)).timestamp()
    _write(tmp_path / "2025-09-01" / "old.jpg", cutoff - 86400)  # retention'dan eski
    _write(tmp_path / "2026-01-01" / "new.jpg", cutoff + 86400)  # taze
    m = _monitor(db, tmp_path, clock, pct=10.0)

    await m.check()

    assert not (tmp_path / "2025-09-01" / "old.jpg").exists()
    assert (tmp_path / "2026-01-01" / "new.jpg").exists()
    assert db.rows[m.mount]["pruned_files_last"] == 1
    assert db.rows[m.mount]["snapshot_files"] == 1  # sadece taze dosya sayıldı


async def test_prune_throttled_by_interval(tmp_path: Path) -> None:
    """İlk check'te budar; interval dolmadan ikinci check budamaz."""
    db = FakeDB()
    now = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
    clock = Clock(now)
    m = _monitor(db, tmp_path, clock, pct=10.0)

    await m.check()  # ilk budama (t0)
    # interval (3600s) dolmadan eski bir dosya ekle
    cutoff = (clock.now - timedelta(days=90)).timestamp()
    _write(tmp_path / "late_old.jpg", cutoff - 86400)
    clock.advance(60)
    await m.check()  # interval dolmadı → budama yapılmaz
    assert (tmp_path / "late_old.jpg").exists()

    clock.advance(3600)
    await m.check()  # interval doldu → budanır
    assert not (tmp_path / "late_old.jpg").exists()


async def test_missing_snapshot_dir_is_safe(tmp_path: Path) -> None:
    """Snapshot dizini henüz yoksa (hiç snapshot yazılmadı) check patlamaz."""
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    missing = tmp_path / "yok" / "snapshots"
    m = DiskMonitor(
        _settings(),
        db,  # type: ignore[arg-type]
        missing,
        clock=clock,
        usage_fn=_usage(10.0),
    )

    await m.check()

    assert db.rows[m.mount]["snapshot_files"] == 0
    assert db.rows[m.mount]["pruned_files_last"] == 0
