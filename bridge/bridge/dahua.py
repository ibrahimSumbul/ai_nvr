"""Dahua NVR external alarm köprüsü (M4).

Bridge'in tetiklediği zone olaylarını orijinal Dahua paneline (DSS/SmartPSS)
"External Alarm" olarak geri besler. Böylece AI olayları mevcut güvenlik
operasyonunun gördüğü panelde belirir (mobil push dahil).

Yöntem (docs/05-dahua-integration.md): Virtual Input CGI —
    GET /cgi-bin/alarm.cgi?action=triggerAlarm&channel=N&alarmType=External
Digest authentication zorunlu (Dahua çoğu CGI'de Basic'i reddeder).

ONVIF (Yöntem 2) ve DSS Pro Custom Event (Yöntem 4) ileride
`dahua_alarm_method` ile eklenebilir; şimdilik virtual_input.

Retry: inline max_retries deneme + exponential backoff (2s, 4s, 8s). Hepsi
başarısızsa DahuaAlarmError → çağıran (zones.py) olayı DB'de pending bırakır,
retry worker (main.py) periyodik tekrar dener.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx
import structlog

from bridge.config import Settings

log = structlog.get_logger(__name__)


class DahuaAlarmError(Exception):
    """Dahua alarm tüm inline retry'lardan sonra başarısız."""


def _backoff_seconds(attempt: int) -> float:
    """Bir deneme sonrası beklenecek backoff (exponential): 2s, 4s, 8s, ..."""
    return 2.0 ** (attempt + 1)


def dahua_inline_worst_case_seconds(settings: Settings) -> float:
    """`trigger_external_alarm` tek çağrısının worst-case toplam süresi (s).

    = (deneme sayısı × timeout) + (denemeler arası backoff toplamı).
    Retry worker'ın claim guard'ı bundan büyük olmalı (çift-push race önlemi);
    backoff exponential olduğu için lineer yaklaşım yetmez (subagent review).
    """
    attempts = settings.dahua_max_retries + 1
    backoff_total = sum(_backoff_seconds(i) for i in range(settings.dahua_max_retries))
    return attempts * settings.dahua_timeout_s + backoff_total


class DahuaAlarmClient(Protocol):
    """Alarm köprüsü arayüzü — provider-agnostic (virtual_input/onvif/dss)."""

    async def trigger_external_alarm(
        self,
        channel: int,
        event_type: str,
        description: str,
        snapshot_path: str | None = None,
    ) -> None: ...

    async def health_check(self) -> bool: ...

    async def close(self) -> None: ...


class DahuaClient:
    """Virtual Input CGI üzerinden Dahua NVR external alarm tetikleyici."""

    def __init__(
        self,
        settings: Settings,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._s = settings
        self._sleep = sleep  # test edilebilirlik (backoff'u hızlandır)
        self._client = httpx.AsyncClient(
            base_url=f"http://{settings.dahua_nvr_host}:{settings.dahua_nvr_port}",
            auth=httpx.DigestAuth(settings.dahua_nvr_user, settings.dahua_nvr_password),
            timeout=httpx.Timeout(settings.dahua_timeout_s),
        )

    async def trigger_external_alarm(
        self,
        channel: int,
        event_type: str,
        description: str,
        snapshot_path: str | None = None,
    ) -> None:
        """NVR'a external alarm event'i gönder. Her çağrıda tetikler (idempotent değil).

        Tüm denemeler başarısızsa DahuaAlarmError raise eder.
        """
        params = {
            "action": "triggerAlarm",
            "channel": str(channel),
            "alarmType": "External",
        }
        last_error: Exception | None = None
        for attempt in range(self._s.dahua_max_retries + 1):
            try:
                response = await self._client.get("/cgi-bin/alarm.cgi", params=params)
                response.raise_for_status()
                log.info(
                    "dahua.alarm_sent",
                    channel=channel,
                    event_type=event_type,
                    description=description,
                    attempt=attempt + 1,
                )
                return
            except httpx.HTTPError as exc:
                last_error = exc
                log.warning(
                    "dahua.alarm_attempt_failed",
                    channel=channel,
                    attempt=attempt + 1,
                    max_attempts=self._s.dahua_max_retries + 1,
                    error=str(exc),
                )
                if attempt < self._s.dahua_max_retries:
                    await self._sleep(_backoff_seconds(attempt))

        raise DahuaAlarmError(
            f"Dahua alarm {self._s.dahua_max_retries + 1} denemede başarısız "
            f"(channel={channel}): {last_error}"
        )

    async def health_check(self) -> bool:
        """NVR erişilebilir mi (getDeviceType ile hafif yoklama)."""
        try:
            response = await self._client.get(
                "/cgi-bin/magicBox.cgi", params={"action": "getDeviceType"}
            )
            return response.status_code == 200
        except httpx.HTTPError as exc:
            log.warning("dahua.health_check_failed", error=str(exc))
            return False

    async def close(self) -> None:
        await self._client.aclose()


def build_dahua_client(settings: Settings) -> DahuaClient | None:
    """Settings'e göre Dahua client kur. Alarm kapalıysa None döner.

    Dev'de `dahua_alarm_enabled=False` → None → zones.py alarm tetiklemeyi atlar
    (alarm_emitted yine DB'ye yazılır, sadece NVR'a push yapılmaz).
    """
    if not settings.dahua_alarm_enabled:
        log.info("dahua.disabled", msg="DAHUA_ALARM_ENABLED=false — NVR push atlanıyor")
        return None
    if settings.dahua_alarm_method != "virtual_input":
        raise ValueError(
            f"Desteklenmeyen dahua_alarm_method: {settings.dahua_alarm_method!r} "
            "(şu an sadece 'virtual_input')"
        )
    if not settings.dahua_nvr_host:
        raise ValueError("DAHUA_ALARM_ENABLED=true ama DAHUA_NVR_HOST boş")
    return DahuaClient(settings)
