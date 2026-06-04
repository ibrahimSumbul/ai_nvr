"""perf harness testleri — parse / özet / değerlendir + IO döngüsü (enjekte deps)."""

from __future__ import annotations

import argparse
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from bridge.perf import (
    CameraReport,
    CameraSample,
    ContainerReport,
    ContainerSample,
    DetectorReport,
    DetectorSample,
    PerfReport,
    Sample,
    Stat,
    Thresholds,
    Verdict,
    _growth_pct,
    _parse_mem_to_mb,
    evaluate,
    format_summary,
    parse_docker_stats,
    parse_frigate_stats,
    percentile,
    report_to_dict,
    run,
    sample_loop,
    samples_to_csv_rows,
    summarize,
)

# --------------------------------------------------------------------------- #
# Test yardımcıları
# --------------------------------------------------------------------------- #

T0 = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)


def _client(stats: dict[str, Any]) -> httpx.AsyncClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=stats)

    return httpx.AsyncClient(base_url="http://frigate:5000", transport=httpx.MockTransport(handler))


def _monotonic_seq(values: list[float]) -> Callable[[], float]:
    it = iter(values)

    def _m() -> float:
        return next(it)

    return _m


async def _no_sleep(_seconds: float) -> None:
    return None


def _docker(
    containers: tuple[ContainerSample, ...],
) -> Callable[[], Awaitable[tuple[ContainerSample, ...]]]:
    async def _f() -> tuple[ContainerSample, ...]:
        return containers

    return _f


def _args(out: str, **overrides: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "duration": 0.0,
        "interval": 1.0,
        "frigate_url": "http://frigate:5000",
        "out": out,
        "max_mem_growth": 20.0,
        "max_inference": 200.0,
        "max_skipped": 0.05,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


# --------------------------------------------------------------------------- #
# parse_frigate_stats
# --------------------------------------------------------------------------- #


def test_parse_frigate_stats_cameras_and_detectors() -> None:
    stats = {
        "cameras": {
            "cam_test": {
                "camera_fps": 5.0,
                "detection_fps": 4.8,
                "process_fps": 4.9,
                "skipped_fps": 0.2,
            },
            "cam_off": {"camera_fps": None},
        },
        "detectors": {"cpu1": {"inference_speed": 23.5}},
        "service": {"uptime": 100},  # kamera-olmayan key → atlanmalı
    }
    cams, dets = parse_frigate_stats(stats)

    by_name = {c.name: c for c in cams}
    assert set(by_name) == {"cam_test", "cam_off"}  # service atlandı
    assert by_name["cam_test"].skipped_ratio == pytest.approx(0.04)  # 0.2 / 5.0
    assert by_name["cam_off"].camera_fps == 0.0  # None → 0
    assert by_name["cam_off"].skipped_ratio == 0.0  # fps 0 → bölme yok
    assert len(dets) == 1
    assert dets[0].inference_speed_ms == 23.5


def test_parse_frigate_stats_top_level_fallback() -> None:
    """`cameras` wrapper'ı yoksa top-level; detectors yine ayrı okunur."""
    stats = {"cam_test": {"camera_fps": 5.0}, "detectors": {"cpu1": {"inference_speed": 10.0}}}
    cams, dets = parse_frigate_stats(stats)

    assert [c.name for c in cams] == ["cam_test"]  # detectors kamera değil
    assert [d.name for d in dets] == ["cpu1"]


# --------------------------------------------------------------------------- #
# parse_docker_stats / birim çevirme
# --------------------------------------------------------------------------- #


def test_parse_docker_stats_parses_and_skips_garbage() -> None:
    payload = "\n".join(
        [
            json.dumps(
                {"Name": "ai_nvr-frigate-1", "CPUPerc": "42.50%", "MemUsage": "500.2MiB / 7.654GiB"}
            ),
            json.dumps(
                {"Name": "ai_nvr-bridge-1", "CPUPerc": "3.10%", "MemUsage": "64MiB / 7.654GiB"}
            ),
            "not json at all",
            "",
        ]
    )
    cs = parse_docker_stats(payload)

    assert [c.name for c in cs] == ["ai_nvr-frigate-1", "ai_nvr-bridge-1"]
    assert cs[0].cpu_pct == 42.5
    assert cs[0].mem_used_mb == pytest.approx(500.2)
    assert cs[0].mem_limit_mb == pytest.approx(7.654 * 1024)


def test_parse_docker_stats_empty() -> None:
    assert parse_docker_stats("") == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("240.5MiB", 240.5),
        ("1GiB", 1024.0),
        ("7.654GiB", 7.654 * 1024),
        ("1024KiB", 1.0),
        ("garbage", 0.0),
        ("", 0.0),
    ],
)
def test_parse_mem_to_mb(text: str, expected: float) -> None:
    assert _parse_mem_to_mb(text) == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# percentile / Stat / _growth_pct
