"""TruckEventHandler için testler — label filter, dedup, success, fail path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bridge.config import Settings
from bridge.events import FrigateEvent
from bridge.llm import LLMError, LLMResult, TruckAnalysis
from bridge.trucks import TruckEventHandler

# ---- Mocks ----


class FakeDB:
    def __init__(self) -> None:
        self.llm_usage: list[dict[str, Any]] = []
        self.truck_events: list[dict[str, Any]] = []
        self.existing_ids: set[str] = set()

    async def insert_llm_usage(self, **kwargs: Any) -> int:
        self.llm_usage.append(kwargs)
        return len(self.llm_usage)

    async def insert_truck_event(self, **kwargs: Any) -> int:
        self.truck_events.append(kwargs)
        return len(self.truck_events)

    async def truck_event_exists(self, frigate_event_id: str) -> bool:
        return frigate_event_id in self.existing_ids


class FakeSnapshots:
    def __init__(self, snapshot_returns: Path | None = Path("/tmp/snap.jpg")) -> None:
        self._returns = snapshot_returns
        self.height_calls: list[int | None] = []

    async def fetch_event_snapshot(
        self, event_id: str, height: int | None = None
    ) -> Path | None:
        self.height_calls.append(height)
        return self._returns


class FakeLLM:
    """LLMClient Protocol implementation."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[Path] = []
        self._raises = raises

    async def analyze_truck(self, image_path: Path) -> LLMResult:
        self.calls.append(image_path)
        if self._raises:
            raise self._raises
        return LLMResult(
            parsed=TruckAnalysis(
                tir_var_mi=True,
                cekici_rengi="mavi",
                dorse_var_mi=True,
                dorse_rengi="beyaz",
                dorse_tipi="tenteli",
                yon="giris",
                guven=0.85,
                notlar=None,
            ),
            raw_response='{"tir_var_mi": true}',
            model="qwen2.5vl:7b",
            latency_ms=2500,
            input_tokens=400,
            output_tokens=120,
        )

    async def close(self) -> None:
        pass


def _truck_event(
    event_id: str = "evt-1",
    score: float = 0.85,
    label: str = "truck",
    has_snapshot: bool = True,
) -> FrigateEvent:
    after = {
        "id": event_id,
        "camera": "pilot_kamera",
        "label": label,
        "score": score,
        "frame_time": 0.0,
        "current_zones": [],
        "entered_zones": [],
        "has_snapshot": has_snapshot,
    }
    return FrigateEvent.model_validate({"type": "new", "after": after})


def _settings() -> Settings:
    return Settings(_env_file=None, llm_truck_min_score=0.6)  # type: ignore[call-arg]


# ---- Tests ----


async def test_truck_event_success_path() -> None:
    """Truck event → snapshot + LLM + DB iki tablo insert."""
    settings = _settings()
    db = FakeDB()
    snaps = FakeSnapshots()
    llm = FakeLLM()
    handler = TruckEventHandler(settings, db, snaps, llm)  # type: ignore[arg-type]

    await handler.on_event(_truck_event(event_id="evt-1"))

    assert len(llm.calls) == 1
    assert len(db.llm_usage) == 1
    assert db.llm_usage[0]["call_type"] == "truck_color"
    assert db.llm_usage[0]["success"] is True
    assert db.llm_usage[0]["latency_ms"] == 2500
    assert len(db.truck_events) == 1
    assert db.truck_events[0]["cekici_rengi"] == "mavi"
    assert db.truck_events[0]["dorse_rengi"] == "beyaz"


async def test_snapshot_fetched_with_height_limit() -> None:
    """LLM snapshot'ı settings.llm_snapshot_max_height ile çekilir (latency kontrolü)."""
    settings = _settings()
    db = FakeDB()
    snaps = FakeSnapshots()
    handler = TruckEventHandler(settings, db, snaps, FakeLLM())  # type: ignore[arg-type]

    await handler.on_event(_truck_event(event_id="evt-h"))

    assert snaps.height_calls == [settings.llm_snapshot_max_height]


async def test_non_truck_label_ignored() -> None:
    """person/car/etc → handler atla, LLM çağrılmaz."""
    db = FakeDB()
    llm = FakeLLM()
    handler = TruckEventHandler(
        _settings(),
        db,
        FakeSnapshots(),  # type: ignore[arg-type]
        llm,  # type: ignore[arg-type]
    )

    await handler.on_event(_truck_event(label="person"))
    await handler.on_event(_truck_event(label="car"))

    assert llm.calls == []
    assert db.llm_usage == []
    assert db.truck_events == []


