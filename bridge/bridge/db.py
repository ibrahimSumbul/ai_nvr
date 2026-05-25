"""Postgres async bağlantı havuzu."""

from __future__ import annotations

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
