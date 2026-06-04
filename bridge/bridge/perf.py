"""M5 performans test harness — stack ayaktayken CPU/RAM/gecikme örnekler.

Frigate `/api/stats` (host-facing port) + `docker stats` belirli bir süre boyunca
periyodik çekilir; sonunda M5 kabul kriterlerine göre pass/fail raporu üretir:

  - RAM stabil       → container bellek büyümesi eşik altında (sızıntı yok)
  - CPU başı boş     → Frigate detector inference gecikmesi eşik altında
                       (CPU doyunca inference_speed fırlar → Coral USB sinyali, M6)
  - Kaçan olay <%5   → kamera skipped_fps / camera_fps oranı eşik altında
                       (CPU yetişemeyince frame atlanır → kaçan tespit)

Zaman serisi CSV + özet JSON yazar, stdout'a tablo basar ve pass/fail'e göre exit
code döner (0 geçti / 1 kaldı) — 24 saatlik koşum ve CI/cron için uygun.

Host'ta, stack up iken çalıştır (bkz. Makefile `perf` + docs/08-operations.md):

    make perf
    cd bridge && uv run python -m bridge.perf --duration 86400 --interval 30 --out perf-24h

Not: harness HOST'ta koşar (docker stats için). Frigate'e `--frigate-url` ile
host port'undan erişir; default http://localhost:5100 (compose `5100:5000` —
host 5000 macOS'te AirPlay Receiver'da çakışır). `/api/stats` Frigate'in auth'suz
internal API'sidir (CameraMonitor da böyle çağırır). Erişilemezse Frigate
metrikleri atlanır, docker stats (CPU/RAM) yine toplanır — kısmi veriyle çalışır.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess  # noqa: S404 — host docker CLI; shell=False, sabit argv
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Örnek modeli (tek poll turunun ham metrikleri)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CameraSample:
    """Tek kamera için tek örnek (Frigate stats)."""

    name: str
    camera_fps: float  # decode hızı — stream sağlığı
    detection_fps: float  # tespit çalıştırma hızı
    process_fps: float  # işlenen frame hızı
    skipped_fps: float  # CPU yetişemeyip atlanan frame — kaçan olay riski

    @property
    def skipped_ratio(self) -> float:
        """Atlanan frame oranı = skipped / decode. M5 'kaçan olay <%5' metriği."""
        return self.skipped_fps / self.camera_fps if self.camera_fps > 0 else 0.0


@dataclass(frozen=True)
class DetectorSample:
    """Tek detector için tek örnek — inference gecikmesi CPU doygunluk sinyali."""

    name: str
    inference_speed_ms: float


@dataclass(frozen=True)
class ContainerSample:
    """Tek container için tek örnek (docker stats)."""

    name: str
    cpu_pct: float  # docker CPUPerc — çok çekirdekte %100 aşabilir
    mem_used_mb: float
    mem_limit_mb: float


@dataclass(frozen=True)
class Sample:
    """Tek poll turu: tüm kameralar + detector'lar + container'lar."""

    ts: datetime
    cameras: tuple[CameraSample, ...]
    detectors: tuple[DetectorSample, ...]
    containers: tuple[ContainerSample, ...]


# --------------------------------------------------------------------------- #
# Saf parse fonksiyonları (IO'suz — birim test edilebilir)
# --------------------------------------------------------------------------- #


def _as_float(value: Any) -> float:
    """None/eksik/str güvenli float; parse edilemezse 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_frigate_stats(
    data: dict[str, Any],
) -> tuple[tuple[CameraSample, ...], tuple[DetectorSample, ...]]:
    """Frigate `/api/stats` JSON → kamera + detector örnekleri.

    cameras.py ile aynı dayanıklılık: 0.14+ `cameras` wrapper'ı veya top-level;
    `camera_fps`'siz key'ler (service/detectors/...) atlanır; None → 0.
    """
    cameras_raw: dict[str, Any] = data.get("cameras", data)
    cameras: list[CameraSample] = []
    for name, cam in cameras_raw.items():
        if not isinstance(cam, dict) or "camera_fps" not in cam:
            continue
        cameras.append(
            CameraSample(
                name=name,
                camera_fps=_as_float(cam.get("camera_fps")),
                detection_fps=_as_float(cam.get("detection_fps")),
                process_fps=_as_float(cam.get("process_fps")),
                skipped_fps=_as_float(cam.get("skipped_fps")),
            )
        )

    detectors_raw: Any = data.get("detectors", {})
    detectors: list[DetectorSample] = []
    if isinstance(detectors_raw, dict):
        for name, det in detectors_raw.items():
            if not isinstance(det, dict):
                continue
            detectors.append(
                DetectorSample(
                    name=name,
                    inference_speed_ms=_as_float(det.get("inference_speed")),
                )
            )

    return tuple(cameras), tuple(detectors)


