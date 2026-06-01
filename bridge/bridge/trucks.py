"""Truck event flow — Frigate "truck" label → snapshot → LLM → DB.

Akış:
1. Frigate event'inde `label == "truck"` ve `score >= llm_truck_min_score`
2. Aynı `frigate_event_id` daha önce işlendi mi? (dedup) → atla
3. Snapshot fetch (mevcut SnapshotStore)
4. LLM analyze_truck (OllamaClient veya hibrit fallback)
5. truck_events + llm_usage insert (atomic değil ama yakın — llm_usage önce)
6. Hata durumunda llm_usage'a `success=False` + `error` yazılır, truck_events boş bırakılır

Dedup memory cache + DB sorgu kombinasyonu — restart sonrası state DB'den geri yüklenir.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import structlog

from bridge.config import Settings
from bridge.db import Database
from bridge.events import FrigateEvent
from bridge.llm import LLMClient, LLMError
from bridge.snapshots import SnapshotStore

log = structlog.get_logger(__name__)


class TruckEventHandler:
    """Frigate truck event'lerini LLM ile zenginleştirip DB'ye yazar."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        snapshots: SnapshotStore,
        llm: LLMClient,
    ) -> None:
        self._settings = settings
        self._db = db
        self._snapshots = snapshots
        self._llm = llm
        self._min_score = settings.llm_truck_min_score
        # Memory dedup — restart'ta DB sorgusu ile çakışmaz
        self._processed: set[str] = set()

    async def on_event(self, event: FrigateEvent) -> None:
        """Frigate event geldiğinde truck flow tetikle."""
        if event.label != "truck":
            return
        if event.score < self._min_score:
            log.debug(
                "truck.skipped_low_score",
                event_id=event.event_id,
                score=event.score,
                threshold=self._min_score,
            )
            return

        # Dedup: memory + DB
        if event.event_id in self._processed:
            return
        if await self._db.truck_event_exists(event.event_id):
            self._processed.add(event.event_id)
            return

        await self._process(event)

    async def _process(self, event: FrigateEvent) -> None:
        # 1. Snapshot fetch — LLM için ZORUNLU girdi (height-sınırlı, latency).
        #
        # Snapshot-gated dedup: Frigate snapshot'ı bir tracking session'ın İLK
        # truck event'inde henüz hazır olmayabilir (`has_snapshot=false`; best
        # frame event ilerledikçe oluşur). Böyle durumda olayı "işlenmiş"
        # SAYMA — `_processed`'e ekleme — ki snapshot hazır olunca sonraki
        # event'te tekrar denensin. Aksi halde ilk event snapshot'sız gelirse
        # tır kalıcı kaybolurdu (dedup'a girip bir daha denenmezdi). Dedup
        # işareti yalnız snapshot başarıyla alındıktan sonra konur → analiz
        # tam bir kez yapılır.
        if not event.after.has_snapshot:
            log.debug("truck.snapshot_not_ready", event_id=event.event_id)
            return
        saved = await self._snapshots.fetch_event_snapshot(
            event.event_id, height=self._settings.llm_snapshot_max_height
        )
        if saved is None:
            log.warning("truck.snapshot_fetch_failed", event_id=event.event_id)
            return
        snapshot_path = str(saved)

        # Snapshot hazır → bu tır artık işlenmiş; sonraki event'ler dedup'a takılır.
        self._processed.add(event.event_id)

        # 2. LLM analiz
        try:
            result = await self._llm.analyze_truck(Path(snapshot_path))
        except LLMError as exc:
            # llm_usage'a fail kaydı yaz, truck_events boş bırak
            await self._db.insert_llm_usage(
                call_type="truck_color",
                model=self._settings.llm_ollama_model,
                input_tokens=0,
                output_tokens=0,
                cached_input_tokens=0,
                cost_usd=0.0,
                latency_ms=0,
                success=False,
                error=str(exc),
                metadata={"frigate_event_id": event.event_id},
            )
            log.error("truck.llm_failed", event_id=event.event_id, error=str(exc))
            return

        now = datetime.now(UTC)

        # 3. llm_usage insert (önce — truck_events FK referans alır)
        llm_usage_id = await self._db.insert_llm_usage(
            call_type="truck_color",
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cached_input_tokens=result.cached_input_tokens,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
            success=True,
            metadata={"frigate_event_id": event.event_id},
        )

        # 4. truck_events insert
        await self._db.insert_truck_event(
            camera_id=event.camera,
            ts=now,
            cekici_rengi=result.parsed.cekici_rengi,
            dorse_var_mi=result.parsed.dorse_var_mi,
            dorse_rengi=result.parsed.dorse_rengi,
            dorse_tipi=result.parsed.dorse_tipi,
            yon=result.parsed.yon,
            guven=result.parsed.guven,
            notlar=result.parsed.notlar,
            snapshot_path=snapshot_path,
            llm_usage_id=llm_usage_id,
            frigate_event_id=event.event_id,
        )
        log.info(
            "truck.analyzed",
            event_id=event.event_id,
            cekici=result.parsed.cekici_rengi,
            dorse=result.parsed.dorse_rengi,
            guven=round(result.parsed.guven, 2),
            latency_ms=result.latency_ms,
        )


def build_truck_handler(
    settings: Settings,
    db: Database,
    snapshots: SnapshotStore,
    llm: LLMClient,
) -> TruckEventHandler:
    """TruckEventHandler factory."""
    return TruckEventHandler(settings, db, snapshots, llm)