# --------------------------------------------------------------------------- #


def test_percentile_and_stat() -> None:
    values = [float(i) for i in range(1, 11)]  # 1..10
    assert percentile(values, 0.95) == 10.0  # round(9*0.95)=9 → ordered[9]
    assert percentile(values, 0.0) == 1.0
    assert percentile([], 0.5) == 0.0

    st = Stat.of(values)
    assert st.count == 10
    assert st.min == 1.0
    assert st.max == 10.0
    assert st.mean == pytest.approx(5.5)


def test_stat_empty() -> None:
    st = Stat.of([])
    assert (st.count, st.min, st.max, st.mean, st.p95) == (0, 0.0, 0.0, 0.0, 0.0)


def test_growth_pct() -> None:
    assert _growth_pct([100.0, 110.0]) == pytest.approx(10.0)
    assert _growth_pct([]) == 0.0
    assert _growth_pct([5.0]) == 0.0  # n<2 → 0
    assert _growth_pct([0.0, 5.0]) == 0.0  # intercept 0 → büyüme tanımsız → 0


def test_growth_pct_linear_leak_not_underreported() -> None:
    """Review bulgusu: lineer sızıntı eşiğin altında görünmemeli.

    100 örnekli 500→600 MB lineer rampa (gerçek %20). Doğrusal eğim bunu TAM
    yakalar (≈%20); eski ilk/son-pencere-ortalaması içe-çekme biasıyla ~%18'e
    düşürüp ≤%20 eşiğini yanlışlıkla geçirebiliyordu.
    """
    n = 100
    ramp = [500.0 + 100.0 * i / (n - 1) for i in range(n)]
    assert _growth_pct(ramp) == pytest.approx(20.0, abs=0.3)


# --------------------------------------------------------------------------- #
# summarize
# --------------------------------------------------------------------------- #


def test_summarize_aggregates_streams() -> None:
    s1 = Sample(
        ts=T0,
        cameras=(CameraSample("cam", 5.0, 5.0, 5.0, 0.1),),
        detectors=(DetectorSample("d", 20.0),),
        containers=(ContainerSample("frigate", 40.0, 500.0, 8000.0),),
    )
    s2 = Sample(
        ts=T0 + timedelta(seconds=10),
        cameras=(CameraSample("cam", 5.0, 5.0, 5.0, 0.5),),
        detectors=(DetectorSample("d", 30.0),),
        containers=(ContainerSample("frigate", 60.0, 600.0, 8000.0),),
    )
    report = summarize([s1, s2])

    assert report.samples == 2
    assert report.duration_s == 10.0
    (cont,) = report.containers
    assert cont.cpu.mean == pytest.approx(50.0)
    assert cont.mem_growth_pct == pytest.approx(20.0)  # 500 → 600
    (cam,) = report.cameras
    assert cam.camera_fps.mean == 5.0
    assert cam.skipped_ratio.max == pytest.approx(0.1)  # 0.5/5.0
    (det,) = report.detectors
    assert det.inference_ms.mean == pytest.approx(25.0)


# --------------------------------------------------------------------------- #
# evaluate
# --------------------------------------------------------------------------- #


def _report(
    *,
    growth: float = 5.0,
    inference: float = 50.0,
    skipped: float = 0.02,
) -> PerfReport:
    return PerfReport(
        samples=10,
        duration_s=100.0,
        containers=(ContainerReport("frigate", Stat.of([40.0]), Stat.of([500.0]), growth),),
        cameras=(CameraReport("cam", Stat.of([5.0]), Stat.of([skipped])),),
        detectors=(DetectorReport("cpu1", Stat.of([inference])),),
    )


def test_evaluate_all_pass() -> None:
    v = evaluate(_report(), Thresholds())
    assert v.passed is True
    assert [c.passed for c in v.checks] == [True, True, True]


def test_evaluate_ram_growth_fails() -> None:
    v = evaluate(_report(growth=30.0), Thresholds())
    assert v.passed is False
    assert v.checks[0].name == "RAM stabil"
    assert v.checks[0].passed is False


def test_evaluate_inference_fails() -> None:
    v = evaluate(_report(inference=250.0), Thresholds())
    assert v.passed is False
    assert v.checks[1].name == "CPU başı boş"
    assert v.checks[1].passed is False


def test_evaluate_skipped_fails() -> None:
    v = evaluate(_report(skipped=0.08), Thresholds())
    assert v.passed is False
    assert v.checks[2].name == "Kaçan olay <%5"
    assert v.checks[2].passed is False


def test_evaluate_empty_report_fails_no_data() -> None:
    """Veri yoksa (Frigate+docker erişilemedi) yanlışlıkla GEÇTİ DEĞİL → BAŞARISIZ."""
    empty = PerfReport(samples=0, duration_s=0.0, containers=(), cameras=(), detectors=())
    v = evaluate(empty, Thresholds())
    assert v.passed is False
    assert all(not c.passed for c in v.checks)
    assert all("verisi yok" in c.detail for c in v.checks)


