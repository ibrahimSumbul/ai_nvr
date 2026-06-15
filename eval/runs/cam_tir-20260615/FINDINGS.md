# VLM Doğruluk Baseline — `cam_tir` (2026-06-15)

İlk **canlı** tır-renk VLM doğruluk koşumu. Harness: `bridge/bridge/eval.py`
(canlı mod). Amaç: `analyze_truck` (qwen2.5vl:7b) çıkarımının gerçek doğruluğunu
ölçmek — "tasarladım"ı "ölçtüm"e çevirmek.

> **Bu küçük, tek-kaynaklı bir bootstrap baseline'dır** (aşağıdaki sınırlara bak).
> Eşik geçer/kalır değil, **kalibrasyon** amaçlıdır: harness'in provizyonel
> eşiklerini gerçek dağılıma göre ayarlamak ve modelin güçlü/zayıf eksenlerini
> ortaya çıkarmak için.

## Ortam & metodoloji

| | |
|---|---|
| Model | `qwen2.5vl:7b` (Ollama, host `localhost:11434`) |
| Kod | `bridge.eval` canlı mod, üretimdeki `analyze_truck` prompt + parse yolu |
| Kaynak | `cam_tir.mp4` (test stream, 90 s / 640×480), 5 s aralıkla kare çıkarımı |
| Örnek | 7 kare — her birinde **tek baskın ön-plan tırı** seçildi (çoklu-tır kareler hariç) |
| Girdi | **Tam kare** (640×480), bbox-crop **DEĞİL** — bkz. Sınır 3 |
| Annotator | tek (görsel inceleme, AI-destekli); ⚠ kullanıcı onayı bekliyor |
| Tarih | 2026-06-15 |

Tekrar üretmek için (görüntüler repoda **değil** — telif/gizlilik):

```bash
ffmpeg -i cam_tir.mp4 -vf "fps=1/5" -q:v 2 frames/f%02d.jpg
# gold.jsonl etiketlerini frames/ ile eşle, sonra:
make eval ARGS='--labels gold.jsonl --images frames/ --out ../eval/runs/<id>/eval'
```

## Sonuçlar

| Metrik | Sonuç | Gate | Durum |
|---|---|---|---|
| Çekici renk doğruluğu | **6/7 = %85.7** | ≥%80 | ✓ |
| Çekici renk uyumu (Cohen κ) | **0.82** | ≥0.50 | ✓ |
| Tır-var-mı (presence) | P/R/F1 = **1.00** (7/0/0/0) | — | ✓ |
| Dorse-var-mı (presence) | P/R/F1 = **1.00** (7/0/0/0) | ≥0.80 | ✓ |
| Dorse renk doğruluğu | **1/6 = %16.7** | — | ✗ zayıf |
| Dorse tipi doğruluğu | **0/7 = %0** | — | ✗ (model tamamen çekimser) |
| Güven kalibrasyonu (ECE) | **0.257** | ≤0.15 | ✗ aşırı-güvenli |
| Latency (ort / p95) | **19.3 s / 27.5 s** | — | tam-kare, CPU/Metal |

Yön (`yon`) ölçülmedi: transit otoyol görüntüsünde giriş/çıkış **nesnel olarak
gerçeklenemez** (zone/kapı bağlamı yok) → gold `yon=null` (skor dışı).

## Bulgular (eval'in açığa çıkardığı şey)

1. **Çekici (tractor) renk tanıma GÜÇLÜ** — %85.7, κ 0.82. Tek hata
   `lacivert → mavi` (tir12). Bu lacivert/mavi sınırı **öznel** bir near-miss;
   renk-ailesi toleranslı sayımda çekici %100 olurdu. → Çekici rengi güvenilir.

2. **Trailer (dorse) TİPİ kullanılamaz durumda** — model **7/7 `bilinmeyen`**
   döndürdü. Yanlış tahmin etmiyor, **tamamen çekimser kalıyor**. tenteli/açık
   ayrımını tam-karede yapmıyor/yapamıyor. → `dorse_tipi` şu an fact olarak
   sunulmamalı; prompt iyileştirmesi veya crop gerekebilir.

3. **Trailer (dorse) RENGİ zayıf** — 1/6. Model dorse rengini sık sık **"gri"ye**
   default'luyor (beyaz→gri, krem→gri, ×3) ve lacivert→mavi tekrar ediyor.
   Çekici (kabin, net renk) vs dorse (büyük, baskılı/gölgeli yüzey) arasında
   belirgin doğruluk farkı.

4. **Aşırı-güven (kalibrasyon)** — ECE 0.257. 0.90 güven bandında doğruluk %50.
   Model emin olmadığında bile yüksek `guven` veriyor → operatöre yanlış kesinlik
   riski. `guven` ham haliyle eşik kararı için güvenilmez.

5. **Presence (tır/dorse var-mı) mükemmel** — 1.00 F1. Tespit katmanı sağlam;
   zayıflık **nitelik** çıkarımında (renk/tip), varlıkta değil.

## Sınırlar (dürüst çerçeve — "ölçülen ≠ abartılan")

1. **N=7, tek video kaynağı.** İstatistiksel olarak ince; renk başına 1–2 örnek.
   κ/ECE küçük-örnek gürültüsüne açık. Bu bir **trend göstergesi**, kesin oran değil.
2. **Tek annotator (AI-destekli), kullanıcı onayı bekliyor.** docs/12 §A.9 hedefi
   2 insan annotator + κ≥0.8 hakem; bu baseline o bara ulaşmaz. lacivert/mavi gibi
   sınır renkleri tartışmalı.
3. **Tam-kare girdi.** Üretim Frigate'in **bbox-crop snapshot'ını** gönderir
   (tek tıra odaklı, daha kolay). Buradaki tam-kare hem tır-lokalizasyonu hem
   renk-ID'yi birlikte zorlar → bu sayılar muhtemelen **alt sınır** (üretimde daha iyi olabilir).
4. **Test footage**, gerçek saha kamerası değil; YouTube TIR derlemesi (watermark'lı).
5. **Latency tam-kare/CPU'da** ölçüldü; bbox-crop + daha küçük görüntü ile düşer.

## Sıradaki adımlar (eval'in işaret ettiği iş)

- **Eşik kalibrasyonu:** `Thresholds` ECE eşiği (0.15) bu modelde gerçekçi değil;
  çekici-renk ≥%80 ulaşılabilir. Daha büyük set sonrası sıkılaştır.
- **dorse_tipi 0/7 → kök-neden:** prompt'ta tip vurgusu + örnek; veya bbox-crop ile
  tekrar ölç (tam-kare mı suçlu, model mi?).
- **dorse_rengi "gri" bias'ı:** crop + prompt revizyonu sonrası tekrar.
- **Daha büyük, çok-kaynaklı, 2-annotator gold set** (gerçek saha kamerası dahil).
- **Confidence kalibrasyonu:** `guven`'i ham eşik yerine kalibre edilmiş kullan
  (veya alarm tabanını ECE'ye göre ayarla).
