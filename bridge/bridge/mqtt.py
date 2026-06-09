"""MQTT istemcisi — Frigate event'lerini dinler."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

import aiomqtt
import structlog

from bridge.config import Settings

log = structlog.get_logger(__name__)


class MqttClient:
    """Frigate event subscription sarmalayıcısı — otomatik reconnect ile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def listen(
        self, topics: str | Sequence[str] = "frigate/#"
    ) -> AsyncIterator[aiomqtt.Message]:
        """MQTT'ye bağlan ve topic('ler)e abone ol — message stream döndür.

        Tek bağlantı/identifier üzerinden birden çok topic'e abone olunur (örn.
        `frigate/events` + `frigate/available`); çağıran `message.topic` ile yönlendirir.
        Bağlantı kopunca exponential backoff ile yeniden dener (1s → 30s).
        """
        topic_list = [topics] if isinstance(topics, str) else list(topics)
        log.info(
            "mqtt.connecting",
            host=self._settings.mqtt_host,
            port=self._settings.mqtt_port,
            topics=topic_list,
        )
        retry_delay = 1
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self._settings.mqtt_host,
                    port=self._settings.mqtt_port,
                    username=self._settings.mqtt_user or None,
                    password=self._settings.mqtt_password or None,
                    identifier="ainvr-bridge",
                ) as client:
                    log.info("mqtt.connected", topics=topic_list)
                    retry_delay = 1
                    for t in topic_list:
                        await client.subscribe(t)
                    async for message in client.messages:
                        yield message
            except aiomqtt.MqttError as exc:
                log.warning("mqtt.disconnected", error=str(exc), retry_in=retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)
