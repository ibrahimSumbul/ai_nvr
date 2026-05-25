"""MQTT istemcisi — Frigate event'lerini dinler."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import aiomqtt
import structlog

from bridge.config import Settings

log = structlog.get_logger(__name__)


class MqttClient:
    """Frigate event subscription sarmalayıcısı — otomatik reconnect ile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def listen(self, topic: str = "frigate/#") -> AsyncIterator[aiomqtt.Message]:
        """MQTT'ye bağlan ve topic'e abone ol — message stream döndür.

        Bağlantı kopunca exponential backoff ile yeniden dener (1s → 30s).
        """
        log.info(
            "mqtt.connecting",
            host=self._settings.mqtt_host,
            port=self._settings.mqtt_port,
            topic=topic,
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
                    log.info("mqtt.connected", topic=topic)
                    retry_delay = 1
                    await client.subscribe(topic)
                    async for message in client.messages:
                        yield message
            except aiomqtt.MqttError as exc:
                log.warning("mqtt.disconnected", error=str(exc), retry_in=retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)
