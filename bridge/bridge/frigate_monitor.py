"""Frigate servis sağlığı (down-detection) — M7.

`CameraMonitor` Frigate `/api/stats`'ı poll edip **kameraları** izler ama Frigate'in
**kendisi** düşerse kameraları offline işaretlemez (Frigate down ≠ kamera down). O
boşluğu bu modül kapatır: Frigate'in MQTT availability topic'i (`frigate/available`,
retained + LWT, payload `online`/`offline`) dinlenir.

- `offline` (Frigate çöktü → broker LWT yayınlar) → bir kez Dahua external alarm
  (`frigate_offline`) → DMSS push. Tek-uyarı; recovery'de flag resetlenir, tekrar
  düşerse yeniden uyarır (kamera offline ile aynı desen).
- Durum `service_status` tablosunda tutulur (restart-safe: bridge yeniden başlayıp
  retained `offline`'ı alsa bile DB'deki `offline_alert_sent` mükerrer alarmı önler).

Olay-tabanlı (MQTT), poll değil — availability anında bilinir, ayrı interval gerekmez.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import structlog

from bridge.dahua import DahuaAlarmClient, DahuaAlarmError
from bridge.db import Database

log = structlog.get_logger(__name__)

SERVICE = "frigate"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FrigateMonitor:
    """`frigate/available` LWT'sinden Frigate servis online/offline durumunu izler."""

    def __init__(
        self,
        db: Database,
        dahua: DahuaAlarmClient | None = None,
        channel: int = 1,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._db = db
        self._dahua = dahua
        self._channel = channel
        self._clock = clock

    async def on_availability(self, payload: str) -> None:
        """`frigate/available` mesajını işle. Yalnız `online`/`offline` dikkate alınır."""
        val = payload.strip().lower()
        if val not in ("online", "offline"):
            log.debug("frigate.availability_unknown", payload=payload[:50])
            return

        now = self._clock()
        st = await self._db.get_service_status(SERVICE)

        if val == "online":
            was_offline = st is not None and not st["is_online"]
            await self._db.mark_service_online(SERVICE, now)
            if was_offline:
                log.info("frigate.recovered")
            return

        # offline — Frigate down. Önce alarm-gönderildi mi diye bak (tek-uyarı).
        already_alerted = st is not None and st["offline_alert_sent"]
        await self._db.mark_service_offline(SERVICE, now)
        if not already_alerted:
            log.warning(
                "frigate.offline", msg="Frigate servisi cevrimdisi (MQTT available=offline)"
            )
            await self._emit_offline_alarm()

    async def _emit_offline_alarm(self) -> None:
        """Frigate down → Dahua external alarm → DMSS push (best-effort)."""
        if self._dahua is None:
            return
        try:
            await self._dahua.trigger_external_alarm(
                channel=self._channel,
                event_type="frigate_offline",
                description="Frigate servisi cevrimdisi (tespit pipeline durdu)",
            )
        except DahuaAlarmError as exc:
            log.warning("frigate.offline_alarm_failed", error=str(exc))
            return
        log.info("frigate.offline_alarm_sent", channel=self._channel)
