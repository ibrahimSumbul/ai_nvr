"""Settings yükleme smoke testleri."""

from __future__ import annotations

import pytest

from bridge.config import Settings


def test_settings_load_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hiçbir env değişkeni yokken default değerlerle yüklenmeli."""
    for key in [
        "ANTHROPIC_API_KEY",
        "POSTGRES_HOST",
        "MQTT_HOST",
        "LLM_MONTHLY_BUDGET_USD",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.postgres_host == "postgres"
    assert settings.mqtt_host == "mqtt"
    assert settings.llm_monthly_budget_usd == 10.0


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("LLM_MONTHLY_BUDGET_USD", "25")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.postgres_host == "localhost"
    assert settings.llm_monthly_budget_usd == 25.0


def test_postgres_dsn_format() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        postgres_user="u",
        postgres_password="p",
        postgres_host="h",
        postgres_port=5432,
        postgres_db="d",
    )
    assert settings.postgres_dsn == "postgresql://u:p@h:5432/d"
