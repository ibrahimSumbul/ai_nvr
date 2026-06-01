"""Kapı geçiş state machine — M6.5. docs/04-zone-rules.md (door tipi).

Oda (ZoneStateMachine) occupancy modeli izlerken, kapı farklı: her **geçiş**
(traversal) bir olaydır, saniye/ms hassasiyetinde loglanır ve her geçişte
Dahua external alarm → DMSS push tetiklenir.

Yön (direction) belirleme — basit **alternating** model:
- 1. geçiş → "in" (giriş): yeni door_event açar (entry_ts)
- 2. geçiş → "out" (çıkış): açık oturumu kapatır (exit_ts + duration_ms)
- 3. geçiş → yeni "in", ...

⚠️ NOT: Bu alternating varsayımı **genel geçer DEĞİLDİR.** Gerçek giriş/çıkış
yönü kameranın açısına, kapının geometrisine ve sahneye göre değişir (örn. iki
ayrı kişi arka arkaya girerse ikincisi yanlışlıkla "çıkış" sayılır). Her kamera
ve kurulum için ayrıca değerlendirilmeli; ileride çok-zone (iç/dış) geçiş yönü
veya hareket vektörü ile iyileştirilebilir. Şimdilik tek-kapı basit model.

Restart davranışı: açık oturum bellekte tutulur, restart'ta sıfırlanır — bir
sonraki geçiş "giriş" sayılır (kabul edilen basitleştirme; M7 session-timeout).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import structlog

from bridge.dahua import DahuaAlarmClient, DahuaAlarmError
from bridge.db import Database
from bridge.events import FrigateEvent
from bridge.snapshots import SnapshotStore
from bridge.zone_config import ZoneConfig

log = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DoorStateMachine:
    """Tek bir kapı zone'u için traversal (geçiş) detektörü.

    ZoneStateMachine ile aynı arayüz (on_event/tick/restore_from_db/zone_name)
    — main.py routing'i tip'e göre seçer.
    """

    def __init__(
        self,
        cfg: ZoneConfig,
        db: Database,
        snapshots: SnapshotStore,
        clock: Callable[[], datetime] = _utcnow,
        dahua: DahuaAlarmClient | None = None,
    ) -> None:
        self._cfg = cfg
        self._db = db
        self._snapshots = snapshots
        self._clock = clock
        self._dahua = dahua

        # Açık giriş oturumu (alternating): None → sıradaki geçiş "in"
        self._open_event_id: int | None = None
        self._open_entry_ts: datetime | None = None
        # Heartbeat dedup + cooldown
        self._processed_ids: set[str] = set()
        self._last_traversal_ts: datetime | None = None

    @property
    def zone_name(self) -> str:
        return self._cfg.name

    async def restore_from_db(self) -> None:
        """Kapı oturumu bellekte; restart'ta sıfırlanır (basitleştirme)."""
        return

    async def tick(self, now: datetime | None = None) -> None:
        """Kapı geçişi anlık — periyodik iş yok. (M7: session-timeout eklenebilir.)"""
        return

    async def on_event(self, event: FrigateEvent) -> None:
        """Frigate event → kapı geçişi tespiti (alternating in/out)."""
        cfg = self._cfg
        if not cfg.rules.enabled:
            return
        if event.label not in cfg.rules.track_objects:
            return
        if event.score < cfg.rules.min_person_score:
            return

        tracking_id = event.event_id

        # `end` = tracking session bitti. Zone içinde/dışında olmasına BAKMAKSIZIN
        # dedup işaretini temizle. Frigate `end` event'i nesne hâlâ zone'dayken de
        # gelebilir; aksi halde `_processed_ids` sınırsız büyür (7/24 bellek
        # sızıntısı). Temizlik ayrıca aynı kişi tekrar girince yeni geçiş sağlar.
        if event.type == "end":
            self._processed_ids.discard(tracking_id)
            return

        in_zone = cfg.frigate_zone in event.current_zones
        if not in_zone:
            return

        # Zone içinde. Aynı tracking_id'nin tekrarı = heartbeat, sayma.
        if tracking_id in self._processed_ids:
            return

        now = self._clock()
        # Cooldown debounce — çok hızlı ardışık geçişleri yut
        if (
            self._last_traversal_ts is not None
            and (now - self._last_traversal_ts).total_seconds() < cfg.rules.cooldown_seconds
        ):
            self._processed_ids.add(tracking_id)
            log.debug("door.cooldown_skip", zone=cfg.name, tracking_id=tracking_id)
            return

        self._processed_ids.add(tracking_id)
        self._last_traversal_ts = now
        await self._handle_traversal(event, now)

    async def _handle_traversal(self, event: FrigateEvent, now: datetime) -> None:
        """Bir geçiş: açık oturum yoksa giriş, varsa çıkış (alternating)."""
        cfg = self._cfg

        snapshot_path: str | None = None
        if event.after.has_snapshot:
            saved = await self._snapshots.fetch_event_snapshot(event.event_id)
            if saved is not None:
                snapshot_path = str(saved)

        if self._open_event_id is None:
            # GİRİŞ — yeni oturum aç
            event_id = await self._db.insert_door_event(
                zone=cfg.name,
                camera_id=event.camera,
                entry_ts=now,
                direction="in",
                tracking_id=event.event_id,
                entry_snapshot_path=snapshot_path,
                metadata={"label": event.label, "score": round(event.score, 3)},
            )
            self._open_event_id = event_id
            self._open_entry_ts = now
            log.info("door.entry", zone=cfg.name, door_event_id=event_id, tracking_id=event.event_id)
            await self._emit_dahua_alarm("door_entry")
        else:
            # ÇIKIŞ — açık oturumu kapat
            duration_ms = 0
            if self._open_entry_ts is not None:
                duration_ms = int((now - self._open_entry_ts).total_seconds() * 1000)
            await self._db.close_door_event(
                self._open_event_id,
                exit_ts=now,
                duration_ms=duration_ms,
                exit_snapshot_path=snapshot_path,
            )
            log.info(
                "door.exit",
                zone=cfg.name,
                door_event_id=self._open_event_id,
                duration_ms=duration_ms,
            )
            self._open_event_id = None
            self._open_entry_ts = None
            await self._emit_dahua_alarm("door_exit")

    async def _emit_dahua_alarm(self, event_type: str) -> None:
        """Kapı geçişinde Dahua external alarm → DMSS push (best-effort).

        Inline retry DahuaClient içinde (exp. backoff). Zone'daki pending retry
        kuyruğu door'a uygulanmaz — kapı geçişi anlık, kaçırılırsa bir sonraki
        geçiş zaten yeni alarm üretir. Başarısızlık log'lanır.
        """
        if self._dahua is None:
            return
        cfg = self._cfg
        try:
            await self._dahua.trigger_external_alarm(
                channel=cfg.rules.dahua_channel,
                event_type=event_type,
                description=f"{cfg.name}: kapi gecisi ({event_type})",
            )
        except DahuaAlarmError as exc:
            log.warning("door.dahua_alarm_failed", zone=cfg.name, event_type=event_type, error=str(exc))
            return
        log.info("door.dahua_alarm_sent", zone=cfg.name, event_type=event_type)