# docker stats birim → MB (MiB tabanlı). Binary (MiB/GiB) ve SI (MB/GB) desteklenir.
_UNIT_TO_MB: dict[str, float] = {
    "B": 1.0 / (1024 * 1024),
    "KIB": 1.0 / 1024,
    "MIB": 1.0,
    "GIB": 1024.0,
    "TIB": 1024.0 * 1024,
    "KB": 1000.0 / (1024 * 1024),
    "MB": (1000.0 * 1000) / (1024 * 1024),
    "GB": (1000.0 * 1000 * 1000) / (1024 * 1024),
}


def _parse_mem_to_mb(text: str) -> float:
    """'240.5MiB' / '7.654GiB' / '512MB' → MB (MiB tabanlı). Parse edilemezse 0."""
    num = ""
    unit = ""
    for ch in text:
        if ch.isdigit() or ch == ".":
            num += ch
        else:
            unit += ch
    factor = _UNIT_TO_MB.get(unit.strip().upper())
    if factor is None or not num:
        return 0.0
    try:
        return float(num) * factor
    except ValueError:
        return 0.0


def _parse_cpu_pct(text: str) -> float:
    """'12.34%' → 12.34."""
    return _as_float(text.strip().rstrip("%"))


def parse_docker_stats(payload: str) -> tuple[ContainerSample, ...]:
    """`docker stats --no-stream --format '{{json .}}'` çıktısı → container örnekleri.

    Her satır bir JSON nesnesi; boş/parse edilemeyen satırlar atlanır.
    """
    containers: list[ContainerSample] = []
    for raw in payload.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            row: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = str(row.get("Name", "")).strip()
        if not name:
            continue
        used_text, _, limit_text = str(row.get("MemUsage", "")).partition("/")
        containers.append(
            ContainerSample(
                name=name,
                cpu_pct=_parse_cpu_pct(str(row.get("CPUPerc", "0%"))),
                mem_used_mb=_parse_mem_to_mb(used_text),
                mem_limit_mb=_parse_mem_to_mb(limit_text),
            )
        )
    return tuple(containers)


# --------------------------------------------------------------------------- #
# Özetleme (saf — istatistik aggregasyonu)
# --------------------------------------------------------------------------- #


