"""Smoke testleri — paket import + (opsiyonel) integration DB.

Integration testler için:
    docker compose up -d postgres mqtt
    pytest -m integration
"""

from __future__ import annotations

import pytest

from bridge.config import Settings
from bridge.db import Database


def test_bridge_package_imports() -> None:
    """Paket import edilebilir olmalı (Docker healthcheck'in kontrol ettiği şey)."""
    import bridge

    assert bridge.__version__ == "0.1.0"


def test_settings_default_dsn() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert "postgres" in settings.postgres_dsn


@pytest.mark.integration
async def test_database_connect_disconnect() -> None:
    """DB bağlantı havuzu açılır, SELECT 1 çalışır, kapanır."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    db = Database(settings)
    await db.connect()
    async with db.pool.acquire() as conn:
        result = await conn.fetchval("SELECT 1")
    assert result == 1
    await db.close()
