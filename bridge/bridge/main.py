"""Bridge servis ana giriş noktası — M1 iskelet.

M1: MQTT'ye bağlanır, Postgres'i açar, gelen Frigate event'lerini loglar.
M2: zone state machine eklenir.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

import structlog

from bridge.config import Settings, get_settings
from bridge.db import Database
from bridge.mqtt import MqttClient

log = structlog.get_logger(__name__)


def configure_logging(level: str) -> None:
    """structlog'u console output için ayarla."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=log_level, stream=sys.stdout)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
    )


async def run(settings: Settings) -> None:
    """Ana koşum döngüsü."""
    db = Database(settings)
    mqtt = MqttClient(settings)

    await db.connect()
    log.info(
        "bridge.ready",
        msg="Bridge ready, waiting for events",
        budget_usd=settings.llm_monthly_budget_usd,
    )

    stop_event = asyncio.Event()

    def _handle_stop() -> None:
        log.info("bridge.stop_signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_stop)

    listener_task = asyncio.create_task(_listen_loop(mqtt, stop_event))

    try:
        await stop_event.wait()
    finally:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
        await db.close()
        log.info("bridge.shutdown_complete")


async def _listen_loop(mqtt: MqttClient, stop_event: asyncio.Event) -> None:
    """MQTT event'lerini dinler — M1'de sadece log atar."""
    async for message in mqtt.listen("frigate/#"):
        if stop_event.is_set():
            break
        log.info(
            "mqtt.message",
            topic=str(message.topic),
            payload_bytes=len(message.payload) if message.payload else 0,
        )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log.info("bridge.starting", version="0.1.0")
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
