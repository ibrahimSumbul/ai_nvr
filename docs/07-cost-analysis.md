# 07 — Maliyet Analizi

> ✅ **M3'ten itibaren LLM lokal.** Semantik analiz (tır/dorse renk) host'taki Ollama'da koşar — **aylık marjinal LLM maliyeti $0**, görüntüler tesisten çıkmaz. Eski "aylık $10–25 Haiku bütçesi" anlatısı geçersiz. Strateji: [`docs/06-llm-strategy.md`](06-llm-strategy.md).

## Özet — Maliyet Tablosu

| Faz | Donanım (tek seferlik) | LLM (aylık) | Elektrik (marjinal) | Toplam aylık |
|---|---|---|---|---|
| **PoC** | $0 (mevcut sunucu, CPU detection) | **$0** (lokal Ollama) | ~$2–3 | **~$2–3** |
| **Production** | ~$60 (1× Coral USB) | **$0** (lokal Ollama) | ~$3 | **~$3** |

Lokal LLM marjinal maliyeti **$0** (sadece elektrik). Çağrı başına ücret, aylık fatura, kota **yoktur**. Coral USB tek seferlik bir detection hızlandırıcıdır (LLM değil). NVR'a yük binmez (direct kamera bağlantısı zorunlu).

> **Değer önerisi**: gizlilik (görüntüler tesisten çıkmaz) + **sıfır marjinal maliyet** + kotasız/offline çalışma. Karşılığında bulut LLM'in ~1–2 sn gecikmesi yerine CPU'da ~30 sn (olay-tetikli, alarm yolu değil — kabul edilebilir).

## Kıyaslama: Üç Yaklaşım

| Yaklaşım | İlk yatırım | Aylık | 1 yıl | 3 yıl |
|---|---|---|---|---|
| Saf bulut LLM (1 fps, 100 kamera) | $0 | ~$2.592.000 | ~$31 M | ~$93 M |
| Frigate + GPU (saf lokal, beefy rig) | ~$1.500 | ~$40 (elektrik) | ~$1.980 | ~$2.940 |
| **Bu proje — PoC** | **$0** | **~$3** (elektrik) | **~$36** | – |
| **Bu proje — Production** | **$60** | **~$3** (elektrik) | **~$96** | **~$168** |

> Bu proje, "saf bulut LLM" stroman'ının **~1/850.000**'i, ayrı bir GPU rig'in (~$40/ay) **~1/13**'ü kadar işletim maliyetine sahip. Coral USB tek seferlik; ondan sonra **aylık fatura yok**.

Saf bulut LLM neden bu kadar pahalı/uygulanamaz (sadece maliyet değil; tracking + gecikme): [`docs/10-why-frigate.md`](10-why-frigate.md).

## LLM Maliyeti: Neden $0?

Lokal Ollama'da her çağrı `llm_usage` tablosuna **`cost_usd = 0.0`** olarak loglanır — donanım zaten alınmış, internet/API ücreti yok, marjinal yük sadece elektrik (çıkarım anındaki birkaç saniyelik CPU/GPU tüketimi).

| Kalem | Lokal Ollama | Bulut LLM (kıyas) |
|---|---|---|
| Çağrı başına ücret | **$0** | ~$0,001 |
| Aylık LLM faturası | **$0** | olay hacmine göre $1–$25+ |
| Kota / rate limit | yok | API tier limiti |
| Veri tesisten çıkar mı | **hayır** | evet (her snapshot) |

