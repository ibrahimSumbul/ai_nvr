"""Kamera offline tespiti — M7. Frigate `/api/stats` `camera_fps` izlenir.

Bir kamera RTSP stream'i düşerse Frigate o kameranın `camera_fps`'ini 0'a
düşürür. CameraMonitor periyodik olarak stats'ı çeker; `camera_fps>0` ise
kamerayı canlı (last_seen güncelle), aksi halde son görülmeden bu yana
`camera_offline_threshold_s` geçtiyse offline işaretler (bir kez uyarır).

Durum `camera_status` tablosunda tutulur (restart-safe). Offline uyarısı şimdilik
log + DB + Grafana; Dahua/DMSS offline alarmı ileride (kamera→NVR channel
eşlemesi + kullanıcı kararı gerekir).

Olay-tabanlı değil HTTP-poll: bir kameradan event gelmemesi "hareket yok"
demektir (offline değil); `camera_fps` gerçek stream sağlığını gösterir.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from bridge.config import Settings
from bridge.db import Database

log = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CameraMonitor:
    """Frigate stats'tan kamera online/offline durumunu izler."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._settings = settings
        self._db = db
        self._clock = clock
        self._threshold_s = settings.camera_offline_threshold_s
        self._client = httpx.AsyncClient(
            base_url=settings.frigate_internal_url,
            timeout=httpx.Timeout(10.0),
        )

    async def check(self) -> None:
        """Bir tur: stats çek, her kamera için online/offline durumunu güncelle."""
        now = self._clock()
        try:
            response = await self._client.get("/api/stats")
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Frigate erişilemez → kameraları offline işaretleme (Frigate down ≠
            # kamera down). Sadece log; bir sonraki tur tekrar dener.
            log.warning("camera.stats_unreachable", error=str(exc))
            return

        # Frigate 0.14+ stats kameraları `cameras` altında; eski sürüm top-level.
        cameras: dict[str, Any] = data.get("cameras", data)

        for cam_id, cam in cameras.items():
            if not isinstance(cam, dict) or "camera_fps" not in cam:
                continue  # 'detectors'/'service' gibi kamera-olmayan key'leri atla
            fps = cam.get("camera_fps") or 0
            st = await self._db.get_camera_status(cam_id)

            if fps > 0:
                was_offline = st is not None and not st["is_online"]
                await self._db.mark_camera_online(cam_id, now)
                if was_offline:
                    log.info("camera.recovered", camera=cam_id)
                continue

            # camera_fps == 0 → frame gelmiyor. Baseline yoksa (hiç online
            # olmadı) bekle. Aksi halde threshold + tek-uyarı kontrolü.
            if st is None or st["last_seen_at"] is None:
                continue
            elapsed = (now - st["last_seen_at"]).total_seconds()
            if elapsed > self._threshold_s and not st["offline_alert_sent"]:
                await self._db.mark_camera_offline(cam_id)
                log.warning(
                    "camera.offline",
                    camera=cam_id,
                    last_seen_s_ago=int(elapsed),
                    threshold_s=int(self._threshold_s),
                )

    async def close(self) -> None:
        await self._client.aclose()
