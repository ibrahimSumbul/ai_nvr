"""M3 tır-renk VLM doğruluk eval harness — etiketli gold sete karşı `analyze_truck` ölçer.

Neden ayrı bir harness? `test_llm.py` YALNIZCA Pydantic şema/parse'ı doğrular
(geçerli JSON → tipli alanlar), modelin renk/tip/yön DOĞRULUĞUNU değil. Yani
"tasarladım"ı kanıtlar ama "ölçtüm"ü değil. Bu harness o boşluğu kapatır:
etiketli gold görüntülere karşı `OllamaClient.analyze_truck` koşar ve modelin
çıkarımını yer-gerçeğiyle (ground truth) karşılaştırır.

Ölçülen metrikler (hepsi IO-suz saf fonksiyonlarla — birim test edilebilir):
  - Per-alan doğruluk: çekici rengi / dorse rengi / dorse tipi / yön (exact match)
  - İkili sınıflandırma: tır-var-mı, dorse-var-mı → precision / recall / F1
  - Renk confusion matrix (hangi renk hangisiyle karışıyor — gri↔metalik vb.)
  - Cohen kappa: çekici rengi için şans-düzeltmeli uyum (chance-corrected)
  - Güven kalibrasyonu: `guven`'e göre kovalanmış doğruluk + ECE
    (expected calibration error) — "yüksek güven = gerçekten daha doğru mu?"

İki çalışma modu:
  - **canlı** (`--images DIR --labels FILE`): gerçek Ollama'ya karşı koşar →
    asıl doğruluk sayıları (host'ta, stack ayaktayken; bkz. Makefile `eval`).
  - **replay** (`--replay --labels FILE`): kayıtlı (etiket, ham LLM yanıtı)
    çiftlerini ÜRETİMDEKİ AYNI parse yolundan (`TruckAnalysis.model_validate_json`,
    Türkçe-unicode normalizasyonu dahil) geçirir → Ollama'sız. CI + birim test +
    offline regresyon kapısı bunu kullanır.

`perf.py` şeklini birebir yansıtır (saf scorer'lar + `Thresholds` + `CheckResult`/
`Verdict` + CSV/JSON + stdout tablo + exit code 0/1) ve onun `Stat`/`percentile`/
`CheckResult`/`Verdict` parçalarını yeniden kullanır. docs/12 §A.9'daki M8
davranış-anlatısı eval'i ileride aynı iskeleti genişletecek; bu sürüm canlı/shipped
olan M3 tır-renk hattını ölçer.

Eşikler (`Thresholds`) PROVİZYONELDİR — ilk canlı baseline koşumu kalibre edene
kadar tutucu seçilmiştir; CLI ile override edilir. perf.py'deki "veri yoksa
BAŞARISIZ" dürüstlüğü burada da geçerli: gold örnek yoksa ilgili check exit 0
dönmesin diye 'veri yok' ile kalır.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from bridge.config import Settings
from bridge.llm import (
    LLMClient,
    LLMError,
    OllamaClient,
    TruckAnalysis,
    _normalize_tr_token,
)
from bridge.perf import CheckResult, Stat, Verdict

log = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Gold etiket modeli
# --------------------------------------------------------------------------- #


# Karşılaştırmada gold ve tahmin AYNI normalize uzayında olmalı: TruckAnalysis
# tahmin tarafını ASCII-literal'e indirger (llm.py), gold tarafını da burada
# aynı fonksiyonla indirgeriz ("sarı" ve "sari" tutarlı eşleşsin).
def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    out = _normalize_tr_token(value)
    return out if isinstance(out, str) else None


@dataclass(frozen=True)
class TruckLabel:
    """Tek görüntü için yer-gerçeği (ground truth) — gold annotator etiketi."""

    image_id: str
    tir_var_mi: bool
    cekici_rengi: str | None
    dorse_var_mi: bool
    dorse_rengi: str | None
    dorse_tipi: str | None
    yon: str | None
    tag: str | None = None  # opsiyonel dilimleme etiketi (ışık/zorluk/kamera)


@dataclass(frozen=True)
class GoldEntry:
    """Bir gold satırı: etiket + (canlı için) görüntü adı + (replay için) ham yanıt."""

    label: TruckLabel
    image: str | None  # --images dizinine göreli dosya adı (canlı mod)
    raw_response: str | None  # kayıtlı ham LLM JSON yanıtı (replay mod)


@dataclass(frozen=True)
class CaseResult:
    """Bir görüntünün eval sonucu: etiket + (varsa) tahmin + latency + hata."""

    label: TruckLabel
    prediction: TruckAnalysis | None  # None = LLM çağrısı veya parse başarısız
    latency_ms: int
    error: str | None


# --------------------------------------------------------------------------- #
# Saf parse (gold dosyası → entries) — IO'suz
# --------------------------------------------------------------------------- #


def _parse_entry(obj: dict[str, Any]) -> GoldEntry:
    """Tek JSON nesnesi → GoldEntry. `expected` bloğu gold alanları taşır.

    `raw_response` string (kayıtlı ham JSON) ya da nesne olabilir; nesneyse
    string'e serileştirilir ki replay üretimdeki string-parse yolunu birebir
    egzersiz etsin.
    """
    exp = obj.get("expected", {})
    label = TruckLabel(
        image_id=str(obj.get("image_id") or obj.get("image") or "?"),
        tir_var_mi=bool(exp.get("tir_var_mi", False)),
        cekici_rengi=_norm(exp.get("cekici_rengi")),
        dorse_var_mi=bool(exp.get("dorse_var_mi", False)),
        dorse_rengi=_norm(exp.get("dorse_rengi")),
        dorse_tipi=_norm(exp.get("dorse_tipi")),
        yon=_norm(exp.get("yon")),
        tag=(str(obj["tag"]) if obj.get("tag") is not None else None),
    )
    raw = obj.get("raw_response")
    if raw is not None and not isinstance(raw, str):
        raw = json.dumps(raw, ensure_ascii=False)
    image = obj.get("image")
    return GoldEntry(label=label, image=(str(image) if image else None), raw_response=raw)


def load_labels(text: str) -> tuple[GoldEntry, ...]:
    """Gold dosyasını parse et. JSONL (satır başına bir nesne) veya JSON dizisi.

    Boş satırlar atlanır. Önce JSON dizisi/nesnesi denenir; olmazsa JSONL.
    """
    stripped = text.strip()
    if not stripped:
        return ()
    # JSON dizisi mi?
    try:
        doc = json.loads(stripped)
    except json.JSONDecodeError:
        doc = None
    if isinstance(doc, list):
        return tuple(_parse_entry(o) for o in doc if isinstance(o, dict))
    if isinstance(doc, dict):
        return (_parse_entry(doc),)
    # JSONL
    entries: list[GoldEntry] = []
    for raw in stripped.splitlines():
        line = raw.strip()
        if not line:
            continue
        entries.append(_parse_entry(json.loads(line)))
    return tuple(entries)


# --------------------------------------------------------------------------- #
# Saf scorer'lar (CaseResult dizisi → metrik) — IO'suz, birim test edilebilir
# --------------------------------------------------------------------------- #

# Kategorik alanların tahmin tarafı (None tahmin = cevap yok)
_FIELD_GETTERS: dict[str, Callable[[TruckAnalysis], str | None]] = {
    "cekici_rengi": lambda p: p.cekici_rengi,
    "dorse_rengi": lambda p: p.dorse_rengi,
    "dorse_tipi": lambda p: p.dorse_tipi,
    "yon": lambda p: p.yon,
}


def _gold_value(label: TruckLabel, field: str) -> str | None:
    return {
        "cekici_rengi": label.cekici_rengi,
        "dorse_rengi": label.dorse_rengi,
        "dorse_tipi": label.dorse_tipi,
        "yon": label.yon,
    }[field]


@dataclass(frozen=True)
class FieldAccuracy:
    """Kategorik alan doğruluğu — gold değeri MEVCUT olan örnekler üzerinden.

    `total`   : gold değeri non-null olan örnek sayısı (paydadır).
    `answered`: bunlardan modelin tahmin ürettiği (cevap yok = başarısız tahmin).
    `correct` : tahmin == gold (normalize uzayda).
    Doğruluk = correct/total → cevapsız/başarısız tahmin DOĞRUDAN yanlış sayılır
    (dürüst: model "bilmiyorum" diye atlayıp ceza yememezlik etmesin).
    """

    field: str
    total: int
    answered: int
    correct: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def answer_rate(self) -> float:
        return self.answered / self.total if self.total else 0.0


def field_accuracy(items: Sequence[CaseResult], field: str) -> FieldAccuracy:
    getter = _FIELD_GETTERS[field]
    total = answered = correct = 0
    for it in items:
        gold = _gold_value(it.label, field)
        if gold is None:
            continue  # bu alan bu örnekte uygulanamaz (paydaya girmez)
        total += 1
        if it.prediction is None:
            continue  # cevap yok → yanlış
        pred = getter(it.prediction)
        if pred is not None:
            answered += 1
        if pred == gold:
            correct += 1
    return FieldAccuracy(field=field, total=total, answered=answered, correct=correct)


@dataclass(frozen=True)
class BinaryMetrics:
    """İkili sınıflandırma (tir_var_mi / dorse_var_mi) — cevaplanan örnekler üzerinden.

    `failed` = tahmin üretilemeyen örnekler; precision/recall'dan HARİÇ tutulur ama
    raporlanır (cevap oranı şeffaf kalsın). accuracy = (tp+tn)/answered.
    """

    field: str
    tp: int
    fp: int
    fn: int
    tn: int
    failed: int

    @property
    def answered(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.answered if self.answered else 0.0


def binary_metrics(items: Sequence[CaseResult], field: str) -> BinaryMetrics:
    tp = fp = fn = tn = failed = 0
    for it in items:
        gold = getattr(it.label, field)
        if it.prediction is None:
            failed += 1
            continue
        pred = getattr(it.prediction, field)
        if gold and pred:
            tp += 1
        elif not gold and pred:
            fp += 1
        elif gold and not pred:
            fn += 1
        else:
            tn += 1
    return BinaryMetrics(field=field, tp=tp, fp=fp, fn=fn, tn=tn, failed=failed)


_FAIL_TOKEN = "<cevap-yok>"


def confusion_matrix(items: Sequence[CaseResult], field: str) -> dict[tuple[str, str], int]:
    """(gold, tahmin) → sayım. gold değeri mevcut örnekler üzerinden.

    Tahmin yoksa/None ise tahmin etiketi `<cevap-yok>` olur (kaçaklar görünür).
    """
    getter = _FIELD_GETTERS[field]
    matrix: dict[tuple[str, str], int] = {}
    for it in items:
        gold = _gold_value(it.label, field)
        if gold is None:
            continue
        pred = getter(it.prediction) if it.prediction is not None else None
        key = (gold, pred if pred is not None else _FAIL_TOKEN)
        matrix[key] = matrix.get(key, 0) + 1
    return matrix


def cohen_kappa(items: Sequence[CaseResult], field: str) -> float:
    """Çekici/kategorik alan için şans-düzeltmeli uyum (Cohen κ).

    Yalnız gold MEVCUT ve model CEVAP VERMİŞ örnekler üzerinden (eşleşen çiftler).
    κ = (p_o - p_e) / (1 - p_e). Çok az/tek-sınıf veride 1.0'a yakınsar; gözlenen
    uyum tam ise 1.0, p_e==1 ise tanım gereği 1.0 döner.
    """
    getter = _FIELD_GETTERS[field]
    pairs: list[tuple[str, str]] = []
    for it in items:
        gold = _gold_value(it.label, field)
        if gold is None or it.prediction is None:
            continue
        pred = getter(it.prediction)
        if pred is None:
            continue
        pairs.append((gold, pred))
    n = len(pairs)
    if n == 0:
        return 0.0
    observed = sum(1 for g, p in pairs if g == p) / n
    labels = {g for g, _ in pairs} | {p for _, p in pairs}
    p_e = 0.0
    for lab in labels:
        pg = sum(1 for g, _ in pairs if g == lab) / n
        pp = sum(1 for _, p in pairs if p == lab) / n
        p_e += pg * pp
    if p_e >= 1.0:
        return 1.0
    return (observed - p_e) / (1.0 - p_e)


@dataclass(frozen=True)
class CalibrationBin:
    """Bir güven kovası: aralık + sayım + ortalama güven + gözlenen doğruluk."""

    lo: float
    hi: float
    count: int
    mean_conf: float
    accuracy: float


# Varsayılan kova kenarları — `guven` aralıkları (üst sınır dahil son kovada).
_DEFAULT_BINS: tuple[float, ...] = (0.0, 0.5, 0.7, 0.9, 1.01)


def calibration(
    items: Sequence[CaseResult],
    *,
    field: str = "cekici_rengi",
    bins: Sequence[float] = _DEFAULT_BINS,
) -> tuple[tuple[CalibrationBin, ...], float]:
    """Güven kalibrasyonu: `field` doğruluğunu `guven`'e göre kovala + ECE döndür.

    Doğruluk hedefi default çekici-rengi exact-match'tir (gold rengi mevcut ve
    model cevap vermiş örnekler). ECE = Σ (n_k/N)·|acc_k − conf_k| — düşük = iyi
    kalibre (modelin güveni gerçek doğruluğuyla örtüşüyor).

    N, kovaya GİREN nokta sayısıdır (toplam değil): bins tüm `guven` aralığını
    kapsamazsa (özel `--bins`) kova dışı kalan noktalar ECE'yi şişirmesin/düşürmesin
    diye payda kovalanan noktalara eşitlenir. Default bins (0.0–1.01) tüm aralığı
    kapsar → bu durumda N == toplam.
    """
    getter = _FIELD_GETTERS[field]
    points: list[tuple[float, bool]] = []  # (guven, dogru_mu)
    for it in items:
        gold = _gold_value(it.label, field)
        if gold is None or it.prediction is None:
            continue
        pred = getter(it.prediction)
        if pred is None:
            continue
        points.append((it.prediction.guven, pred == gold))
    out: list[CalibrationBin] = []
    ece_sum = 0.0
    edges = list(bins)
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        bucket = [(c, ok) for c, ok in points if lo <= c < hi]
        if not bucket:
            out.append(CalibrationBin(lo=lo, hi=hi, count=0, mean_conf=0.0, accuracy=0.0))
            continue
        n = len(bucket)
        mean_conf = sum(c for c, _ in bucket) / n
        acc = sum(1 for _, ok in bucket if ok) / n
        out.append(CalibrationBin(lo=lo, hi=hi, count=n, mean_conf=mean_conf, accuracy=acc))
        ece_sum += n * abs(acc - mean_conf)
    used = sum(b.count for b in out)  # kovalanan nokta sayısı (≤ len(points))
    ece = ece_sum / used if used else 0.0
    return tuple(out), ece


# --------------------------------------------------------------------------- #
# Rapor + değerlendirme (eşikler → pass/fail)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EvalReport:
    cases: int
    failures: int  # LLM/parse başarısızlığı (tahmin None)
    latency: Stat
    cekici_color: FieldAccuracy
    dorse_color: FieldAccuracy
    dorse_type: FieldAccuracy
    yon: FieldAccuracy
    tir_presence: BinaryMetrics
    dorse_presence: BinaryMetrics
    color_kappa: float
    calibration: tuple[CalibrationBin, ...]
    ece: float
    color_confusion: dict[tuple[str, str], int]


def summarize(items: Sequence[CaseResult]) -> EvalReport:
    """CaseResult dizisini tüm metriklere indir."""
    latencies = [float(it.latency_ms) for it in items if it.prediction is not None]
    cal_bins, ece = calibration(items)
    return EvalReport(
        cases=len(items),
        failures=sum(1 for it in items if it.prediction is None),
        latency=Stat.of(latencies),
        cekici_color=field_accuracy(items, "cekici_rengi"),
        dorse_color=field_accuracy(items, "dorse_rengi"),
        dorse_type=field_accuracy(items, "dorse_tipi"),
        yon=field_accuracy(items, "yon"),
        tir_presence=binary_metrics(items, "tir_var_mi"),
        dorse_presence=binary_metrics(items, "dorse_var_mi"),
        color_kappa=cohen_kappa(items, "cekici_rengi"),
        calibration=cal_bins,
        ece=ece,
        color_confusion=confusion_matrix(items, "cekici_rengi"),
    )


@dataclass(frozen=True)
class Thresholds:
    """Pass/fail eşikleri — PROVİZYONEL (ilk canlı baseline kalibre edene kadar).

    CLI ile override edilir. Tek-doğru sayı bilinmeden konan tutucu varsayılanlar;
    canlı koşum sonrası eval/README.md'deki baseline'a göre sıkılaştırılır.
    """

    min_cekici_color_acc: float = 0.80  # çekici rengi exact-match doğruluğu
    min_dorse_presence_f1: float = 0.80  # dorse-var-mı F1
    max_ece: float = 0.15  # güven kalibrasyon hatası (düşük iyi)
    min_color_kappa: float = 0.50  # şans-düzeltmeli renk uyumu


def evaluate(report: EvalReport, thresholds: Thresholds) -> Verdict:
    """Raporu eşiklere göre değerlendir → 4 check + genel sonuç.

    Gold örnek yoksa ilgili check **'veri yok' ile BAŞARISIZ** olur (perf.py
    dürüstlüğü): eksik gold set yanlışlıkla exit 0 dönmesin.
    """
    checks: list[CheckResult] = []

    cc = report.cekici_color
    if cc.total == 0:
        checks.append(CheckResult("Çekici renk doğruluğu", False, "renk etiketli gold örnek yok"))
    else:
        checks.append(
            CheckResult(
                "Çekici renk doğruluğu",
                cc.accuracy >= thresholds.min_cekici_color_acc,
                f"{cc.accuracy * 100:.1f}% ({cc.correct}/{cc.total}), "
                f"cevap oranı {cc.answer_rate * 100:.0f}%, "
                f"eşik ≥{thresholds.min_cekici_color_acc * 100:.0f}%",
            )
        )

    dp = report.dorse_presence
    if dp.answered == 0:
        checks.append(CheckResult("Dorse-var F1", False, "cevaplanan dorse-var örneği yok"))
    else:
        checks.append(
            CheckResult(
                "Dorse-var F1",
                dp.f1 >= thresholds.min_dorse_presence_f1,
                f"F1 {dp.f1:.2f} (P {dp.precision:.2f} / R {dp.recall:.2f}), "
                f"eşik ≥{thresholds.min_dorse_presence_f1:.2f}",
            )
        )

    cal_n = sum(b.count for b in report.calibration)
    if cal_n == 0:
        checks.append(CheckResult("Güven kalibrasyonu (ECE)", False, "kalibrasyon örneği yok"))
    else:
        checks.append(
            CheckResult(
                "Güven kalibrasyonu (ECE)",
                report.ece <= thresholds.max_ece,
                f"ECE {report.ece:.3f} (n={cal_n}), eşik ≤{thresholds.max_ece:.2f}",
            )
        )

    if cc.answered == 0:
        checks.append(CheckResult("Renk uyumu (κ)", False, "cevaplanan renk örneği yok"))
    else:
        checks.append(
            CheckResult(
                "Renk uyumu (κ)",
                report.color_kappa >= thresholds.min_color_kappa,
                f"κ {report.color_kappa:.2f}, eşik ≥{thresholds.min_color_kappa:.2f}",
            )
        )

    return Verdict(passed=all(c.passed for c in checks), checks=tuple(checks))


# --------------------------------------------------------------------------- #
# IO katmanı (canlı Ollama / replay)
# --------------------------------------------------------------------------- #


async def evaluate_live(
    client: LLMClient, entries: Sequence[GoldEntry], images_dir: Path
) -> list[CaseResult]:
    """Her gold görüntüyü gerçek `analyze_truck`'tan geçir (canlı Ollama)."""
    results: list[CaseResult] = []
    for e in entries:
        if not e.image:
            results.append(CaseResult(e.label, None, 0, "gold girişinde 'image' yok"))
            continue
        try:
            res = await client.analyze_truck(images_dir / e.image)
            results.append(CaseResult(e.label, res.parsed, res.latency_ms, None))
        except LLMError as exc:
            log.warning("eval.live_failed", image=e.image, error=str(exc))
            results.append(CaseResult(e.label, None, 0, str(exc)))
    return results


