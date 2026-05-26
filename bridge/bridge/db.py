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
