"""Konfigürasyon yönetimi — ortam değişkenlerinden ayarlar."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bridge servisinin tüm ayarları — .env dosyasından yüklenir."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-haiku-4-5-20251001")

    # Postgres
    postgres_user: str = Field(default="ainvr")
    postgres_password: str = Field(default="ainvr")
    postgres_db: str = Field(default="ainvr")
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)

    # MQTT
    mqtt_host: str = Field(default="mqtt")
    mqtt_port: int = Field(default=1883)
    mqtt_user: str = Field(default="ainvr")
    mqtt_password: str = Field(default="ainvr")

    # Frigate (bridge container'ından internal erişim — snapshot fetch için)
    frigate_internal_url: str = Field(default="http://frigate:5000")

    # Dahua
    dahua_nvr_host: str = Field(default="")
    dahua_nvr_user: str = Field(default="admin")
    dahua_nvr_password: str = Field(default="")

    # LLM (M3+). Default Ollama (lokal). Anthropic fallback ileride eklenir.
    llm_provider: str = Field(default="ollama")  # 'ollama' | 'anthropic' (gelecek)
    llm_ollama_url: str = Field(default="http://host.docker.internal:11434")
    llm_ollama_model: str = Field(default="qwen2.5vl:7b")  # .env ile override edilir
    llm_timeout_s: float = Field(default=60.0, ge=5.0, le=300.0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    # Minimum truck label score — Frigate bu altındaysa LLM çağrılmaz
    llm_truck_min_score: float = Field(default=0.6, ge=0.0, le=1.0)

    # LLM bütçe (anthropic kullanırsa)
    llm_monthly_budget_usd: float = Field(default=10.0)

    # SMTP (M6.5+)
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="")
    smtp_to_default: str = Field(default="")

    # Viewer (M6.5+)
    portal_url: str = Field(default="")
    view_token_secret: str = Field(default="change-me")
    view_token_ttl_days: int = Field(default=7)

    # Log
    log_level: str = Field(default="INFO")

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def get_settings() -> Settings:
    return Settings()
