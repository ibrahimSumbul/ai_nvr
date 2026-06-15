# VLM Doğruluk Eval — M3 Tır-Renk Analizi

Bu dizin, `OllamaClient.analyze_truck` (qwen2.5vl) VLM çıkarımının **doğruluğunu**
etiketli bir gold sete karşı ölçen eval harness'inin protokolünü ve canlı koşum
çıktılarını tutar.

## Neden ayrı bir harness?

`bridge/tests/test_llm.py` yalnızca **Pydantic şema/parse**'ı doğrular: geçerli
JSON → tipli alanlar, geçersiz renk → `ValidationError`, Türkçe-unicode → ASCII.
Bu, modelin **şemaya uyduğunu** kanıtlar ama **renk/tip/yön çıkarımının doğru
olduğunu** değil. Yani "tasarladım/parse ediyorum"u kanıtlar, "ölçtüm"ü değil.

`bridge/bridge/eval.py` bu boşluğu kapatır: etiketli görüntülere karşı gerçek VLM
çağrısını yer-gerçeğiyle (ground truth) karşılaştırır ve `perf.py` ile aynı şekli
izler (saf scorer'lar + `Thresholds`/`Verdict` + CSV/JSON + `make eval`, exit 0/1).

## Ölçülen metrikler

| Metrik | Ne ölçer |
|---|---|
| Per-alan doğruluk | çekici rengi / dorse rengi / dorse tipi / yön — exact match (cevapsız/başarısız tahmin = yanlış) |
| İkili P/R/F1 | tır-var-mı, dorse-var-mı — precision / recall / F1 + confusion (TP/FP/FN/TN) |
| Renk confusion matrix | hangi renk hangisiyle karışıyor (gri↔metalik, beyaz↔krem…) |
| Cohen κ | çekici rengi için **şans-düzeltmeli** uyum (chance-corrected agreement) |
| Güven kalibrasyonu (ECE) | `guven`'e göre kovalanmış doğruluk → "yüksek güven gerçekten daha doğru mu?" |
| Latency | tahmin başına ms (ort / p95 / maks) |

> **Eşikler PROVİZYONELDİR.** `Thresholds` varsayılanları (renk doğruluğu ≥%80,
> dorse-var F1 ≥0.80, ECE ≤0.15, κ ≥0.50) tutucu seçilmiştir; **ilk canlı baseline
> koşumu** gerçek dağılımı gösterene kadar tek-doğru değer değildir. Baseline sonrası
> bu dosyaya gözlenen sayılar yazılıp eşikler ona göre sıkılaştırılır. (perf.py'deki
> "1h baseline → kriter kalibrasyonu" yolunun aynısı.)
>
> Not (F1 semantiği): dorse-var gold set'i hiç pozitif içermezse (tümü doğru
> negatif) F1 tanımı gereği 0.0 olur ve gate başarısız görünebilir — gold set'in
> hem pozitif hem negatif vaka içermesi beklenir (örnek fixture'da 4 pozitif var).

## Gold set formatı

JSONL (satır başına bir nesne) veya JSON dizisi. Her giriş:

```json
{
  "image_id": "t01_beyaz_tenteli",
  "image": "t01.jpg",
  "tag": "gunduz",
  "expected": {
    "tir_var_mi": true,
    "cekici_rengi": "beyaz",
    "dorse_var_mi": true,
    "dorse_rengi": "mavi",
    "dorse_tipi": "tenteli",
    "yon": "giris"
  },
  "raw_response": { "...": "yalnız replay modunda — kayıtlı ham LLM yanıtı" }
}
```

- `image`  → **canlı mod** için `--images` dizinine göreli dosya adı.
- `raw_response` → **replay mod** için kayıtlı ham LLM yanıtı (nesne ya da string).
  String verilirse üretimdeki `model_validate_json` yolunu birebir egzersiz eder
  (Türkçe-unicode normalizasyonu dahil).
- `expected` renkleri ASCII-literal yazılır; gold tarafı da tahmin tarafıyla aynı
  fonksiyonla normalize edilir, böylece "sarı" ve "sari" tutarlı eşleşir.
- Renk/tip/yön değer kümeleri için bkz. `bridge/bridge/llm.py` (`Color`,
  `TrailerType`, `Direction`).

## İki çalışma modu

### Replay (offline, Ollama'sız — CI + birim test + regresyon)

Kayıtlı ham yanıtları üretimdeki aynı parse yolundan geçirir. Model gerektirmez;
scorer mantığını ve frozen bir baseline'ı doğrular.

```bash
make eval ARGS='--replay --labels tests/fixtures/eval/sample_gold.jsonl'
```

`bridge/tests/fixtures/eval/sample_gold.jsonl` küçük, gizlilik-güvenli (sentetik;
gerçek görüntü/IP yok) bir örnektir — doğru/yanlış/unicode/bozuk-yanıt vakaları
içerir ve `bridge/tests/test_eval.py` tarafından uçtan uca koşulur.

### Canlı (host'ta, stack ayaktayken — asıl ölçüm)

`perf.py` gibi **host'ta** koşar (Ollama'ya host-facing port'tan erişir). Gerçek
etiketli görüntüler üzerinde asıl doğruluk sayılarını üretir.

```bash
# Ollama + model hazır olmalı (qwen2.5vl:7b). Stack için bkz. docs/08-operations.md.
# Not: make eval `bridge/` içine cd'ler → --out yolu bridge/'e GÖRELİDİR. Repo-kökü
# eval/runs/ altına yazmak için '../eval/...' kullan. Eksik üst dizinler oluşturulur.
make eval ARGS='--labels ../GOLD.jsonl --images /path/to/truck_images/ --out ../eval/runs/baseline-1/eval'
```

Çıktı: `<out>.csv` (görüntü başına audit izi — gold vs tahmin yan yana) +
`<out>.json` (özet + verdict) + stdout tablo + exit code (0 geçti / 1 kaldı).

## Canlı koşum çıktıları (`eval/runs/<id>/`)

Gerçek bir gold set + canlı koşum yapıldığında, koşum başına bir alt dizin:
`eval/runs/<id>/eval.json` + `eval.csv` + `FINDINGS.md` (metodoloji + gözlenen
sayılar + dürüst çerçeve). Henüz canlı baseline koşulmadı — bu PR harness'i +
replay altyapısını getirir; canlı ölçüm dokümante edilmiş follow-up'tır
(etiketli gold set + stack gerektirir).

> **Gizlilik:** gerçek kamera kareleri (gold görüntüler) repoya **commit'lenmez**
> (KVKK/PII). Yalnız türetilmiş metrikler (sayılar, confusion matrix) `eval/runs/`
> altında paylaşılabilir.

## docs/12 §A.9 ile ilişki

Bu sürüm canlı/shipped olan **M3 tır-renk** hattını ölçer. docs/12 §A.9'daki M8
**davranış-anlatısı** eval'i (grounding doğruluğu, confabulation audit, handoff
precision/recall) aynı scorer iskeletini (Thresholds/Verdict + saf scorer'lar)
ileride genişletecektir — M8 kodu indiğinde.
