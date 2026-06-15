"""VLM tır-renk eval harness testleri — saf scorer'lar + replay + run() (enjekte client).

Sayısal beklentiler küçük, elle-hesaplanmış CaseResult listeleri üzerinden doğrulanır
(her metrik tek tek izlenebilir); fixture dosyası ayrıca uçtan-uca replay yolunu sınar.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from bridge.eval import (
    CaseResult,
    GoldEntry,
    TruckLabel,
    binary_metrics,
    calibration,
    cases_to_csv_rows,
    cohen_kappa,
    confusion_matrix,
    evaluate,
    evaluate_replay,
    field_accuracy,
    format_summary,
    load_labels,
    report_to_dict,
    run,
    summarize,
)
from bridge.llm import LLMError, LLMResult, TruckAnalysis

FIXTURE = Path(__file__).parent / "fixtures" / "eval" / "sample_gold.jsonl"


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #


def _label(
    image_id: str,
    *,
    tir: bool = True,
    cekici: str | None = None,
    dorse_var: bool = False,
    dorse_rengi: str | None = None,
    dorse_tipi: str | None = None,
    yon: str | None = None,
) -> TruckLabel:
    return TruckLabel(
        image_id=image_id,
        tir_var_mi=tir,
        cekici_rengi=cekici,
        dorse_var_mi=dorse_var,
        dorse_rengi=dorse_rengi,
        dorse_tipi=dorse_tipi,
        yon=yon,
    )


def _pred(
    *,
    tir: bool = True,
    cekici: str | None = None,
    dorse_var: bool = False,
    dorse_rengi: str | None = None,
    dorse_tipi: str | None = None,
    yon: str | None = None,
    guven: float = 0.9,
) -> TruckAnalysis:
    return TruckAnalysis(
        tir_var_mi=tir,
        cekici_rengi=cekici,  # type: ignore[arg-type]
        dorse_var_mi=dorse_var,
        dorse_rengi=dorse_rengi,  # type: ignore[arg-type]
        dorse_tipi=dorse_tipi,  # type: ignore[arg-type]
        yon=yon,  # type: ignore[arg-type]
        guven=guven,
    )


def _case(label: TruckLabel, pred: TruckAnalysis | None, *, latency: int = 0) -> CaseResult:
    return CaseResult(label=label, prediction=pred, latency_ms=latency, error=None)


# --------------------------------------------------------------------------- #
# field_accuracy
# --------------------------------------------------------------------------- #


def test_field_accuracy_counts_missing_prediction_as_wrong() -> None:
    items = [
        _case(_label("a", cekici="beyaz"), _pred(cekici="beyaz")),  # doğru
        _case(_label("b", cekici="siyah"), _pred(cekici="mavi")),  # yanlış
        _case(_label("c", cekici="gri"), None),  # cevap yok → yanlış
        _case(_label("d", cekici=None), _pred(cekici="beyaz")),  # gold yok → paydaya girmez
    ]
    fa = field_accuracy(items, "cekici_rengi")
    assert fa.total == 3
    assert fa.answered == 2  # a, b (c None, d hariç)
    assert fa.correct == 1
    assert fa.accuracy == pytest.approx(1 / 3)
    assert fa.answer_rate == pytest.approx(2 / 3)


def test_field_accuracy_empty_is_zero_not_crash() -> None:
    fa = field_accuracy([], "cekici_rengi")
    assert fa.total == 0
    assert fa.accuracy == 0.0
    assert fa.answer_rate == 0.0


# --------------------------------------------------------------------------- #
# binary_metrics
# --------------------------------------------------------------------------- #


def test_binary_metrics_confusion_and_derived() -> None:
    items = [
        _case(_label("tp", dorse_var=True), _pred(dorse_var=True)),
        _case(_label("tn", dorse_var=False), _pred(dorse_var=False)),
        _case(_label("fp", dorse_var=False), _pred(dorse_var=True)),
        _case(_label("fn", dorse_var=True), _pred(dorse_var=False)),
        _case(_label("fail", dorse_var=True), None),  # cevap yok → failed
    ]
    bm = binary_metrics(items, "dorse_var_mi")
    assert (bm.tp, bm.fp, bm.fn, bm.tn, bm.failed) == (1, 1, 1, 1, 1)
    assert bm.answered == 4
    assert bm.precision == pytest.approx(0.5)
    assert bm.recall == pytest.approx(0.5)
    assert bm.f1 == pytest.approx(0.5)
    assert bm.accuracy == pytest.approx(0.5)  # (1+1)/4


def test_binary_metrics_no_positives_safe() -> None:
    items = [_case(_label("x", dorse_var=False), _pred(dorse_var=False))]
    bm = binary_metrics(items, "dorse_var_mi")
    assert bm.precision == 0.0
    assert bm.recall == 0.0
    assert bm.f1 == 0.0
    assert bm.accuracy == 1.0  # tn=1


# --------------------------------------------------------------------------- #
# confusion_matrix
# --------------------------------------------------------------------------- #


def test_confusion_matrix_includes_fail_token() -> None:
    items = [
        _case(_label("a", cekici="gri"), _pred(cekici="metalik")),
        _case(_label("b", cekici="gri"), _pred(cekici="gri")),
        _case(_label("c", cekici="beyaz"), None),  # cevap yok
        _case(_label("d", cekici=None), _pred(cekici="mavi")),  # gold yok → girmez
    ]
    m = confusion_matrix(items, "cekici_rengi")
    assert m[("gri", "metalik")] == 1
    assert m[("gri", "gri")] == 1
    assert m[("beyaz", "<cevap-yok>")] == 1
    assert ("beyaz", None) not in m
    assert sum(m.values()) == 3  # d hariç


# --------------------------------------------------------------------------- #
# cohen_kappa
# --------------------------------------------------------------------------- #


def test_cohen_kappa_perfect_agreement() -> None:
    items = [
        _case(_label("a", cekici="beyaz"), _pred(cekici="beyaz")),
        _case(_label("b", cekici="siyah"), _pred(cekici="siyah")),
    ]
    assert cohen_kappa(items, "cekici_rengi") == pytest.approx(1.0)


def test_cohen_kappa_chance_corrected_below_observed() -> None:
    # 4 örnek: 3 doğru, 1 yanlış. observed=0.75 ama şans-düzeltmeli κ daha düşük.
    items = [
        _case(_label("a", cekici="beyaz"), _pred(cekici="beyaz")),
        _case(_label("b", cekici="beyaz"), _pred(cekici="beyaz")),
        _case(_label("c", cekici="siyah"), _pred(cekici="siyah")),
        _case(_label("d", cekici="siyah"), _pred(cekici="beyaz")),
    ]
    # gold: beyaz×2, siyah×2 → pg(beyaz)=0.5, pg(siyah)=0.5
    # pred: beyaz×3, siyah×1 → pp(beyaz)=0.75, pp(siyah)=0.25
    # p_e = 0.5*0.75 + 0.5*0.25 = 0.5 ; observed = 0.75
    # κ = (0.75-0.5)/(1-0.5) = 0.5
    assert cohen_kappa(items, "cekici_rengi") == pytest.approx(0.5)


def test_cohen_kappa_empty_is_zero() -> None:
    assert cohen_kappa([], "cekici_rengi") == 0.0


# --------------------------------------------------------------------------- #
# calibration / ECE
# --------------------------------------------------------------------------- #


def test_calibration_well_calibrated_low_ece() -> None:
    # Güven == gözlenen doğruluk → ECE ≈ 0.
    items = [
        _case(_label("a", cekici="beyaz"), _pred(cekici="beyaz", guven=0.95)),
        _case(_label("b", cekici="siyah"), _pred(cekici="siyah", guven=0.95)),
    ]
    bins, ece = calibration(items)
    assert ece == pytest.approx(0.05, abs=1e-9)  # |1.0 - 0.95|
    # tek dolu kova [0.9,1.01)
    filled = [b for b in bins if b.count > 0]
    assert len(filled) == 1
    assert filled[0].count == 2
    assert filled[0].accuracy == pytest.approx(1.0)


def test_calibration_overconfident_high_ece() -> None:
    # Yüksek güven ama yanlış → ECE büyük.
    items = [
        _case(_label("a", cekici="beyaz"), _pred(cekici="mavi", guven=0.95)),
        _case(_label("b", cekici="siyah"), _pred(cekici="mavi", guven=0.95)),
    ]
    _bins, ece = calibration(items)
    assert ece == pytest.approx(0.95, abs=1e-9)  # |0.0 - 0.95|


def test_calibration_skips_unanswered_and_missing_gold() -> None:
    items = [
        _case(_label("a", cekici="beyaz"), None),  # cevap yok → atlanır
        _case(_label("b", cekici=None), _pred(cekici="mavi", guven=0.9)),  # gold yok → atlanır
    ]
    bins, ece = calibration(items)
    assert ece == 0.0
    assert all(b.count == 0 for b in bins)


def test_calibration_ece_denominator_is_bucketed_count_not_total() -> None:
    """Kova dışı kalan noktalar ECE'yi düşürmemeli: payda = kovalanan nokta sayısı.

    Özel bins (tüm guven aralığını kapsamayan) verilince, kova dışındaki nokta
    paydaya girmemeli — yoksa ECE yanlışça düşük raporlanır.
    """
    items = [
        _case(
            _label("a", cekici="beyaz"), _pred(cekici="beyaz", guven=0.95)
        ),  # [0.9,1.01) → 1 doğru
        _case(_label("b", cekici="siyah"), _pred(cekici="siyah", guven=0.20)),  # kova dışı
    ]
    _bins, ece = calibration(items, bins=(0.9, 1.01))
    # Yalnız 'a' kovalanır: |acc 1.0 - conf 0.95| / 1 = 0.05 (toplam=2'ye bölünseydi 0.025 olurdu)
    assert ece == pytest.approx(0.05, abs=1e-9)


# --------------------------------------------------------------------------- #
# summarize + evaluate (eşikler)
# --------------------------------------------------------------------------- #


def test_evaluate_passes_when_above_thresholds() -> None:
    from bridge.eval import Thresholds

    # Hepsi doğru + güven doğrulukla örtüşür (0.98 ≈ %100) → iyi kalibre, ECE düşük.
    items = [
        _case(
            _label("a", cekici="beyaz", dorse_var=True),
            _pred(cekici="beyaz", dorse_var=True, guven=0.98),
        ),
        _case(
            _label("b", cekici="siyah", dorse_var=True),
            _pred(cekici="siyah", dorse_var=True, guven=0.98),
        ),
        _case(
            _label("c", cekici="gri", dorse_var=False),
            _pred(cekici="gri", dorse_var=False, guven=0.98),
        ),
    ]
    report = summarize(items)
    verdict = evaluate(report, Thresholds())
    assert verdict.passed is True, [(c.name, c.detail) for c in verdict.checks]
    assert all(c.passed for c in verdict.checks)


def test_evaluate_empty_fails_no_silent_pass() -> None:
    """Gold örnek yoksa 'veri yok' ile BAŞARISIZ (perf.py dürüstlüğü)."""
    from bridge.eval import Thresholds

    report = summarize([])
    verdict = evaluate(report, Thresholds())
    assert verdict.passed is False
    assert all(not c.passed for c in verdict.checks)
    assert any("yok" in c.detail for c in verdict.checks)


def test_evaluate_fails_below_color_threshold() -> None:
    from bridge.eval import Thresholds

    items = [
        _case(_label("a", cekici="beyaz"), _pred(cekici="mavi")),  # yanlış
        _case(_label("b", cekici="siyah"), _pred(cekici="kirmizi")),  # yanlış
    ]
    report = summarize(items)
    verdict = evaluate(report, Thresholds(min_cekici_color_acc=0.8))
    assert verdict.passed is False
    color_check = next(c for c in verdict.checks if "Çekici renk" in c.name)
    assert color_check.passed is False


# --------------------------------------------------------------------------- #
# load_labels parse
# --------------------------------------------------------------------------- #


def test_load_labels_jsonl_and_normalizes_gold_unicode() -> None:
    text = (
        '{"image_id": "x", "expected": {"tir_var_mi": true, "cekici_rengi": "Sarı", '
        '"dorse_var_mi": false}, "raw_response": {"tir_var_mi": true, "guven": 0.5}}\n'
    )
    entries = load_labels(text)
    assert len(entries) == 1
    assert entries[0].label.cekici_rengi == "sari"  # gold da normalize edilir
    assert entries[0].raw_response is not None  # nesne → string'e serileştirildi


def test_load_labels_empty_returns_empty() -> None:
    assert load_labels("") == ()
    assert load_labels("   \n  ") == ()


def test_load_labels_json_array() -> None:
    text = '[{"image_id": "a", "expected": {"tir_var_mi": true}}]'
    entries = load_labels(text)
    assert len(entries) == 1
    assert entries[0].label.image_id == "a"


# --------------------------------------------------------------------------- #
# evaluate_replay — üretimdeki parse yolunu egzersiz eder
# --------------------------------------------------------------------------- #


def test_replay_parses_object_and_string_and_normalizes() -> None:
    entries = [
        GoldEntry(
            _label("ok", cekici="sari"),
            None,
            '{"tir_var_mi": true, "cekici_rengi": "sarı", "dorse_var_mi": false, "guven": 0.8}',
        ),
        GoldEntry(_label("bad", cekici="gri"), None, "gecersiz json {"),
        GoldEntry(_label("noraw", cekici="gri"), None, None),
    ]
    results = evaluate_replay(entries)
    assert results[0].prediction is not None
    assert results[0].prediction.cekici_rengi == "sari"  # unicode → ascii (üretim yolu)
    assert results[1].prediction is None  # bozuk JSON → fail
    assert results[1].error is not None
    assert results[2].prediction is None  # raw_response yok


# --------------------------------------------------------------------------- #
# Fixture: uçtan-uca replay (dosya → load → replay → summarize → evaluate)
# --------------------------------------------------------------------------- #


def test_fixture_end_to_end_replay() -> None:
    entries = load_labels(FIXTURE.read_text(encoding="utf-8"))
    assert len(entries) == 10
    items = evaluate_replay(entries)
    report = summarize(items)

    # 2 örnek parse edilemez (t08 bozuk JSON, t09 gecersiz renk 'altin')
    assert report.failures == 2
    # çekici renk: 10 gold, 2 fail + 3 yanlış → 5 doğru
    assert report.cekici_color.total == 10
    assert report.cekici_color.correct == 5
    assert report.cekici_color.answered == 8
    # unicode örnek (t03) doğru sayıldı → confusion'da (sari, sari) var
    assert report.color_confusion.get(("sari", "sari")) == 1
    # dorse-var: tp=4, fn=1 (t07 dorse kaçtı), failed=2
    assert report.dorse_presence.tp == 4
    assert report.dorse_presence.fn == 1
    assert report.dorse_presence.failed == 2
    # ECE pozitif (model kötü kalibre — t05 aşırı güven/yanlış)
    assert report.ece > 0.0


# --------------------------------------------------------------------------- #
# Çıktı serileştirme
# --------------------------------------------------------------------------- #


def test_report_to_dict_is_json_serializable() -> None:
    import json

    from bridge.eval import Thresholds

    items = [
        _case(_label("a", cekici="beyaz", dorse_var=True), _pred(cekici="beyaz", dorse_var=True))
    ]
    report = summarize(items)
    verdict = evaluate(report, Thresholds())
    d = report_to_dict(report, verdict)
    json.dumps(d, ensure_ascii=False)  # patlamamalı
    assert d["cases"] == 1
    assert "checks" in d
    assert isinstance(d["color_confusion"], list)


def test_csv_rows_header_and_one_row_per_case() -> None:
    items = [
        _case(_label("a", cekici="beyaz"), _pred(cekici="beyaz", guven=0.9)),
        _case(_label("b", cekici="gri"), None),
    ]
    rows = cases_to_csv_rows(items)
    assert rows[0].startswith("image_id,gold_cekici,pred_cekici")
    assert len(rows) == 3  # header + 2
    assert rows[1].startswith("a,beyaz,beyaz,True")
    assert ",,,," in rows[2] or rows[2].startswith("b,gri,,")  # cevapsız satır


def test_format_summary_contains_verdict_marker() -> None:
    from bridge.eval import Thresholds

    items = [
        _case(_label("a", cekici="beyaz", dorse_var=True), _pred(cekici="beyaz", dorse_var=True))
    ]
    out = format_summary(summarize(items), evaluate(summarize(items), Thresholds()))
    assert "VLM tır-renk eval" in out
    assert ("GEÇTİ" in out) or ("KALDI" in out)


# --------------------------------------------------------------------------- #
# run() — replay (IO'suz) + live (enjekte fake client)
# --------------------------------------------------------------------------- #


def _args(**kw: object) -> argparse.Namespace:
    base = dict(
        labels="",
        images=".",
        replay=False,
        ollama_url="http://localhost:11434",
        model=None,
        out="eval-test",
        min_cekici_acc=0.8,
        min_dorse_f1=0.8,
        max_ece=0.15,
        min_kappa=0.5,
    )
    base.update(kw)
    return argparse.Namespace(**base)


async def test_run_replay_mode_writes_outputs(tmp_path: Path) -> None:
    out = tmp_path / "rep"
    args = _args(labels=str(FIXTURE), replay=True, out=str(out))
    code = await run(args)
    assert code in (0, 1)
    assert (tmp_path / "rep.csv").exists()
    assert (tmp_path / "rep.json").exists()


class _FakeClient:
    """analyze_truck'ı görüntü adına göre sabit cevaplayan sahte LLM client."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def analyze_truck(self, image_path: Path) -> LLMResult:
        self.calls.append(image_path.name)
        if "fail" in image_path.name:
            raise LLMError("sahte hata")
        parsed = TruckAnalysis(
            tir_var_mi=True,
            cekici_rengi="beyaz",
            dorse_var_mi=False,
            guven=0.9,
        )
        return LLMResult(parsed=parsed, raw_response="{}", model="fake", latency_ms=42)

    async def close(self) -> None:
        pass


async def test_run_live_mode_with_injected_client(tmp_path: Path) -> None:
    labels = tmp_path / "g.jsonl"
    labels.write_text(
        '{"image_id": "i1", "image": "ok.jpg", "expected": {"tir_var_mi": true, "cekici_rengi": "beyaz", "dorse_var_mi": false}}\n'
        '{"image_id": "i2", "image": "fail.jpg", "expected": {"tir_var_mi": true, "cekici_rengi": "siyah", "dorse_var_mi": false}}\n',
        encoding="utf-8",
    )
    out = tmp_path / "live"
    args = _args(labels=str(labels), replay=False, images=str(tmp_path), out=str(out))
    fake = _FakeClient()
    code = await run(args, client=fake)
    assert code in (0, 1)
    assert fake.calls == ["ok.jpg", "fail.jpg"]
    # i1 doğru (beyaz), i2 LLMError → fail; renk doğruluğu 1/2
    import json

    data = json.loads((tmp_path / "live.json").read_text(encoding="utf-8"))
    assert data["failures"] == 1
    assert data["cekici_color"]["correct"] == 1
    assert data["cekici_color"]["total"] == 2
