# 07 — Maliyet Analizi

> **M3 güncellemesi:** Bu proje semantik analizde **lokal Ollama** (`qwen2.5vl:7b`) kullanır. **Aylık LLM maliyeti $0**'dır (yalnızca elektrik) — görüntüler tesisten çıkmaz, token/kota yoktur. Eski "$10–25/ay Haiku bütçesi" anlatısı geçersizdir; aşağıdaki tablolar lokal $0 modeline göre revize edilmiştir. Bulut hibrit (Anthropic) **planlıdır** — `LLM_PROVIDER` switch + `LLM_MONTHLY_BUDGET_USD` ayarı kodda hazır ama implementasyon henüz yok (bkz. [`06-llm-strategy.md`](06-llm-strategy.md), [`11-tech-decisions.md`](11-tech-decisions.md)).

## Özet — Toplam Maliyet

| Faz | Donanım (tek seferlik) | LLM (aylık) | Toplam aylık |
|---|---|---|---|
| **PoC** | $0 (mevcut sunucu, CPU detection) | **$0** (lokal Ollama) | ~$2–3 (sadece elektrik) |
| **Production** | ~$60 (1× Coral USB, opsiyonel) | **$0** (lokal Ollama) | ~$3–6 (sadece elektrik) |

Lokal Ollama'da **aylık tekrarlayan LLM maliyeti yoktur**. Tek seferlik donanım (opsiyonel $60 Coral, Frigate detection için) ve sunucu elektriği dışında işletme maliyeti $0'a yakındır. NVR'a yük binmez (direct kamera bağlantısı zorunlu).

> **Bütçe guard:** `.env` `LLM_MONTHLY_BUDGET_USD` ayarı yalnızca **planlı** bulut hibrit (Anthropic) içindir; lokal Ollama'da maliyet $0 olduğu için aktif bir bütçe kesme mekanizması işlemez.

## Kıyaslama: Üç Yaklaşım

| Yaklaşım | İlk yatırım | Aylık | 1 yıl | 3 yıl |
|---|---|---|---|---|
| Saf bulut LLM (1 fps, 100 kamera) | $0 | $2.592.000 | $31 M | $93 M |
| Frigate + GPU (saf lokal, sürekli) | $1.500 | ~$40 (elektrik) | $1.980 | $2.940 |
| **Bu proje — PoC** (Frigate CPU + lokal Ollama) | **$0** | **~$2–3** (elektrik) | **~$30** | – |
| **Bu proje — Production** (+ Coral) | **~$60** | **~$3–6** (elektrik) | **~$120** | **~$240** |

> Bu projenin **marjinal LLM maliyeti sıfırdır**. En pahalı bulut yaklaşımının binde birinden az, saf-GPU lokal alternatifin onda biri seviyesinde işletme gideri. Üstelik görüntüler tesisten çıkmadığı için **gizlilik** avantajı bulutla kıyaslanamaz.

## LLM Maliyeti Detay (Lokal Ollama)

### Per-çağrı

Lokal Ollama'da **çağrı başına para maliyeti yoktur** ($0). Ölçülen büyüklük token-doları değil, **gecikme**dir. Bridge yine de her çağrının token sayımını ve gecikmesini `llm_usage` tablosuna yazar (`cost_usd` Ollama'da 0 kalır — bkz. `bridge/bridge/llm.py`).

| Bileşen | Token (tahmini) | Para maliyeti | Not |
|---|---|---|---|
| Sistem prompt (`TRUCK_PROMPT_SYSTEM`) | ~400 | $0 | Her çağrıda gönderilir |
| Görüntü (snapshot, ≤480px downscale) | ~300–500 | $0 | `LLM_SNAPSHOT_MAX_HEIGHT=480` ile sınırlı |
| User msg | ~10 | $0 | "Bu kamyonu analiz et ve JSON döndür." |
| Output JSON | ≤256 | $0 | `num_predict=256` ile sınırlı |
| **Per çağrı** | | **$0** | Gecikme: CPU'da saniyeler (timeout 90s) |

### PoC Kullanımı (lokal $0)

Pilot 2–3 kamera. Sadece doğrulama amaçlı. **Maliyet her satırda $0** — burada tablo gecikme/yük perspektifindedir.