def evaluate_replay(entries: Sequence[GoldEntry]) -> list[CaseResult]:
    """Kayıtlı ham yanıtları ÜRETİMDEKİ AYNI parse yolundan geçir (Ollama'sız).

    `TruckAnalysis.model_validate_json` Türkçe-unicode normalizasyonunu da
    uyguladığından replay, gerçek parse davranışını birebir egzersiz eder.
    """
    results: list[CaseResult] = []
    for e in entries:
        if e.raw_response is None:
            results.append(CaseResult(e.label, None, 0, "replay için 'raw_response' yok"))
            continue
        try:
            pred = TruckAnalysis.model_validate_json(e.raw_response)
            results.append(CaseResult(e.label, pred, 0, None))
        except ValueError as exc:
            results.append(CaseResult(e.label, None, 0, f"parse: {exc}"))
    return results


# --------------------------------------------------------------------------- #
# Çıktı (per-case CSV + JSON özet + stdout tablo)
# --------------------------------------------------------------------------- #


def _csv_cell(value: str | None) -> str:
    """CSV güvenli hücre (virgül/None)."""
    if value is None:
        return ""
    return value.replace(",", ";")


def cases_to_csv_rows(items: Sequence[CaseResult]) -> list[str]:
    """Per-case (görüntü başına bir satır) audit izi — gold vs tahmin yan yana."""
    rows = [
        "image_id,gold_cekici,pred_cekici,cekici_ok,gold_dorse_var,pred_dorse_var,"
        "gold_dorse_rengi,pred_dorse_rengi,gold_dorse_tipi,pred_dorse_tipi,"
        "gold_yon,pred_yon,guven,latency_ms,error"
    ]
    for it in items:
        p = it.prediction
        cekici_ok = (
            ""
            if it.label.cekici_rengi is None
            else str(p is not None and p.cekici_rengi == it.label.cekici_rengi)
        )
        rows.append(
            ",".join(
                [
                    _csv_cell(it.label.image_id),
                    _csv_cell(it.label.cekici_rengi),
                    _csv_cell(p.cekici_rengi if p else None),
                    cekici_ok,
                    str(it.label.dorse_var_mi),
                    ("" if p is None else str(p.dorse_var_mi)),
                    _csv_cell(it.label.dorse_rengi),
                    _csv_cell(p.dorse_rengi if p else None),
                    _csv_cell(it.label.dorse_tipi),
                    _csv_cell(p.dorse_tipi if p else None),
                    _csv_cell(it.label.yon),
                    _csv_cell(p.yon if p else None),
                    ("" if p is None else f"{p.guven:.2f}"),
                    str(it.latency_ms),
                    _csv_cell(it.error),
                ]
            )
        )
    return rows