def test_evaluate_frigate_down_fails_even_with_docker() -> None:
    """docker stats var ama Frigate yok → RAM geçse de CPU/kaçan check'leri düşer."""
    report = PerfReport(
        samples=5,
        duration_s=50.0,
        containers=(ContainerReport("frigate", Stat.of([40.0]), Stat.of([500.0]), 2.0),),
        cameras=(),
        detectors=(),
    )
    v = evaluate(report, Thresholds())
    assert v.passed is False
    by_name = {c.name: c for c in v.checks}
    assert by_name["RAM stabil"].passed is True  # docker verisi var
    assert by_name["CPU başı boş"].passed is False  # detector yok
    assert by_name["Kaçan olay <%5"].passed is False  # kamera yok


# --------------------------------------------------------------------------- #
# çıktı biçimleme
# --------------------------------------------------------------------------- #


def test_report_to_dict_is_json_serializable() -> None:
    report = _report()
    verdict = evaluate(report, Thresholds())
    d = report_to_dict(report, verdict)

    assert d["passed"] is True
    assert d["containers"][0]["name"] == "frigate"
    assert d["cameras"][0]["skipped_ratio"]["p95"] == pytest.approx(0.02)
    json.dumps(d)  # serileştirilebilir olmalı (raise etmemeli)


def test_format_summary_marks_verdict() -> None:
    passed = Verdict(passed=True, checks=())
    failed = Verdict(passed=False, checks=())
    report = _report()
    assert "GEÇTİ" in format_summary(report, passed)
    assert "KALDI" in format_summary(report, failed)


def test_samples_to_csv_rows() -> None:
    s = Sample(
        ts=T0,
        cameras=(CameraSample("cam", 5.0, 5.0, 5.0, 0.0),),
        detectors=(DetectorSample("d", 20.0),),
        containers=(ContainerSample("frigate", 40.0, 500.0, 8000.0),),
    )
    rows = samples_to_csv_rows([s])

    assert rows[0] == "timestamp,kind,name,metric,value"
    assert any(",container,frigate,cpu_pct,40.00" in r for r in rows)
    assert any(",camera,cam,camera_fps,5.00" in r for r in rows)
    assert any(",detector,d,inference_ms,20.00" in r for r in rows)


# --------------------------------------------------------------------------- #
# IO döngüsü (canlı stack gerekmez)
# --------------------------------------------------------------------------- #


def _stats(
    camera_fps: float = 5.0, skipped_fps: float = 0.0, inference: float = 25.0
) -> dict[str, Any]:
    return {
        "cameras": {
            "cam_test": {
                "camera_fps": camera_fps,
                "detection_fps": camera_fps,
                "process_fps": camera_fps,
                "skipped_fps": skipped_fps,
            }
        },
        "detectors": {"cpu1": {"inference_speed": inference}},
    }


async def test_sample_loop_collects_until_duration() -> None:
    clock = lambda: T0  # noqa: E731 — testte sabit clock yeterli
    client = _client(_stats())
    samples = await sample_loop(
        client,
        duration=2.5,
        interval=0.0,
        clock=clock,
        docker_fetch=_docker((ContainerSample("frigate", 40.0, 500.0, 8000.0),)),
        monotonic=_monotonic_seq([0.0, 1.0, 2.0, 3.0]),
        sleep=_no_sleep,
    )

    assert len(samples) == 3  # elapsed 3.0 >= 2.5'te durur
    assert samples[0].cameras[0].name == "cam_test"
    assert samples[0].containers[0].name == "frigate"
    await client.aclose()


async def test_run_passes_and_writes_outputs(tmp_path: Any) -> None:
    out = str(tmp_path / "report")
    code = await run(
        _args(out),
        clock=lambda: T0,
        client=_client(_stats(skipped_fps=0.0, inference=25.0)),
        docker_fetch=_docker((ContainerSample("frigate", 40.0, 500.0, 8000.0),)),
        monotonic=_monotonic_seq([0.0, 0.0]),
        sleep=_no_sleep,
    )

    assert code == 0
    csv_text = (tmp_path / "report.csv").read_text(encoding="utf-8")
    assert csv_text.startswith("timestamp,kind,name,metric,value")
    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert payload["passed"] is True


async def test_run_fails_on_high_inference(tmp_path: Any) -> None:
    out = str(tmp_path / "report")
    code = await run(
        _args(out),
        clock=lambda: T0,
        client=_client(_stats(inference=999.0)),  # CPU başı boş check düşer
        docker_fetch=_docker((ContainerSample("frigate", 40.0, 500.0, 8000.0),)),
        monotonic=_monotonic_seq([0.0, 0.0]),
        sleep=_no_sleep,
    )

    assert code == 1
    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert payload["passed"] is False
