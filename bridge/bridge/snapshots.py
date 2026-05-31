"""Frigate snapshot fetcher.

Frigate API'sinden bir event'in snapshot'ını alır, local diske yazar.
M2'de zone first_entry için snapshot kaydı. M3'te bu snapshot Haiku'ya gider
(tır renk analizi, anomali doğrulama).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog

log = structlog.get_logger(__name__)


class SnapshotStore:
    """Frigate event snapshot'larını fetch + local disk."""

    def __init__(
        self,
        frigate_url: str = "http://frigate:5000",
        base_dir: Path = Path("/var/lib/ainvr/snapshots"),
        timeout: float = 10.0,
    ) -> None:
        self._base_dir = base_dir
        self._client = httpx.AsyncClient(
            base_url=frigate_url,
            timeout=httpx.Timeout(timeout),
        )

    async def fetch_event_snapshot(
        self, event_id: str, height: int | None = None
    ) -> Path | None:
        """Frigate event ID için snapshot'ı indir, diske yaz, path döndür.

        Frigate `/api/events/<event_id>/snapshot.jpg` endpoint'ine erişir.
        `height` verilirse Frigate server-side resize uygular (`?height=N`) —
        LLM'e gönderilecek snapshot'ı küçültüp inference latency'sini sınırlar.
        Hata varsa None döner; bridge çağıran tarafta None'a göre davranır.
        """
        path = self._make_path(event_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"/api/events/{event_id}/snapshot.jpg"
        if height is not None:
            url += f"?height={height}"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning(
                "snapshot.fetch_failed",
                event_id=event_id,
                error=str(exc),
            )
            return None

        path.write_bytes(response.content)
        log.info(
            "snapshot.saved",
            event_id=event_id,
            path=str(path),
            bytes=len(response.content),
        )
        return path

    async def fetch_camera_latest(self, camera: str) -> Path | None:
        """Kameranın o anki canlı snapshot'ı (event'siz)."""
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        path = self._base_dir / "latest" / f"{camera}_{ts}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = await self._client.get(f"/api/{camera}/latest.jpg")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("snapshot.fetch_camera_failed", camera=camera, error=str(exc))
            return None

        path.write_bytes(response.content)
        return path

    def _make_path(self, event_id: str) -> Path:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        return self._base_dir / date / f"{event_id}.jpg"

    async def close(self) -> None:
        await self._client.aclose()