def report_to_dict(report: EvalReport, verdict: Verdict) -> dict[str, Any]:
    """Özet raporu JSON-serileştirilebilir dict'e çevir."""

    def fa(a: FieldAccuracy) -> dict[str, Any]:
        return {
            "total": a.total,
            "answered": a.answered,
            "correct": a.correct,
            "accuracy": a.accuracy,
            "answer_rate": a.answer_rate,
        }

    def bm(b: BinaryMetrics) -> dict[str, Any]:
        return {
            "tp": b.tp,
            "fp": b.fp,
            "fn": b.fn,
            "tn": b.tn,
            "failed": b.failed,
            "precision": b.precision,
            "recall": b.recall,
            "f1": b.f1,
            "accuracy": b.accuracy,
        }

    return {
        "cases": report.cases,
        "failures": report.failures,
        "passed": verdict.passed,
        "checks": [
            {"name": c.name, "passed": c.passed, "detail": c.detail} for c in verdict.checks
        ],
        "latency_ms": {
            "count": report.latency.count,
            "min": report.latency.min,
            "max": report.latency.max,
            "mean": report.latency.mean,
            "p95": report.latency.p95,
        },
        "cekici_color": fa(report.cekici_color),
        "dorse_color": fa(report.dorse_color),
        "dorse_type": fa(report.dorse_type),
        "yon": fa(report.yon),
        "tir_presence": bm(report.tir_presence),
        "dorse_presence": bm(report.dorse_presence),
        "color_kappa": report.color_kappa,
        "ece": report.ece,
        "calibration": [
            {
                "range": f"[{b.lo:.2f},{b.hi:.2f})",
                "count": b.count,
                "mean_conf": b.mean_conf,
                "accuracy": b.accuracy,
            }
            for b in report.calibration
        ],
        "color_confusion": [
            {"gold": g, "pred": p, "count": n}
            for (g, p), n in sorted(report.color_confusion.items())
        ],
    }


