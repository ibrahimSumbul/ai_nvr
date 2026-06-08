"""Bridge servis ana giriş noktası — M2.

M1: MQTT'ye bağlanır, Postgres'i açar, gelen Frigate event'lerini loglar.
M2: zone state machine'e yönlendirir, `first_entry` ve `exit` DB'ye yazılır.
M3: Haiku LLM + Dahua alarm + truck color flow eklenecek.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

from bridge.cameras import CameraMonitor
from bridge.config import Settings, get_settings
from bridge.dahua import (
    DahuaAlarmClient,
    DahuaAlarmError,
    build_dahua_client,
    dahua_inline_worst_case_seconds,
)
from bridge.db import Database
from bridge.disk import DiskMonitor
from bridge.doors import DoorStateMachine
from bridge.events import FrigateEvent
from bridge.llm import build_llm_client
from bridge.mqtt import MqttClient
from bridge.snapshots import SnapshotStore
from bridge.trucks import TruckEventHandler, build_truck_handler
from bridge.zone_config import ZoneConfig, ZonesConfig, load_zones_config
from bridge.zones import ZoneStateMachine

log = structlog.get_logger(__name__)

ZONES_PATH = Path(os.environ.get("AINVR_ZONES_PATH", "/app/config/zones.yaml"))
TICK_INTERVAL_S = 10.0

# Oda (room) ve kapı (door) state machine'leri aynı arayüzü paylaşır
# (on_event/tick/restore_from_db/zone_name) — routing tip'e göre seçer.
StateMachine = ZoneStateMachine | DoorStateMachine


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


def build_state_machines(
    zones_cfg: ZonesConfig,
    db: Database,
    snapshots: SnapshotStore,
    dahua: DahuaAlarmClient | None = None,
) -> dict[str, StateMachine]:
    """Her zone için state machine — tip'e göre room (ZSM) veya door (DSM)."""
    machines: dict[str, StateMachine] = {}
    for z in zones_cfg.zones:
        if z.rules.type == "door":
            machines[z.name] = DoorStateMachine(z, db, snapshots, dahua=dahua)
        else:
            machines[z.name] = ZoneStateMachine(z, db, snapshots, dahua=dahua)
    return machines


def index_by_camera(zones_cfg: ZonesConfig) -> dict[str, list[ZoneConfig]]:
    """`{camera_name: [zone_cfg, ...]}` — event yönlendirme için."""
    by_cam: dict[str, list[ZoneConfig]] = {}
    for z in zones_cfg.zones:
        by_cam.setdefault(z.camera, []).append(z)
    return by_cam


async def run(settings: Settings) -> None:
    """Ana koşum döngüsü."""
    db = Database(settings)
    snapshots = SnapshotStore(frigate_url=settings.frigate_internal_url)
    mqtt = MqttClient(settings)
    llm = build_llm_client(settings)
    dahua = build_dahua_client(settings)  # None → NVR push devre dışı (dev/disabled)
    truck_handler = build_truck_handler(settings, db, snapshots, llm)

    await db.connect()

    zones_cfg = load_zones_config(ZONES_PATH)
    state_machines = build_state_machines(zones_cfg, db, snapshots, dahua)
    cameras_to_zones = index_by_camera(zones_cfg)

    # M7 — kamera offline tespit. Offline → Dahua alarm için kamera→NVR channel
    # eşlemesi zones.yaml dahua_channel'dan türetilir.
    camera_channels = {z.camera: z.rules.dahua_channel for z in zones_cfg.zones}
    camera_monitor = CameraMonitor(settings, db, dahua=dahua, camera_channels=camera_channels)

    # M7 — disk doluluk izleme + snapshot retention budama. Snapshot store'un
    # kök dizininin dosya sistemi izlenir; eşik aşılınca DMSS alarm (kamera
    # offline ile aynı yol). Budama disk'i bizim tarafımızdan hiç doldurmaz.
    disk_monitor = DiskMonitor(settings, db, snapshots.base_dir, dahua=dahua)

    # State recovery
    for zsm in state_machines.values():
        await zsm.restore_from_db()

    log.info(
        "bridge.ready",
        msg="Bridge ready, waiting for events",
        budget_usd=settings.llm_monthly_budget_usd,
        zones=len(state_machines),
        cameras=len(cameras_to_zones),
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_ollama_model if settings.llm_provider == "ollama" else "n/a",
    )

    stop_event = asyncio.Event()

    def _handle_stop() -> None:
        log.info("bridge.stop_signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_stop)

    listener = asyncio.create_task(
        _listen_loop(mqtt, state_machines, cameras_to_zones, truck_handler, stop_event)
    )
    ticker = asyncio.create_task(_tick_loop(state_machines, stop_event))
    camera_task = asyncio.create_task(_camera_monitor_loop(camera_monitor, settings, stop_event))
    tasks = [listener, ticker, camera_task]

    # M7 — disk doluluk + snapshot budama worker
    if settings.disk_monitor_enabled:
        tasks.append(asyncio.create_task(_disk_monitor_loop(disk_monitor, settings, stop_event)))

    # M4 — pending Dahua alarm retry worker (yalnızca alarm aktifse)
    if dahua is not None:
        tasks.append(
            asyncio.create_task(_dahua_retry_loop(dahua, db, zones_cfg, settings, stop_event))
        )

    try:
        await stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await llm.close()
        if dahua is not None:
            await dahua.close()
        await camera_monitor.close()
        await snapshots.close()
        await db.close()
        log.info("bridge.shutdown_complete")


async def _listen_loop(
    mqtt: MqttClient,
    state_machines: dict[str, StateMachine],
    cameras_to_zones: dict[str, list[ZoneConfig]],
    truck_handler: TruckEventHandler,
    stop_event: asyncio.Event,
) -> None:
    """MQTT event akışını state machine'lere ve truck handler'a dağıt."""
    async for message in mqtt.listen("frigate/events"):
        if stop_event.is_set():
            break
        if not message.payload:
            continue
        try:
            payload = json.loads(message.payload)
            event = FrigateEvent.model_validate(payload)
        except (ValueError, TypeError) as exc:
            log.warning(
                "mqtt.parse_failed",
                topic=str(message.topic),
                error=str(exc),
            )
            continue

        # Truck event flow (M3): label == "truck" filter trucks.py içinde
        try:
            await truck_handler.on_event(event)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "truck.handler_failed",
                event_id=event.event_id,
                error=str(exc),
            )

        zones_for_cam = cameras_to_zones.get(event.camera, [])
        if not zones_for_cam:
            log.debug("event.no_zone_match", camera=event.camera)
            continue

        for zone_cfg in zones_for_cam:
            zsm = state_machines.get(zone_cfg.name)
            if zsm is None:
                continue
            try:
                await zsm.on_event(event)
            except Exception as exc:  # noqa: BLE001
                # Bir zone'daki hata diğer zone'ları veya listener'ı durdurmasın.
                log.error(
                    "zone.event_handling_failed",
                    zone=zone_cfg.name,
                    event_id=event.event_id,
                    error=str(exc),
                )


