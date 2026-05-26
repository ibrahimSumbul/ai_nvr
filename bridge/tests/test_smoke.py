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
    """Paket import edilebilir olmalı (Docker healthcheck'in kontrol ettiği şey).

    `__version__` artık `importlib.metadata.version("bridge")` ile pyproject.toml'dan
    okunur — manuel sync gerek değil. Bu test sadece format'ı doğrular.
    """
    import bridge

    # Version PEP 440 uyumlu olmalı (M.m.p veya M.m.p+dev gibi)
    assert bridge.__version__
    assert bridge.__version__ != "0.0.0+unknown", (
        "Paket install edilmemiş — `uv sync` veya `pip install -e .` çalıştır"
    )


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