async def test_low_score_skipped() -> None:
    """score < min_score → LLM çağrılmaz."""
    db = FakeDB()
    llm = FakeLLM()
    handler = TruckEventHandler(
        _settings(),
        db,
        FakeSnapshots(),  # type: ignore[arg-type]
        llm,  # type: ignore[arg-type]
    )

    await handler.on_event(_truck_event(score=0.3))

    assert llm.calls == []
    assert db.truck_events == []


async def test_dedup_memory_cache() -> None:
    """Aynı event_id ikinci kez gelirse LLM tekrar çağrılmaz."""
    db = FakeDB()
    llm = FakeLLM()
    handler = TruckEventHandler(
        _settings(),
        db,
        FakeSnapshots(),  # type: ignore[arg-type]
        llm,  # type: ignore[arg-type]
    )

    await handler.on_event(_truck_event(event_id="evt-1"))
    await handler.on_event(_truck_event(event_id="evt-1"))  # tekrar

    assert len(llm.calls) == 1  # sadece bir kez çağrıldı
    assert len(db.truck_events) == 1


async def test_dedup_db_check() -> None:
    """DB'de zaten varsa LLM çağrılmaz."""
    db = FakeDB()
    db.existing_ids.add("evt-existing")
    llm = FakeLLM()
    handler = TruckEventHandler(
        _settings(),
        db,
        FakeSnapshots(),  # type: ignore[arg-type]
        llm,  # type: ignore[arg-type]
    )

    await handler.on_event(_truck_event(event_id="evt-existing"))

    assert llm.calls == []
    assert db.truck_events == []


async def test_no_snapshot_skipped_and_not_deduped() -> None:
    """Snapshot None → LLM çağrılmaz VE dedup'a eklenmez (retry için)."""
    db = FakeDB()
    llm = FakeLLM()
    handler = TruckEventHandler(
        _settings(),
        db,
        FakeSnapshots(snapshot_returns=None),  # type: ignore[arg-type]
        llm,  # type: ignore[arg-type]
    )

    await handler.on_event(_truck_event(event_id="evt-nosnap"))

    assert llm.calls == []
    assert db.truck_events == []
    assert "evt-nosnap" not in handler._processed  # dedup'a EKLENMEDİ → retry mümkün


async def test_has_snapshot_false_skips_no_fetch_no_dedup() -> None:
    """has_snapshot=false → fetch denenmez, dedup'a eklenmez (snapshot hazır değil)."""
    db = FakeDB()
    llm = FakeLLM()
    snaps = FakeSnapshots()
    handler = TruckEventHandler(_settings(), db, snaps, llm)  # type: ignore[arg-type]

    await handler.on_event(_truck_event(event_id="evt-nohs", has_snapshot=False))

    assert llm.calls == []
    assert snaps.height_calls == []  # fetch hiç denenmedi (has_snapshot=false)
    assert "evt-nohs" not in handler._processed


async def test_snapshot_not_ready_then_retried_when_available() -> None:
    """İlk event snapshot'sız → işlenmez; snapshot gelince aynı tır işlenir (tır kaybı yok)."""
    db = FakeDB()
    llm = FakeLLM()
    snaps = FakeSnapshots(snapshot_returns=None)  # önce snapshot yok
    handler = TruckEventHandler(_settings(), db, snaps, llm)  # type: ignore[arg-type]

    # 1. event: snapshot fetch None → işlenmez, dedup'a eklenmez
    await handler.on_event(_truck_event(event_id="evt-1"))
    assert llm.calls == []
    assert "evt-1" not in handler._processed

    # Snapshot artık hazır → aynı tracking_id ikinci event → işlenir
    snaps._returns = Path("/tmp/snap.jpg")
    await handler.on_event(_truck_event(event_id="evt-1"))
    assert len(llm.calls) == 1
    assert len(db.truck_events) == 1
    assert "evt-1" in handler._processed  # artık dedup'lı (tek analiz)


async def test_llm_failure_logged_to_usage() -> None:
    """LLM exception → llm_usage'a success=False, truck_events boş."""
    db = FakeDB()
    llm = FakeLLM(raises=LLMError("Ollama timeout"))
    handler = TruckEventHandler(
        _settings(),
        db,
        FakeSnapshots(),  # type: ignore[arg-type]
        llm,  # type: ignore[arg-type]
    )

    await handler.on_event(_truck_event(event_id="evt-fail"))

    assert len(llm.calls) == 1
    assert len(db.llm_usage) == 1
    assert db.llm_usage[0]["success"] is False
    assert "Ollama timeout" in db.llm_usage[0]["error"]
    assert len(db.truck_events) == 0  # truck event yazılmadı
