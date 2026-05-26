"""Zone state machine — docs/04-zone-rules.md.

Her zone iki state arasında geçer:
- EMPTY:    alan boş, ilk giriş `first_entry` üretir + (koşullarda) alarm
- OCCUPIED: alanda en az bir takip edilen obje var, sessiz heartbeat

Exit ölçütü: son event'ten beri `exit_timeout_seconds` geçtiyse OCCUPIED → EMPTY.
Bu "EXIT_PENDING" alt-durumu açıkça modellenmedi; tick() içinde implicit kontrol
edilir.

Tasarım kararları:
- Dedup: aynı Frigate tracking ID'sinin tekrar tekrar gelmesi heartbeat sayılır.
- Restart recovery: son DB event'inden state geri yüklenir (in-flight olayı kaçırma).
- **DB insert HER ZAMAN yapılır** (analiz için event log). Alarm tetikleme ayrı
  bir karar: `first_entry_alarm AND active_hour AND alert_on_empty_arrival`
  üçlüsü `alarm_emitted=True` üretir, M4'te Dahua external alarm bu flag ile
  tetiklenecek. Mesai dışı yapılan girişler de kayıt altında kalır.
- Tüm zaman karşılaştırmaları enjekte edilen `clock` ile yapılır (test edilebilirlik).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

import structlog

from bridge.db import Database
from bridge.events import FrigateEvent
from bridge.snapshots import SnapshotStore
from bridge.zone_config import ZoneConfig

log = structlog.get_logger(__name__)

ZoneState = Literal["EMPTY", "OCCUPIED"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_within_active_hours(now: datetime, spec: str) -> bool:
    """`"HH:MM-HH:MM"` formatında aktif saat kontrolü.

    "00:00-23:59" = her saat. Çapraz gece (örn. "18:00-08:00") desteklenir.
    """
    if spec == "00:00-23:59":
        return True
    try:
        start_s, end_s = spec.split("-", 1)
        sh, sm = (int(x) for x in start_s.split(":"))
        eh, em = (int(x) for x in end_s.split(":"))
    except ValueError:
        log.warning("active_hours.parse_failed", spec=spec)
        return True
    cur = now.hour * 60 + now.minute
    start = sh * 60 + sm
    end = eh * 60 + em
    if start <= end:
        return start <= cur <= end
    # Çapraz gece: 18:00-08:00 → 18:00–23:59 VEYA 00:00–08:00
    return cur >= start or cur <= end


class ZoneStateMachine:
    """Tek bir zone için state machine.

    Bridge her zone için bir instance tutar (`{zone_name: ZSM}`).
    Frigate event'leri `on_event` ile, periyodik exit kontrolü `tick` ile gelir.
    """

    def __init__(
        self,
        cfg: ZoneConfig,
        db: Database,
        snapshots: SnapshotStore,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._cfg = cfg
        self._db = db
        self._snapshots = snapshots
        self._clock = clock

        self._state: ZoneState = "EMPTY"
        self._since: datetime | None = None
        self._last_seen: datetime | None = None
        self._active_ids: set[str] = set()

    # ---- read-only state ----

    @property
    def state(self) -> ZoneState:
        return self._state

    @property
    def zone_name(self) -> str:
        return self._cfg.name

    # ---- recovery ----

    async def restore_from_db(self) -> None:
        """Restart sonrası son state'i DB'den yükle.

        Şu an sadece `first_entry` ile recovery yapılır. Gelecekte
        `still_present` heartbeat event'i eklendiğinde (M2.5+) bu fonksiyon
        genişletilmeli; aksi halde son event `still_present` ise yanlışlıkla
        EMPTY varsayılır.
        """
        last = await self._db.get_zone_last_event(self._cfg.name)
        if not last:
            return
        if last["event_type"] != "first_entry":
            log.info(
                "zone.restore_skipped",
                zone=self._cfg.name,
                last_event_type=last["event_type"],
            )
            return
        elapsed = (self._clock() - last["ts"]).total_seconds()
        if elapsed >= self._cfg.rules.exit_timeout_seconds:
            return
        # Restart sırasında alan dolu sayılır
        self._state = "OCCUPIED"
        self._since = last["ts"]
        self._last_seen = last["ts"]
        log.info(
            "zone.state_restored",
            zone=self._cfg.name,
            state="OCCUPIED",
            elapsed_s=elapsed,
        )

    # ---- event handling ----

    async def on_event(self, event: FrigateEvent) -> None:
        """Frigate event geldiğinde state machine'i ilerlet."""
        cfg = self._cfg
        if not cfg.rules.enabled:
            return

        # Filter: label, score, zone match
        if event.label not in cfg.rules.track_objects:
            return
        if event.score < cfg.rules.min_person_score:
            return

        in_zone = cfg.frigate_zone in event.current_zones
        now = self._clock()

        if not in_zone:
            # Obje bu zone'da değil (veya çıktı). `end` event ise ID'yi düş.
            if event.type == "end":
                self._active_ids.discard(event.event_id)
            return

        # Obje şu an bu zone'da
        self._last_seen = now
        self._active_ids.add(event.event_id)

        if self._state == "EMPTY":
            await self._handle_first_entry(event, now)
        # OCCUPIED → heartbeat, DB'ye yazılmaz

    async def _handle_first_entry(self, event: FrigateEvent, now: datetime) -> None:
        """Boş alana ilk giriş.

        State EMPTY → OCCUPIED geçişi yapılır.
        DB insert HER ZAMAN yapılır (event log; analiz için kayıtta kalmalı).
        Alarm tetikleme ayrı karar: `first_entry_alarm AND active_hour AND
        alert_on_empty_arrival` koşulunda `alarm_emitted=True` metadata'ya yazılır.
        M4'te Dahua external alarm bu flag'e bakacak.
        """
        cfg = self._cfg

        self._state = "OCCUPIED"
        self._since = now

        snapshot_path: str | None = None
        if event.after.has_snapshot:
            saved = await self._snapshots.fetch_event_snapshot(event.event_id)
            if saved is not None:
                snapshot_path = str(saved)

        is_active = _is_within_active_hours(now, cfg.rules.active_hours)
        alarm_emitted = (
            cfg.rules.first_entry_alarm and is_active and cfg.rules.alert_on_empty_arrival
        )

        metadata: dict[str, Any] = {
            "label": event.label,
            "active_hour": is_active,
            "alarm_emitted": alarm_emitted,
        }

        await self._db.insert_zone_event(
            zone=cfg.name,
            camera_id=event.camera,
            event_type="first_entry",
            ts=now,
            score=event.score,
            frigate_event_id=event.event_id,
            snapshot_path=snapshot_path,
            metadata=metadata,
        )
        log.info(
            "zone.first_entry",
            zone=cfg.name,
            event_id=event.event_id,
            score=round(event.score, 3),
            alarm_emitted=alarm_emitted,
            active_hour=is_active,
        )
        # M4'te buraya Dahua alarm tetiklemesi eklenecek:
        # if alarm_emitted:
        #     await self._dahua.trigger_external_alarm(event.camera, "person_entered")

    async def tick(self, now: datetime | None = None) -> None:
        """Periyodik exit kontrolü. M2'de 10 sn'de bir çağrılır."""
        if self._state != "OCCUPIED":
            return
        if self._last_seen is None:
            return
        ts = now or self._clock()
        elapsed = (ts - self._last_seen).total_seconds()
        if elapsed >= self._cfg.rules.exit_timeout_seconds:
            await self._handle_exit(ts)

    async def _handle_exit(self, now: datetime) -> None:
        cfg = self._cfg
        duration_s: float | None = None
        if self._since is not None:
            duration_s = (now - self._since).total_seconds()

        metadata: dict[str, float] = {}
        if duration_s is not None:
            metadata["duration_s"] = duration_s

        await self._db.insert_zone_event(
            zone=cfg.name,
            camera_id=cfg.camera,
            event_type="exit",
            ts=now,
            metadata=metadata,
        )
        log.info("zone.exit", zone=cfg.name, duration_s=duration_s)

        self._state = "EMPTY"
        self._since = None
        self._last_seen = None
        self._active_ids.clear()
