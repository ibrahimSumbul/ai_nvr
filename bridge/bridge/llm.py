"""LLM istemcisi — Ollama (M3 birincil), Anthropic Haiku fallback (gelecek).

Bridge doğrudan LLM provider'a HTTP çağrısı yapar (Frigate genAI yerine).
Bu sayede:
- Structured JSON output (Pydantic schema validation)
- llm_usage tablosuna her çağrı için cost/latency log
- Provider-agnostic — `.env` `LLM_PROVIDER` ile değiştirilebilir
- Retry + timeout + structured error handling

M3 hedefi: Truck color analizi (çekici + dorse + tip).
M3+: Anomali doğrulama, M8'de yetkisiz alan tespiti.

docs/06-llm-strategy.md tasarımı (Ollama'ya revize edildi).
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field

from bridge.config import Settings

log = structlog.get_logger(__name__)


# ---- Pydantic output şemaları ----

Color = Literal[
    "beyaz",
    "siyah",
    "gri",
    "kirmizi",
    "mavi",
    "yesil",
    "sari",
    "turuncu",
    "kahverengi",
    "mor",
    "pembe",
    "lacivert",
    "krem",
    "bordo",
    "metalik",
    "bilinmeyen",
]
TrailerType = Literal[
    "tenteli",
    "frigo",
    "konteyner",
    "acik",
    "tanker",
    "bilinmeyen",
]
Direction = Literal["giris", "cikis", "duruyor", "bilinmeyen"]


class TruckAnalysis(BaseModel):
    """Tır renk + dorse analiz sonucu."""

    model_config = ConfigDict(extra="ignore")

    tir_var_mi: bool
    cekici_rengi: Color | None = None
    dorse_var_mi: bool
    dorse_rengi: Color | None = None
    dorse_tipi: TrailerType | None = None
    yon: Direction | None = None
    guven: float = Field(ge=0.0, le=1.0)
    notlar: str | None = None


# ---- LLM çağrı sonucu (kullanım metadata'sı ile) ----


class LLMResult(BaseModel):
    """LLM çağrısının full sonucu — Pydantic parse + usage metadata."""

    parsed: TruckAnalysis  # M3'te sadece truck; ileride union eklenir
    raw_response: str
    model: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0  # Anthropic için; Ollama'da 0
    cost_usd: float = 0.0  # Ollama'da 0 (electric); Anthropic'te hesaplanır


# ---- Provider interface ----


class LLMClient(Protocol):
    """Provider-agnostic LLM istemcisi."""

    async def analyze_truck(self, image_path: Path) -> LLMResult:
        """Görüntüdeki tır + dorse renk + tip analizi."""
        ...

    async def close(self) -> None:
        """HTTP client kapatma."""
        ...


# ---- Ollama implementation ----


TRUCK_PROMPT_SYSTEM = """Sen bir araç görüntü analiz asistanısın. Sana endüstriyel tesise giren bir kamyonun görüntüsü verilecek. Aşağıdakileri tespit edip JSON döndüreceksin.

ÖNEMLİ:
- Sadece JSON döndür, başka açıklama yapma.
- Plaka okumaya çalışma, sadece renk ve genel bilgi.
- Emin değilsen "guven" alanını düşür ve renk için "bilinmeyen" kullan.
- Renk listesi: beyaz, siyah, gri, kirmizi, mavi, yesil, sari, turuncu, kahverengi, mor, pembe, lacivert, krem, bordo, metalik, bilinmeyen

Şema:
{
  "tir_var_mi": boolean,
  "cekici_rengi": <renk> | null,
  "dorse_var_mi": boolean,
  "dorse_rengi": <renk> | null,
  "dorse_tipi": "tenteli" | "frigo" | "konteyner" | "acik" | "tanker" | "bilinmeyen" | null,
  "yon": "giris" | "cikis" | "duruyor" | "bilinmeyen" | null,
  "guven": float (0.0-1.0),
  "notlar": string | null
}"""


class OllamaClient:
    """Ollama vision model client. POST /api/generate, format=json structured output."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.llm_ollama_url,
            timeout=httpx.Timeout(settings.llm_timeout_s),
        )

    async def analyze_truck(self, image_path: Path) -> LLMResult:
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload: dict[str, Any] = {
            "model": self._settings.llm_ollama_model,
            "prompt": "Bu kamyonu analiz et ve JSON döndür.",
            "system": TRUCK_PROMPT_SYSTEM,
            "images": [image_b64],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,  # düşük → tutarlı sonuçlar
                "num_predict": 512,
            },
        }

        start = time.monotonic()
        last_error: Exception | None = None
        for attempt in range(self._settings.llm_max_retries + 1):
            try:
                response = await self._client.post("/api/generate", json=payload)
                response.raise_for_status()
                data = response.json()
                latency_ms = int((time.monotonic() - start) * 1000)
                raw = data.get("response", "")
                parsed = TruckAnalysis.model_validate_json(raw)
                return LLMResult(
                    parsed=parsed,
                    raw_response=raw,
                    model=self._settings.llm_ollama_model,
                    latency_ms=latency_ms,
                    input_tokens=int(data.get("prompt_eval_count", 0)),
                    output_tokens=int(data.get("eval_count", 0)),
                )
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                log.warning(
                    "llm.attempt_failed",
                    attempt=attempt + 1,
                    max_attempts=self._settings.llm_max_retries + 1,
                    error=str(exc),
                )

        assert last_error is not None
        raise LLMError(f"Ollama analyze_truck başarısız: {last_error}") from last_error

    async def close(self) -> None:
        await self._client.aclose()


class LLMError(Exception):
    """LLM çağrısı tüm retry'lardan sonra başarısız."""


# ---- Factory ----


def build_llm_client(settings: Settings) -> LLMClient:
    """Settings.llm_provider'a göre uygun client'ı döndür."""
    if settings.llm_provider == "ollama":
        return OllamaClient(settings)
    raise ValueError(
        f"Desteklenmeyen LLM provider: {settings.llm_provider!r} "
        "(şu an sadece 'ollama' destekleniyor; 'anthropic' gelecekte)"
    )