def _write_outputs(
    out_prefix: str, items: Sequence[CaseResult], report: EvalReport, verdict: Verdict
) -> None:
    csv_path = Path(f"{out_prefix}.csv")
    json_path = Path(f"{out_prefix}.json")
    # Nested --out (örn. ../eval/runs/<id>/eval) için üst dizini oluştur.
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("\n".join(cases_to_csv_rows(items)) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(report_to_dict(report, verdict), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    log.info("eval.written", csv=str(csv_path), json=str(json_path))


def format_summary(report: EvalReport, verdict: Verdict) -> str:
    """stdout için insan-okunur özet tablosu."""
    lines: list[str] = [
        f"VLM tır-renk eval: {report.cases} örnek, {report.failures} başarısız tahmin",
        "",
        "Alan doğruluğu          doğru/toplam   doğruluk  cevap%",
    ]
    for a in (report.cekici_color, report.dorse_color, report.dorse_type, report.yon):
        lines.append(
            f"  {a.field:<20} {a.correct:>3}/{a.total:<3}        "
            f"{a.accuracy * 100:5.1f}%   {a.answer_rate * 100:4.0f}%"
        )
    lines.append("")
    lines.append("İkili (var-mı)          P / R / F1            TP/FP/FN/TN (fail)")
    for b in (report.tir_presence, report.dorse_presence):
        lines.append(
            f"  {b.field:<20} {b.precision:.2f}/{b.recall:.2f}/{b.f1:.2f}     "
            f"{b.tp}/{b.fp}/{b.fn}/{b.tn} ({b.failed})"
        )
    lines.append("")
    lines.append(f"Çekici renk uyumu (Cohen κ): {report.color_kappa:.2f}")
    lines.append(f"Güven kalibrasyonu (ECE):    {report.ece:.3f}")
    lines.append("  güven aralığı   n    ort.güven  doğruluk")
    for cb in report.calibration:
        if cb.count == 0:
            continue
        lines.append(
            f"  [{cb.lo:.2f},{cb.hi:.2f})    {cb.count:<4} {cb.mean_conf:6.2f}    "
            f"{cb.accuracy * 100:5.1f}%"
        )
    if report.latency.count:
        lines.append("")
        lines.append(
            f"Latency ms: ort {report.latency.mean:.0f} / p95 {report.latency.p95:.0f} "
            f"/ maks {report.latency.max:.0f}"
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
    p = argparse.ArgumentParser(prog="bridge.eval", description="M3 tır-renk VLM doğruluk eval")
    p.add_argument("--labels", required=True, help="gold etiket dosyası (JSONL veya JSON dizisi)")
    p.add_argument("--images", default=".", help="canlı mod: görüntü dizini (gold 'image' göreli)")
    p.add_argument(
        "--replay",
        action="store_true",
        help="replay mod: gold 'raw_response' kayıtlarını kullan (Ollama'sız, CI/offline)",
    )
    p.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="canlı mod: host-facing Ollama URL (default localhost:11434)",
    )
    p.add_argument("--model", default=None, help="canlı mod: Ollama model (default Settings)")
    p.add_argument("--out", default="eval-report", help="çıktı dosya öneki (.csv/.json)")
    p.add_argument("--min-cekici-acc", type=float, default=0.80, help="çekici renk doğruluk eşiği")
    p.add_argument("--min-dorse-f1", type=float, default=0.80, help="dorse-var F1 eşiği")
    p.add_argument("--max-ece", type=float, default=0.15, help="kalibrasyon hata eşiği (ECE)")
    p.add_argument("--min-kappa", type=float, default=0.50, help="renk uyumu κ eşiği")
    return p.parse_args(argv)


async def run(args: argparse.Namespace, *, client: LLMClient | None = None) -> int:
    """Yükle → (canlı/replay) koş → özetle → değerlendir → yaz → exit code."""
    thresholds = Thresholds(
        min_cekici_color_acc=args.min_cekici_acc,
        min_dorse_presence_f1=args.min_dorse_f1,
        max_ece=args.max_ece,
        min_color_kappa=args.min_kappa,
    )
    entries = load_labels(Path(args.labels).read_text(encoding="utf-8"))

    if args.replay:
        items = evaluate_replay(entries)
    else:
        owns_client = client is None
        if client is None:
            settings = Settings(llm_ollama_url=args.ollama_url)
            if args.model:
                settings = Settings(llm_ollama_url=args.ollama_url, llm_ollama_model=args.model)
            client = OllamaClient(settings)
        try:
            items = await evaluate_live(client, entries, Path(args.images))
        finally:
            if owns_client:
                await client.close()

    report = summarize(items)
    verdict = evaluate(report, thresholds)
    _write_outputs(args.out, items, report, verdict)
    print(format_summary(report, verdict))
    return 0 if verdict.passed else 1


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
