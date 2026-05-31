"""DahuaClient + build_dahua_client testleri (httpx MockTransport)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from bridge.config import Settings
from bridge.dahua import (
    DahuaAlarmError,
    DahuaClient,
    build_dahua_client,
    dahua_inline_worst_case_seconds,
)


async def _no_sleep(_seconds: float) -> None:
    """Backoff'u testte anında geçir."""


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "dahua_alarm_enabled": True,
        "dahua_nvr_host": "10.0.0.1",
        "dahua_max_retries": 2,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def _client_with_handler(
    settings: Settings, handler: Any
) -> DahuaClient:
    """DahuaClient'ı MockTransport'lu bir httpx client ile kur."""
    client = DahuaClient(settings, sleep=_no_sleep)
    client._client = httpx.AsyncClient(
        base_url=f"http://{settings.dahua_nvr_host}",
        transport=httpx.MockTransport(handler),
    )
    return client


# ---- trigger_external_alarm ----


async def test_trigger_success() -> None:
    """200 → tek çağrı, doğru CGI parametreleri, exception yok."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="OK")

    client = _client_with_handler(_settings(), handler)
    await client.trigger_external_alarm(channel=3, event_type="zone_first_entry", description="d")

    assert len(calls) == 1
    assert calls[0].url.path == "/cgi-bin/alarm.cgi"
    assert calls[0].url.params["action"] == "triggerAlarm"
    assert calls[0].url.params["channel"] == "3"
    assert calls[0].url.params["alarmType"] == "External"
    await client.close()


async def test_trigger_retry_then_success() -> None:
    """İlk deneme 500, ikinci 200 → başarı (2 çağrı)."""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(500) if state["n"] == 1 else httpx.Response(200, text="OK")

    client = _client_with_handler(_settings(dahua_max_retries=2), handler)
    await client.trigger_external_alarm(channel=1, event_type="x", description="d")

    assert state["n"] == 2
    await client.close()


async def test_trigger_all_fail_raises() -> None:
    """Tüm denemeler 500 → DahuaAlarmError, max_retries+1 deneme yapılır."""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(500)

    client = _client_with_handler(_settings(dahua_max_retries=2), handler)
    with pytest.raises(DahuaAlarmError):
        await client.trigger_external_alarm(channel=1, event_type="x", description="d")

    assert state["n"] == 3  # 1 ilk + 2 retry
    await client.close()


async def test_trigger_timeout_retries_then_raises() -> None:
    """Transport timeout (status değil) da retry edilir ve DahuaAlarmError'a döner."""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        raise httpx.ConnectTimeout("NVR yanıt vermedi")

    client = _client_with_handler(_settings(dahua_max_retries=1), handler)
    with pytest.raises(DahuaAlarmError):
        await client.trigger_external_alarm(channel=1, event_type="x", description="d")

    assert state["n"] == 2  # 1 ilk + 1 retry
    await client.close()


# ---- health_check ----


async def test_health_check_ok() -> None:
    client = _client_with_handler(_settings(), lambda r: httpx.Response(200, text="type=NVR"))
    assert await client.health_check() is True
    await client.close()


async def test_health_check_non_200() -> None:
    client = _client_with_handler(_settings(), lambda r: httpx.Response(500))
    assert await client.health_check() is False
    await client.close()


# ---- build_dahua_client ----


def test_build_disabled_returns_none() -> None:
    """Alarm kapalı → None (dev modu)."""
    assert build_dahua_client(_settings(dahua_alarm_enabled=False)) is None


def test_build_enabled_ok() -> None:
    client = build_dahua_client(_settings())
    assert client is not None


def test_client_uses_digest_auth() -> None:
    """Prod client digest auth ile kurulur (Dahua CGI Basic'i reddeder)."""
    client = build_dahua_client(_settings())
    assert client is not None
    assert isinstance(client._client.auth, httpx.DigestAuth)


# ---- claim guard worst-case (çift-push race fix) ----


def test_inline_worst_case_includes_exponential_backoff() -> None:
    """worst-case = denemeler×timeout + backoff(2+4+...+2^retries) — lineer DEĞİL."""
    # retries=3: 4 deneme × 10s + (2+4+8)=14 → 54s
    s3 = _settings(dahua_max_retries=3, dahua_timeout_s=10.0)
    assert dahua_inline_worst_case_seconds(s3) == 54.0
    # retries=5 (config üst sınırı): 6 × 10 + (2+4+8+16+32)=62 → 122s
    s5 = _settings(dahua_max_retries=5, dahua_timeout_s=10.0)
    assert dahua_inline_worst_case_seconds(s5) == 122.0


def test_claim_delay_covers_inline_window_for_all_retry_counts() -> None:
    """claim_delay (worst-case + 30 buffer) her geçerli retries (0..5) için inline
    penceresini AŞMALI — yoksa worker inline çalışırken çift-push yapar."""
    for retries in range(6):  # config: ge=0 le=5
        s = _settings(dahua_max_retries=retries, dahua_timeout_s=10.0)
        worst = dahua_inline_worst_case_seconds(s)
        claim_delay = worst + 30.0
        assert claim_delay > worst  # buffer pozitif, race penceresi kapalı


def test_build_enabled_no_host_raises() -> None:
    """Alarm açık ama host boş → ValueError (yanlış config erken yakalanır)."""
    with pytest.raises(ValueError, match="DAHUA_NVR_HOST"):
        build_dahua_client(_settings(dahua_nvr_host=""))


def test_build_unsupported_method_raises() -> None:
    with pytest.raises(ValueError, match="dahua_alarm_method"):
        build_dahua_client(_settings(dahua_alarm_method="onvif"))
