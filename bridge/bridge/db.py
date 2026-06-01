"""Postgres async bağlantı havuzu + zone event yazma/okuma."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import asyncpg
import structlog

from bridge.config import Settings

log = structlog.get_logger(__name__)


class Database:
    """asyncpg connection pool sarmalayıcısı."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Bağlantı havuzunu aç ve smoke test (SELECT 1) çalıştır."""
        if self._pool is not None:
            return
        log.info(
            "db.connecting",
            host=self._settings.postgres_host,
            port=self._settings.postgres_port,
            db=self._settings.postgres_db,
        )
        self._pool = await asyncpg.create_pool(
            self._settings.postgres_dsn,
            min_size=1,
            max_size=10,
            command_timeout=30,
        )
        async with self._pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        log.info("db.connected")

    async def close(self) -> None:
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None
        log.info("db.closed")

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database not connected — call connect() first")
        return self._pool

    # ---- Zone events ----

    async def insert_zone_event(
        self,
        zone: str,
        camera_id: str,
        event_type: str,
        ts: datetime,
        score: float | None = None,
        frigate_event_id: str | None = None,
        snapshot_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Zone event insert. ID döndürür.

        Idempotency çağıran tarafta (state machine) memory cache ile sağlanır;
        DB tarafında unique constraint yok (M2.5'te eklenecek).
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO zone_events
                    (zone, camera_id, event_type, ts, score,
                     frigate_event_id, snapshot_path, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                RETURNING id
                """,
                zone,
                camera_id,
                event_type,
                ts,
                score,
                frigate_event_id,
                snapshot_path,
                json.dumps(metadata or {}),
            )
            log.info(
                "zone_event.inserted",
                id=row["id"],
                zone=zone,
                event_type=event_type,
                frigate_event_id=frigate_event_id,
            )
            return int(row["id"])

    async def get_zone_last_event(self, zone: str) -> dict[str, Any] | None:
        """Zone için son event (restart recovery)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT event_type, ts, frigate_event_id
                FROM zone_events
                WHERE zone = $1
                ORDER BY ts DESC
                LIMIT 1
                """,
                zone,
            )
            return dict(row) if row else None

    # ---- Dahua alarm tracking (M4) ----

    async def mark_dahua_alarm_sent(self, zone_event_id: int) -> None:
        """Bir zone event için Dahua alarm başarıyla gönderildi olarak işaretle."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE zone_events SET dahua_alarm_sent = TRUE WHERE id = $1",
                zone_event_id,
            )

    async def increment_dahua_retry(self, zone_event_id: int) -> int:
        """Dahua alarm retry sayacını artır, yeni değeri döndür."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE zone_events
                SET dahua_alarm_retry_count = dahua_alarm_retry_count + 1
                WHERE id = $1
                RETURNING dahua_alarm_retry_count
                """,
                zone_event_id,
            )
            return int(row["dahua_alarm_retry_count"]) if row else 0

    async def get_pending_dahua_alarms(
        self, max_retries: int, older_than_seconds: float, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Gönderilememiş alarm'lar (retry worker için).

        Koşul: first_entry + alarm_emitted=true + henüz gönderilmemiş +
        retry sayısı limiti aşmamış + olay `older_than_seconds`'tan eski.

        `older_than_seconds` claim guard'ıdır: `_handle_first_entry` event'i
        FALSE insert edip inline alarm denemesini *await* ettiği için (worst-case
        ~timeout×deneme), bu pencere kapanmadan worker AYNI event'i alıp ikinci
        kez push etmemeli. Worker bu değeri inline worst-case'den büyük verir.
        Yan fayda: inline tamamlanmadan bridge crash olsa bile event bu süre
        sonra worker tarafından devralınır (alarm kaybı yok).

        Her worker tick'i bir event için tek `dahua_alarm_retry_count` artışı
        sayar (içerideki inline retry'lar hariç). En eski önce (FIFO).
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, zone, camera_id, ts, dahua_alarm_retry_count,
                       metadata
                FROM zone_events
                WHERE event_type = 'first_entry'
                  AND dahua_alarm_sent = FALSE
                  AND dahua_alarm_retry_count < $1
                  AND (metadata->>'alarm_emitted')::bool = TRUE
                  AND ts < (NOW() - make_interval(secs => $2))
                ORDER BY ts ASC
                LIMIT $3
                """,
                max_retries,
                float(older_than_seconds),
                limit,
            )
            return [dict(r) for r in rows]

    # ---- LLM usage (M3+) ----

    async def insert_llm_usage(
        self,
        call_type: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int,
        cost_usd: float,
        latency_ms: int,
        success: bool,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """LLM çağrı log'u — Ollama'da cost_usd=0 (electric)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO llm_usage
                    (call_type, model, input_tokens, output_tokens,
                     cached_input_tokens, cost_usd, latency_ms, success,
                     error, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
                RETURNING id
                """,
                call_type,
                model,
                input_tokens,
                output_tokens,
                cached_input_tokens,
                cost_usd,
                latency_ms,
                success,
                error,
                json.dumps(metadata or {}),
            )
            return int(row["id"])

    # ---- Truck events (M3+) ----

    async def insert_truck_event(
        self,
        camera_id: str,
        ts: datetime,
        cekici_rengi: str | None,
        dorse_var_mi: bool,
        dorse_rengi: str | None,
        dorse_tipi: str | None,
        yon: str | None,
        guven: float,
        notlar: str | None,
        snapshot_path: str | None,
        llm_usage_id: int | None,
        frigate_event_id: str | None = None,
    ) -> int:
        """Truck color analysis sonucu DB'ye yaz."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO truck_events
                    (camera_id, ts, cekici_rengi, dorse_var_mi, dorse_rengi,
                     dorse_tipi, yon, guven, notlar, snapshot_path, llm_usage_id,
                     metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)
                RETURNING id
                """,
                camera_id,
                ts,
                cekici_rengi,
                dorse_var_mi,
                dorse_rengi,
                dorse_tipi,
                yon,
                guven,
                notlar,
                snapshot_path,
                llm_usage_id,
                json.dumps({"frigate_event_id": frigate_event_id} if frigate_event_id else {}),
            )
            log.info(
                "truck_event.inserted",
                id=row["id"],
                camera_id=camera_id,
                cekici_rengi=cekici_rengi,
                dorse_rengi=dorse_rengi,
                guven=round(guven, 2),
            )
            return int(row["id"])

    async def truck_event_exists(self, frigate_event_id: str) -> bool:
        """Aynı tracking ID için truck_events'te kayıt var mı (dedup)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM truck_events
                WHERE metadata->>'frigate_event_id' = $1
                LIMIT 1
                """,
                frigate_event_id,
            )
            return row is not None

    # ---- Door events (M6.5) ----

    async def insert_door_event(
        self,
        zone: str,
        camera_id: str,
        entry_ts: datetime,
        direction: str,
        tracking_id: str | None = None,
        entry_snapshot_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Kapı geçişi (traversal) kaydı aç. ms hassasiyetli entry_ts. ID döndürür.

        exit_ts/duration_ms açılışta boş; alternating session modelinde 2. geçiş
        `close_door_event` ile bunları doldurur (giriş→çıkış eşleştirme).
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO door_events
                    (zone, camera_id, entry_ts, direction, tracking_id,
                     entry_snapshot_path, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                RETURNING id
                """,
                zone,
                camera_id,
                entry_ts,
                direction,
                tracking_id,
                entry_snapshot_path,
                json.dumps(metadata or {}),
            )
            log.info(
                "door_event.inserted",
                id=row["id"],
                zone=zone,
                direction=direction,
                tracking_id=tracking_id,
            )
            return int(row["id"])

    async def close_door_event(
        self,
        door_event_id: int,
        exit_ts: datetime,
        duration_ms: int,
        exit_snapshot_path: str | None = None,
    ) -> None:
        """Açık kapı oturumunu kapat — çıkış zamanı + süre (alternating 2. geçiş)."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE door_events
                SET exit_ts = $2, duration_ms = $3, exit_snapshot_path = $4
                WHERE id = $1
                """,
                door_event_id,
                exit_ts,
                duration_ms,
                exit_snapshot_path,
            )
            log.info(
                "door_event.closed",
                id=door_event_id,
                duration_ms=duration_ms,
            )