def percentile(values: Sequence[float], pct: float) -> float:
    """Basit en-yakın-sıra yüzdelik (numpy'sız). `pct` 0..1. Boşsa 0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = round((len(ordered) - 1) * pct)
    return ordered[k]


@dataclass(frozen=True)
class Stat:
    """Bir metrik akışının özeti."""

    count: int
    min: float
    max: float
    mean: float
    p95: float

    @classmethod
    def of(cls, values: Sequence[float]) -> Stat:
        if not values:
            return cls(0, 0.0, 0.0, 0.0, 0.0)
        return cls(
            count=len(values),
            min=min(values),
            max=max(values),
            mean=sum(values) / len(values),
            p95=percentile(values, 0.95),
        )


@dataclass(frozen=True)
class ContainerReport:
    name: str
    cpu: Stat
    mem_mb: Stat
    mem_growth_pct: float  # doğrusal eğim-tabanlı büyüme % (sızıntı sinyali; bkz _growth_pct)


@dataclass(frozen=True)
class CameraReport:
    name: str
    camera_fps: Stat
    skipped_ratio: Stat  # 0..1


@dataclass(frozen=True)
class DetectorReport:
    name: str
    inference_ms: Stat


@dataclass(frozen=True)
class PerfReport:
    samples: int
    duration_s: float
    containers: tuple[ContainerReport, ...]
    cameras: tuple[CameraReport, ...]
    detectors: tuple[DetectorReport, ...]


def _growth_pct(series: Sequence[float]) -> float:
    """Bellek büyüme yüzdesi — en küçük kareler doğrusal eğimi ile (sızıntı sinyali).

    Önceki ilk/son %10 pencere ortalaması bir lineer rampayı içe çekip OLDUĞUNDAN
    AZ raporluyordu (24s yavaş sızıntı eşiğin altında "stabil" görünebilirdi —
    harness'in asıl amacında kör nokta). Bunun yerine mem(t)'ye doğru fit edilir;
    tüm koşum boyunca öngörülen yükseliş (slope*(n-1)) fit baz değerine (intercept)
    oranlanır → rampayı tam yakalar, tek GC dip'inden de daha az etkilenir.
    """
    n = len(series)
    if n < 2:
        return 0.0
    xs = range(n)
    sx = sum(xs)
    sy = sum(series)
    sxx = sum(i * i for i in xs)
    sxy = sum(i * v for i, v in zip(xs, series, strict=True))
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n  # x=0'daki fit baz değeri
    if intercept <= 0:
        return 0.0
    return 100.0 * (slope * (n - 1)) / intercept


def summarize(samples: Sequence[Sample]) -> PerfReport:
    """Örnek serisini metrik bazında özetle (container/kamera/detector)."""
    duration = 0.0
    if len(samples) >= 2:
        duration = (samples[-1].ts - samples[0].ts).total_seconds()

    cpu_series: dict[str, list[float]] = {}
    mem_series: dict[str, list[float]] = {}
    for s in samples:
        for c in s.containers:
            cpu_series.setdefault(c.name, []).append(c.cpu_pct)
            mem_series.setdefault(c.name, []).append(c.mem_used_mb)
    containers = tuple(
        ContainerReport(
            name=name,
            cpu=Stat.of(cpu_series[name]),
            mem_mb=Stat.of(mem_series[name]),
            mem_growth_pct=_growth_pct(mem_series[name]),
        )
        for name in sorted(cpu_series)
    )

    fps_series: dict[str, list[float]] = {}
    skip_series: dict[str, list[float]] = {}
    for s in samples:
        for cam in s.cameras:
            fps_series.setdefault(cam.name, []).append(cam.camera_fps)
            skip_series.setdefault(cam.name, []).append(cam.skipped_ratio)
    cameras = tuple(
        CameraReport(
            name=name,
            camera_fps=Stat.of(fps_series[name]),
            skipped_ratio=Stat.of(skip_series[name]),
        )
        for name in sorted(fps_series)
    )

    inf_series: dict[str, list[float]] = {}
    for s in samples:
        for det in s.detectors:
            inf_series.setdefault(det.name, []).append(det.inference_speed_ms)
    detectors = tuple(
        DetectorReport(name=name, inference_ms=Stat.of(inf_series[name]))
        for name in sorted(inf_series)
    )

    return PerfReport(
        samples=len(samples),
        duration_s=duration,
        containers=containers,
        cameras=cameras,
        detectors=detectors,
    )


# --------------------------------------------------------------------------- #
# Değerlendirme (M5 eşikleri → pass/fail)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Thresholds:
    """M5 pass/fail eşikleri (CLI ile override edilir)."""

    max_mem_growth_pct: float = 20.0  # RAM stabil: container bellek büyümesi
    max_inference_ms: float = 200.0  # CPU başı boş: detector p95 inference
    max_skipped_ratio: float = 0.05  # kaçan olay <%5: skipped/decode p95


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Verdict:
    passed: bool
    checks: tuple[CheckResult, ...]


def evaluate(report: PerfReport, thresholds: Thresholds) -> Verdict:
    """Raporu M5 eşiklerine göre değerlendir → 3 check + genel sonuç."""
    checks: list[CheckResult] = []

    # 1) RAM stabil — hiçbir container eşik üstü büyümemeli
    if report.containers:
        worst_c = max(report.containers, key=lambda c: c.mem_growth_pct)
        growth, gname = worst_c.mem_growth_pct, worst_c.name
    else:
        growth, gname = 0.0, "-"
    checks.append(
        CheckResult(
            name="RAM stabil",
            passed=growth <= thresholds.max_mem_growth_pct,
            detail=(
                f"en yüksek bellek büyümesi {growth:+.1f}% ({gname}), "
                f"eşik {thresholds.max_mem_growth_pct:.0f}%"
            ),
        )
    )

    # 2) CPU başı boş — detector p95 inference eşik altında
    worst_inf = max((d.inference_ms.p95 for d in report.detectors), default=0.0)
    checks.append(
        CheckResult(
            name="CPU başı boş",
            passed=worst_inf <= thresholds.max_inference_ms,
            detail=f"detector p95 inference {worst_inf:.0f}ms, eşik {thresholds.max_inference_ms:.0f}ms",
        )
    )

    # 3) Kaçan olay <%5 — kamera p95 atlanan-frame oranı eşik altında
    if report.cameras:
        worst_cam = max(report.cameras, key=lambda c: c.skipped_ratio.p95)
        skip, sname = worst_cam.skipped_ratio.p95, worst_cam.name
    else:
        skip, sname = 0.0, "-"
    checks.append(
        CheckResult(
            name="Kaçan olay <%5",
            passed=skip <= thresholds.max_skipped_ratio,
            detail=(
                f"en yüksek p95 atlanan-frame oranı {skip * 100:.1f}% ({sname}), "
                f"eşik {thresholds.max_skipped_ratio * 100:.0f}%"
            ),
        )
    )

    return Verdict(passed=all(c.passed for c in checks), checks=tuple(checks))


# --------------------------------------------------------------------------- #
# IO katmanı (Frigate stats + docker stats toplama)
# --------------------------------------------------------------------------- #


async def fetch_frigate_stats(client: httpx.AsyncClient) -> dict[str, Any] | None:
    """Frigate `/api/stats` çek; erişilemez/auth-blocked ise None (docker yine toplanır)."""
    try:
        resp = await client.get("/api/stats")
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("perf.frigate_unreachable", error=str(exc))
        return None


def _docker_stats_raw() -> str:
    """`docker stats --no-stream --format {{json .}}` — host docker CLI (senkron)."""
    try:
        result = subprocess.run(  # noqa: S603 — sabit argv, shell yok
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("perf.docker_stats_failed", error=str(exc))
        return ""
    if result.returncode != 0:
        log.warning("perf.docker_stats_nonzero", code=result.returncode)
        return ""
    return result.stdout


async def fetch_docker_stats() -> tuple[ContainerSample, ...]:
    """docker stats'ı thread'de çalıştır (event loop'u bloklamadan) ve parse et."""
    raw = await asyncio.to_thread(_docker_stats_raw)
    return parse_docker_stats(raw)


async def collect_sample(
    client: httpx.AsyncClient,
    clock: Callable[[], datetime],
    docker_fetch: Callable[[], Awaitable[tuple[ContainerSample, ...]]] = fetch_docker_stats,
) -> Sample:
    """Bir örnek: Frigate stats + docker stats topla → Sample."""
    stats_data = await fetch_frigate_stats(client)
    containers = await docker_fetch()
    cameras: tuple[CameraSample, ...] = ()
    detectors: tuple[DetectorSample, ...] = ()
    if stats_data is not None:
        cameras, detectors = parse_frigate_stats(stats_data)
    return Sample(ts=clock(), cameras=cameras, detectors=detectors, containers=containers)


async def sample_loop(
    client: httpx.AsyncClient,
    *,
    duration: float,
    interval: float,
    clock: Callable[[], datetime] = _utcnow,
    docker_fetch: Callable[[], Awaitable[tuple[ContainerSample, ...]]] = fetch_docker_stats,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[Sample]:
    """`duration` saniye boyunca `interval` aralıkla örnek topla (en az 1 örnek)."""
    samples: list[Sample] = []
    start = monotonic()
    while True:
        samples.append(await collect_sample(client, clock, docker_fetch))
        log.info("perf.sample", n=len(samples))
        elapsed = monotonic() - start
        if elapsed >= duration:
            break
        await sleep(min(interval, max(0.0, duration - elapsed)))
    return samples


# --------------------------------------------------------------------------- #
# Çıktı (CSV zaman serisi + JSON özet + stdout tablosu)
# --------------------------------------------------------------------------- #


def samples_to_csv_rows(samples: Sequence[Sample]) -> list[str]:
    """Long-format CSV: timestamp,kind,name,metric,value (Grafana/plot dostu)."""
    rows = ["timestamp,kind,name,metric,value"]
    for s in samples:
        ts = s.ts.isoformat()
        for c in s.containers:
            rows.append(f"{ts},container,{c.name},cpu_pct,{c.cpu_pct:.2f}")
            rows.append(f"{ts},container,{c.name},mem_mb,{c.mem_used_mb:.1f}")
        for cam in s.cameras:
            rows.append(f"{ts},camera,{cam.name},camera_fps,{cam.camera_fps:.2f}")
            rows.append(f"{ts},camera,{cam.name},skipped_ratio,{cam.skipped_ratio:.4f}")
        for det in s.detectors:
            rows.append(f"{ts},detector,{det.name},inference_ms,{det.inference_speed_ms:.2f}")
    return rows


def report_to_dict(report: PerfReport, verdict: Verdict) -> dict[str, Any]:
    """Özet raporu JSON-serileştirilebilir dict'e çevir."""

    def stat(s: Stat) -> dict[str, float]:
        return {"count": s.count, "min": s.min, "max": s.max, "mean": s.mean, "p95": s.p95}

    return {
        "samples": report.samples,
        "duration_s": report.duration_s,
        "passed": verdict.passed,
        "checks": [
            {"name": c.name, "passed": c.passed, "detail": c.detail} for c in verdict.checks
        ],
        "containers": [
            {
                "name": c.name,
                "cpu_pct": stat(c.cpu),
                "mem_mb": stat(c.mem_mb),
                "mem_growth_pct": c.mem_growth_pct,
            }
            for c in report.containers
        ],
        "cameras": [
            {
                "name": c.name,
                "camera_fps": stat(c.camera_fps),
                "skipped_ratio": stat(c.skipped_ratio),
            }
            for c in report.cameras
        ],
        "detectors": [
            {"name": d.name, "inference_ms": stat(d.inference_ms)} for d in report.detectors
        ],
    }


def _write_outputs(
    out_prefix: str, samples: Sequence[Sample], report: PerfReport, verdict: Verdict
) -> None:
    csv_path = Path(f"{out_prefix}.csv")
    json_path = Path(f"{out_prefix}.json")
    csv_path.write_text("\n".join(samples_to_csv_rows(samples)) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(report_to_dict(report, verdict), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    log.info("perf.written", csv=str(csv_path), json=str(json_path))


def format_summary(report: PerfReport, verdict: Verdict) -> str:
    """stdout için insan-okunur özet tablosu."""
    lines: list[str] = [f"Perf testi: {report.samples} örnek, {report.duration_s:.0f}s", ""]
    if report.containers:
        lines.append("Container          CPU% ort/maks    RAM MB ort/maks    Büyüme")
        for cont in report.containers:
            lines.append(
                f"  {cont.name:<16} {cont.cpu.mean:6.1f}/{cont.cpu.max:<6.1f}  "
                f"{cont.mem_mb.mean:7.0f}/{cont.mem_mb.max:<7.0f}  {cont.mem_growth_pct:+.1f}%"
            )
        lines.append("")
    if report.detectors:
        lines.append("Detector           inference ms ort/p95/maks")
        for d in report.detectors:
            lines.append(
                f"  {d.name:<16} {d.inference_ms.mean:6.1f}/{d.inference_ms.p95:6.1f}/{d.inference_ms.max:.1f}"
            )
        lines.append("")
    if report.cameras:
        lines.append("Kamera             fps min/ort    atlanan% ort/p95")
        for cam in report.cameras:
            lines.append(
                f"  {cam.name:<16} {cam.camera_fps.min:4.1f}/{cam.camera_fps.mean:<4.1f}   "
                f"{cam.skipped_ratio.mean * 100:4.1f}/{cam.skipped_ratio.p95 * 100:.1f}"
            )
        lines.append("")
    lines.append("Sonuç:")
    for chk in verdict.checks:
        lines.append(f"  {'✓' if chk.passed else '✗'} {chk.name}: {chk.detail}")
    lines.append("")
    lines.append("GEÇTİ ✅" if verdict.passed else "KALDI ❌")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="bridge.perf", description="M5 performans test harness")
    p.add_argument(
        "--duration", type=float, default=60.0, help="toplam koşum süresi sn (default 60)"
    )
    p.add_argument("--interval", type=float, default=5.0, help="örnekleme aralığı sn (default 5)")
    p.add_argument(
        "--frigate-url",
        default="http://localhost:5100",
        help="host-facing Frigate URL (compose 5100:5000)",
    )
    p.add_argument("--out", default="perf-report", help="çıktı dosya öneki (.csv/.json)")
    p.add_argument(
        "--max-mem-growth", type=float, default=20.0, help="RAM büyüme eşiği yüzde (default 20)"
    )
    p.add_argument(
        "--max-inference",
        type=float,
        default=200.0,
        help="detector p95 inference eşiği ms (default 200)",
    )
    p.add_argument(
        "--max-skipped",
        type=float,
        default=0.05,
        help="atlanan-frame oran eşiği 0..1 (default 0.05)",
    )
    return p.parse_args(argv)


async def run(
    args: argparse.Namespace,
    *,
    clock: Callable[[], datetime] = _utcnow,
    client: httpx.AsyncClient | None = None,
    docker_fetch: Callable[[], Awaitable[tuple[ContainerSample, ...]]] = fetch_docker_stats,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Örnekle → özetle → değerlendir → yaz → exit code (0 geçti / 1 kaldı)."""
    thresholds = Thresholds(
        max_mem_growth_pct=args.max_mem_growth,
        max_inference_ms=args.max_inference,
        max_skipped_ratio=args.max_skipped,
    )
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(base_url=args.frigate_url, timeout=httpx.Timeout(10.0))
    try:
        samples = await sample_loop(
            client,
            duration=args.duration,
            interval=args.interval,
            clock=clock,
            docker_fetch=docker_fetch,
            monotonic=monotonic,
            sleep=sleep,
        )
    finally:
        if owns_client:
            await client.aclose()

    report = summarize(samples)
    verdict = evaluate(report, thresholds)
    _write_outputs(args.out, samples, report, verdict)
    print(format_summary(report, verdict))
    return 0 if verdict.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
