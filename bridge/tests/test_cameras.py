"""CameraMonitor testleri — online/offline/threshold/recovery/Frigate-down."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from bridge.cameras import CameraMonitor
from bridge.config import Settings


class FakeDB:
    def __init__(self) -> None:
        self.statuses: dict[str, dict[str, Any]] = {}
        self.online_calls: list[str] = []
        self.offline_calls: list[str] = []

    async def get_camera_status(self, camera_id: str) -> dict[str, Any] | None:
        return self.statuses.get(camera_id)

    async def mark_camera_online(self, camera_id: str, now: datetime) -> None:
        self.online_calls.append(camera_id)
        self.statuses[camera_id] = {
            "camera_id": camera_id,
            "last_seen_at": now,
            "is_online": True,
            "offline_alert_sent": False,
        }

    async def mark_camera_offline(self, camera_id: str) -> None:
        self.offline_calls.append(camera_id)
        st = self.statuses.get(camera_id)
        if st:
            st["is_online"] = False
            st["offline_alert_sent"] = True


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"camera_offline_threshold_s": 60.0}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def _monitor(db: FakeDB, holder: dict[str, Any], clock: Clock) -> CameraMonitor:
    """CameraMonitor'ı MockTransport'lu stats endpoint ile kur."""
    m = CameraMonitor(_settings(), db, clock=clock)  # type: ignore[arg-type]

    def handler(request: httpx.Request) -> httpx.Response:
        if holder.get("fail"):
            raise httpx.ConnectError("frigate down")
        return httpx.Response(200, json=holder["stats"])

    m._client = httpx.AsyncClient(
        base_url="http://frigate:5000", transport=httpx.MockTransport(handler)
    )
    return m


def _stats(**cams: float) -> dict[str, Any]:
    """`cameras` wrapper'lı stats üret (0.14+ formatı)."""
    return {"cameras": {name: {"camera_fps": fps} for name, fps in cams.items()}}


# ---- Tests ----


async def test_camera_fps_positive_marks_online() -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    holder = {"stats": _stats(cam_test=5.0, cam_kapi=5.1)}
    m = _monitor(db, holder, clock)

    await m.check()

    assert set(db.online_calls) == {"cam_test", "cam_kapi"}
    assert db.offline_calls == []
    await m.close()


async def test_camera_offline_after_threshold() -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    holder = {"stats": _stats(cam_test=5.0)}
    m = _monitor(db, holder, clock)

    await m.check()  # t0: online, last_seen=t0
    holder["stats"] = _stats(cam_test=0.0)  # stream düştü
    clock.advance(70)  # threshold(60) aşıldı
    await m.check()

    assert db.offline_calls == ["cam_test"]
    await m.close()


async def test_camera_not_offline_before_threshold() -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    holder = {"stats": _stats(cam_test=5.0)}
    m = _monitor(db, holder, clock)

    await m.check()
    holder["stats"] = _stats(cam_test=0.0)
    clock.advance(30)  # threshold(60) içinde
    await m.check()

    assert db.offline_calls == []  # henüz offline değil
    await m.close()


async def test_camera_offline_alerts_once() -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    holder = {"stats": _stats(cam_test=5.0)}
    m = _monitor(db, holder, clock)

    await m.check()
    holder["stats"] = _stats(cam_test=0.0)
    clock.advance(70)
    await m.check()  # offline (1. uyarı)
    clock.advance(70)
    await m.check()  # hâlâ offline ama tekrar uyarmaz

    assert db.offline_calls == ["cam_test"]  # yalnız bir kez
    await m.close()


async def test_camera_recovery() -> None:
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    holder = {"stats": _stats(cam_test=5.0)}
    m = _monitor(db, holder, clock)

    await m.check()
    holder["stats"] = _stats(cam_test=0.0)
    clock.advance(70)
    await m.check()  # offline
    holder["stats"] = _stats(cam_test=5.0)  # geri geldi
    clock.advance(30)
    await m.check()  # recovery → mark_online

    assert db.offline_calls == ["cam_test"]
    assert db.statuses["cam_test"]["is_online"] is True  # tekrar online
    await m.close()


async def test_no_baseline_camera_skipped() -> None:
    """Hiç online olmamış kamera fps=0 ile gelirse atla (baseline yok)."""
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    holder = {"stats": _stats(cam_yeni=0.0)}
    m = _monitor(db, holder, clock)

    await m.check()

    assert db.offline_calls == []
    assert db.online_calls == []
    await m.close()


async def test_frigate_unreachable_no_marks() -> None:
    """Frigate /api/stats erişilemez → hiçbir kamera işaretlenmez."""
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    holder: dict[str, Any] = {"stats": _stats(cam_test=5.0), "fail": True}
    m = _monitor(db, holder, clock)

    await m.check()

    assert db.online_calls == []
    assert db.offline_calls == []
    await m.close()


async def test_top_level_fallback_and_non_camera_keys() -> None:
    """`cameras` wrapper yoksa top-level; camera_fps'siz key'ler atlanır."""
    db = FakeDB()
    clock = Clock(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    # Eski format: kameralar top-level + 'detectors' gibi kamera-olmayan key
    holder = {"stats": {"cam_test": {"camera_fps": 5.0}, "detectors": {"cpu1": {}}}}
    m = _monitor(db, holder, clock)

    await m.check()

    assert db.online_calls == ["cam_test"]  # detectors atlandı
    await m.close()