async def _tick_loop(
    state_machines: dict[str, StateMachine],
    stop_event: asyncio.Event,
) -> None:
    """Her zone için periyodik exit kontrolü."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_INTERVAL_S)
            return  # stop_event geldi
        except TimeoutError:
            now = datetime.now(UTC)
            for zsm in state_machines.values():
                try:
                    await zsm.tick(now)
                except Exception as exc:  # noqa: BLE001
                    log.error("zone.tick_failed", zone=zsm.zone_name, error=str(exc))


async def _dahua_retry_loop(
    dahua: DahuaAlarmClient,
    db: Database,
    zones_cfg: ZonesConfig,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    """Pending Dahua alarm'larını periyodik tekrar dener (M4).

    Inline retry'ları tükenmiş (`dahua_alarm_sent=false`, retry<max) first_entry
    olayları DB'den çekilir, NVR'a tekrar gönderilir. Başarı → işaretlenir;
    başarısızlık → retry sayacı artar, max'a ulaşınca düşer (dead-letter manuel).
    """
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.dahua_retry_interval_s)
            return  # stop_event geldi
        except TimeoutError:
            # Claim guard: inline alarm penceresinden daha eski pending'leri al
            # → inline path ile çift-push yarışını önler (subagent review blocker).
            # worst-case backoff exponential olduğu için tam hesaplanır + buffer.
            claim_delay = dahua_inline_worst_case_seconds(settings) + 30.0
            try:
                pending = await db.get_pending_dahua_alarms(
                    settings.dahua_max_retries, older_than_seconds=claim_delay
                )
            except Exception as exc:  # noqa: BLE001
                log.error("dahua.retry_query_failed", error=str(exc))
                continue
            for row in pending:
                zcfg = zones_cfg.by_name(row["zone"])
                channel = zcfg.rules.dahua_channel if zcfg else settings.dahua_alarm_channel
                try:
                    await dahua.trigger_external_alarm(
                        channel=channel,
                        event_type="zone_first_entry_retry",
                        description=f"{row['zone']}: pending alarm retry",
                    )
                except DahuaAlarmError as exc:
                    retries = await db.increment_dahua_retry(row["id"])
                    log.warning(
                        "dahua.retry_failed",
                        zone_event_id=row["id"],
                        zone=row["zone"],
                        retry_count=retries,
                        error=str(exc),
                    )
                    # NVR muhtemelen erişilemiyor — batch'i bloklamadan kalanı
                    # sonraki tick'e bırak (50×worst-case seri bekleme önlenir).
                    break
                await db.mark_dahua_alarm_sent(row["id"])
                log.info("dahua.retry_sent", zone_event_id=row["id"], zone=row["zone"])


async def _camera_monitor_loop(
    monitor: CameraMonitor,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    """Periyodik kamera offline kontrolü (M7) — `camera_check_interval_s`."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.camera_check_interval_s)
            return  # stop_event geldi
        except TimeoutError:
            try:
                await monitor.check()
            except Exception as exc:  # noqa: BLE001
                log.error("camera.check_failed", error=str(exc))


async def _disk_monitor_loop(
    monitor: DiskMonitor,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    """Periyodik disk doluluk + snapshot budama (M7) — `disk_check_interval_s`."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.disk_check_interval_s)
            return  # stop_event geldi
        except TimeoutError:
            try:
                await monitor.check()
            except Exception as exc:  # noqa: BLE001
                log.error("disk.check_failed", error=str(exc))


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log.info("bridge.starting", version="0.2.0")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(settings))


if __name__ == "__main__":
    main()