**Gerçek "maliyet" lokalde paradan değil, throughput'tan gelir**: `qwen2.5vl:7b` CPU'da ~30 sn/çağrı. Olay-tetikli (tır) kullanımda bu rahat; sürekli motion→LLM denenmez. Detay: [`docs/02-hardware.md`](02-hardware.md#darboğaz-2-lokal-llm-throughput).

### Opsiyonel bulut hibrit (planlı — henüz yok)

Daha düşük gecikme veya daha yüksek kalite gerekirse, gelecekte `LLM_PROVIDER=anthropic` ile bulut hibrit eklenebilir (switch altyapısı hazır, implementasyon yok). Yalnızca **o zaman** çağrı-başı ücret ve `LLM_MONTHLY_BUDGET_USD` bütçe guard'ı devreye girer. Referans birim maliyet (Haiku 4.5, opt-in edilirse):

| Bileşen | Token | $/M | Maliyet |
|---|---|---|---|
| Sistem prompt (cached) | 400 | 0,80 | ~$0,00003 |
| Görüntü (480px) | ~400 | 0,80 | ~$0,00032 |
| Output JSON | ~200 | 4,00 | ~$0,0008 |
| **Per çağrı (~)** | | | **~$0,0012** |

> Bu tablo yalnızca **planlı opsiyonel hibrit** içindir. Varsayılan kurulumda LLM maliyeti **$0**'dır.

## Donanım Maliyeti

### PoC (sıfır ek yatırım)

- Mevcut Ubuntu sunucu (CPU detection)
- Mevcut kameralar ve NVR
- Mevcut network
- Lokal Ollama: ücretsiz yazılım, model indirme ~5.6 GB disk
- **Toplam: $0**

> RAM uyarısı: lokal Ollama co-located çalışacaksa çıkarım anında ~6 GB host RAM tepe gerekir. 12 GB sunucuda full stack ile çakışmaması için 16 GB+ RAM veya ayrı inference host'u önerilir (tek seferlik). Bkz. [`docs/02-hardware.md`](02-hardware.md#lokal-llm-ollama-için-kaynak).

### Production Upgrade

- **1× Coral USB Accelerator**: ~₺2.500–3.500 (≈ $60) — Frigate **detection**'ını hızlandırır
- Disk: model + snapshot + DB ~30 GB; mevcut diskte yer varsa ayrı disk gerekmez
- (Opsiyonel) UPS: zaten sunucuda var varsayımıyla

> Coral, LLM'i değil detection'ı hızlandırır. LLM marjinal maliyeti $0 kalır; daha fazla kamera AI'a alınsa bile **LLM tarafında maliyet artmaz** — sınır detection donanımı (Coral/CPU/RAM).

### Gelecek (büyürse — hepsi tek seferlik)

| Ekleme | Tahmini maliyet | Not |
|---|---|---|
| Lokal LLM hızı/hacmi (GPU) | $300–500 | Ollama'yı saniyeler-altına indirir; aylık ücret yok |
| Yüz tanıma (CompreFace + RTX 3060 12GB) | $300 | |
| Davranış analizi (VideoMAE, RTX 4060 Ti) | $500 | |
| 2. AI sunucu (yüksek kullanılabilirlik) | $800 | |

## Elektrik Tüketimi

| Konfigürasyon | Güç (W) | Saat/ay | kWh/ay | TL/ay (₺3/kWh) | $/ay |
|---|---|---|---|---|---|
| Sunucu idle | 40 | 720 | 29 | ₺87 | ~$3 |
| + Frigate yükü (CPU) | 80 | 720 | 58 | ₺174 | ~$6 |
| + Coral USB | +5 | 720 | 62 | ₺186 | ~$6,2 |
| + Ollama çıkarım (olay anı, kısa süreli) | tepe +60 | seyrek | marjinal | marjinal | ~$0 ek |

Asıl yük zaten mevcut servisler için ödeniyor; AI tarafının marjinal etkisi **~$2–3/ay**. Ollama çıkarımı olay-tetikli ve kısa (günde birkaç × ~30 sn) olduğundan elektrik etkisi ihmal edilebilir. GPU eklenirse idle GPU tüketimi (~10–30 W) eklenir.

## ROI ve Karar

Sistem ne işe yarıyor (ekonomik değer)?

1. **İş güvenliği**: yetkisiz personel/araç girişi → potansiyel hırsızlık/sabotaj önleme
2. **Operasyonel görünürlük**: tır giriş çıkışı + renk/tip log → sevkıyat doğrulama
3. **Sorumluluk** (liability): alan ihlali kayıtları → sigorta/yasal koruma
4. **Gizlilik**: görüntüler tesisten çıkmaz — KVKK/GDPR açısından bulut LLM'e göre belirgin avantaj
5. **Yöneticiyi gece arayan telefonu azalt**: spam alarm yerine anlamlı alarm

**Geri ödeme**: Tek seferlik ~$60 donanım + $0 aylık LLM. Sistem 1 ciddi olayı (örn. 1 hırsızlık girişimi) yakalarsa kendini fazlasıyla öder.

## Riskler

Bulut bütçe-aşımı riski **ortadan kalktı** (LLM $0). Kalan riskler maliyet değil, **kapasite/kalite** tarafında:

| Senaryo | Etki | Önlem |
|---|---|---|
| CPU'da LLM gecikmesi yüksek (~30 sn+) | Renk kaydı gecikir (alarm değil) | Snapshot 480px (yapıldı), GPU host, daha küçük model |
| Çok sayıda eşzamanlı tır → inference kuyruğu | Bazı kayıtlar gecikir | GPU host veya planlı bulut hibrit |
| Ollama host RAM yetersiz (co-located) | OOM / swap | 16 GB+ RAM veya ayrı inference host |
| Yağmurda titreşen yaprak → motion spam | CPU detection yükü (LLM değil) | Frigate `min_score`, zone'ları daralt |
| Yanlış-pozitif "truck" → gereksiz LLM | Boşa inference (para değil, zaman) | `LLM_TRUCK_MIN_SCORE` 0.6+, zone dar |
| Spam motion → SMTP rate hit (M6.5) | Mail kesintisi | Per-zone mail limit (bkz. `09-notifications.md`) |

## Karşılaştırma Tablosu (Ek)

Türk pazarındaki ticari alternatifler (yaklaşık, 2026):

| Çözüm | Yıllık maliyet | Esneklik | Gizlilik |
|---|---|---|---|
| Hikvision DeepInView analitik | ₺50.000–120.000 lisans | Düşük | Cihaz-içi |
| Avigilon ACC + AI | ₺200.000+ donanım+lisans | Orta | Cihaz-içi |
| Bosch Intelligent Video Analytics | ₺150.000+ | Düşük | Cihaz-içi |
| **Bu proje** | **~₺3.500 (tek seferlik) + ~₺2.000/yıl elektrik** | **Yüksek (açık)** | **Lokal — görüntü dışarı çıkmaz** |

10–30× ucuz, üstüne açık ve özelleştirilebilir; lokal Ollama ile görüntüler tesiste kalır.