| Olay tipi | Adet/gün | Çağrı/ay | Para | Yük |
|---|---|---|---|---|
| Tır+dorse renk (pilot kamyon, 5/gün) | 5 | 150 | $0 | İhmal edilebilir |
| Pilot Grup C motion (1 kamera test) | 30 | 900 | $0 | Düşük |
| Manuel test sırasında | – | 500 | $0 | Düşük (kuyruğa girer) |
| **Toplam** | | **~1.550** | **$0** | Host CPU için rahat |

> PoC'ta tek dikkat edilecek şey para değil, **eşzamanlı çağrı kuyruğu**: aynı anda çok kamyon gelirse Ollama sıraya alır, gecikme artar. Olay-tetikli kullanımda nadirdir.

### Production Kullanımı (lokal $0)

**Grup A+B (15 kamera Coral'da)** — Ollama sadece olay-tetikli zenginleştirme yapar:

| Olay tipi | Adet/gün | Çağrı/ay | Para |
|---|---|---|---|
| Tır+dorse renk | 20 | 600 | $0 |
| Anomali doğrulama (planlı) | 10 | 300 | $0 |
| Yetkisiz alan (M8+) | 5 | 150 | $0 |
| Kapı geçişi enrichment | 150 | 4.500 | $0 |
| **Toplam (A+B)** | | **~5.550** | **$0** |

**Grup C (motion enrichment)** — kamera sayısı artık **para bütçesiyle değil, host inference kapasitesiyle** sınırlıdır:

| Motion/kamera/gün | Kamera × motion × 30 = çağrı/ay | Para | Sınırlayıcı |
|---|---|---|---|
| 15 (sakin) | 10 × 15 × 30 = 4.500 | $0 | CPU/kuyruk |
| 30 (orta) | 10 × 30 × 30 = 9.000 | $0 | CPU/kuyruk |
| 30 (orta) | 12 × 30 × 30 = 10.800 | $0 | CPU/kuyruk |
| 50 (yoğun) | 10 × 50 × 30 = 15.000 | $0 | CPU/kuyruk (gecikme artar) |

> **Hedef**: 10–12 Grup C kamerası tipik bir host'ta rahat çalışır. Sınırı para değil, Ollama gecikmesi belirler — Grafana `llm_usage` latency paneli izlenir.

| **Genel Toplam (Production)** | | **~15.000–16.500** | **$0** |

Lokal Ollama'da aylık LLM gideri her senaryoda **$0**'dır. (Planlı Anthropic hibritte `.env` `LLM_MONTHLY_BUDGET_USD` devreye girerdi.)

### Grup C Otomatik Kalibrasyon

Bridge her gün motion-event/kamera istatistiği üretir. Lokal Ollama'da amaç **para değil, inference kuyruğunu** korumaktır. Eğer:
- Bir kamera × motion/gün >50 → o kamera için LLM tetikleme **active_hours**'a sıkılaştırılır (örn. mesai dışı)
- Motion/`min_score` threshold yükseltilir (gürültüden geliyor olabilir)
- 2 hafta sonra hâlâ yüksekse → Grup D'ye düşürme önerisi log atılır (Ollama gecikmesini düşürmek için)

## Donanım Maliyeti

### PoC (sıfır ek yatırım)

- Mevcut Ubuntu sunucu (12 GB RAM, SnipeIT ile paylaşımlı)
- Mevcut kameralar ve NVR
- Mevcut network
- **Toplam: $0**

### Production Upgrade

- **1× Coral USB Accelerator (opsiyonel, Frigate detection için)**: ~₺2.500–3.500 (≈ $60)
- Disk: mevcut yerde ~25 GB snapshot + Ollama modeli `qwen2.5vl:7b` ~5.6 GB; ayrı disk gerekmez
- (Opsiyonel) UPS: zaten sunucuda var varsayımıyla

> Ek Coral alınmaz. Daha fazla kamera AI'a sokulacaksa **LLM maliyeti artmaz (lokal $0)**; sınır donanım kapasitesidir (CPU/Coral detection + Ollama inference). Çok büyürse opsiyonel GPU LLM gecikmesini düşürür.

### Gelecek (12 ay sonra büyürse)

| Ekleme | Tahmini maliyet |
|---|---|
| Yüz tanıma (CompreFace + RTX 3060 12GB) | $300 |
| Davranış analizi (VideoMAE, RTX 4060 Ti) | $500 |
| 2. AI sunucu (yüksek kullanılabilirlik) | $800 |

## Elektrik Tüketimi

| Konfigürasyon | Güç (W) | Saat/ay | kWh/ay | TL/ay (₺3/kWh) | $/ay |
|---|---|---|---|---|---|
| Sunucu idle | 40 | 720 | 29 | ₺87 | ~$3 |
| + Frigate yükü (CPU) | 80 | 720 | 58 | ₺174 | ~$6 |
| + Coral USB | +5 | 720 | 62 | ₺186 | ~$6,2 |
| + Ollama inference (CPU, olay-tetikli) | tepe anında +30–60, ortalama düşük | — | marjinal | marjinal | marjinal |

Asıl yük zaten SnipeIT için ödeniyor; AI + lokal LLM tarafının marjinal etkisi: ~$2–3/ay. Ollama yalnızca kamyon görüldüğünde kısa süre CPU'yu yükler (sürekli değil), bu yüzden elektrik etkisi ihmal edilebilir. **Bu, tek tekrarlayan LLM gideridir — token ücreti yoktur.**

## ROI ve Karar

Sistem ne işe yarıyor (ekonomik değer)?

1. **İş güvenliği**: yetkisiz personel/araç girişi → potansiyel hırsızlık/sabotaj önleme
2. **Operasyonel görünürlük**: tır giriş çıkışı log → sevkıyat doğrulama
3. **Sorumluluk** (liability): alan ihlali kayıtları → sigorta/yasal koruma
4. **Yöneticiyi gece arayan telefonu azalt**: spam alarm yerine anlamlı alarm

**Geri ödeme**: Sistem 1 ciddi olayı (örn. 1 hırsızlık girişimi) yakalarsa kendini katlayarak öder.

## Riskler ve Kapasite Senaryoları

Lokal Ollama'da **para riski yoktur** (maliyet $0); riskler **inference kuyruğu / gecikme** tarafına kayar:

| Senaryo | Etki | Önlem |
|---|---|---|
| Grup C kamerası "yağmurda titreşen yaprak" → her dk motion | Ollama kuyruğu birikir, gecikme artar (para $0) | Motion threshold yükselt, `active_hours` ile gece-only |
| Kamera saatte 50 yanlış-pozitif "truck" | Gereksiz LLM çağrısı, kuyruk yükü | Frigate `min_score`/`LLM_TRUCK_MIN_SCORE` 0.7+, zone'lar dar |
| 15 alan → 30 alan büyüme | LLM maliyeti $0 kalır; CPU/kuyruk zorlanır | FPS ayarı; gerekirse opsiyonel GPU |
| Çok yoğun eşzamanlı kamyon trafiği | Çağrılar sıraya girer, gecikme ↑ | `llm_timeout_s` ayarı + retry; GPU ekle |
| Ollama servisi host'ta düşük/erişilemez | Tır analizi başarısız (alarm/log yine yazılır) | `OllamaClient` retry; host'ta `ollama serve` health |
| Spam motion → bildirim sıklığı | Bildirim gürültüsü | Per-zone limit (bildirim DMSS push üzerinden, bkz. `05-dahua-integration.md`) |

## Karşılaştırma Tablosu (Ek)

Türk pazarındaki ticari alternatifler (yaklaşık, 2026):

| Çözüm | Yıllık maliyet | Esneklik |
|---|---|---|
| Hikvision DeepInView analitik | ₺50.000–120.000 lisans | Düşük |
| Avigilon ACC + AI | ₺200.000+ donanım+lisans | Orta |
| Bosch Intelligent Video Analytics | ₺150.000+ | Düşük |
| **Bu proje** | **~₺3.500 (tek seferlik) + ~₺2.000/yıl** | **Yüksek (açık)** |

10–30× ucuz, üstüne istenirse özelleştirilebilir.
