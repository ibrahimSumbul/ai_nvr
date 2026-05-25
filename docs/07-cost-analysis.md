# 07 — Maliyet Analizi

## Özet — Sabit Bütçeler

| Faz | Donanım (tek seferlik) | Haiku bütçe (aylık) | Toplam aylık |
|---|---|---|---|
| **PoC** | $0 (mevcut 8 GB sunucu) | **$10** | ~$11 (elektrik dahil) |
| **Production** | $60 (1× Coral USB) | **$25** | ~$28 (elektrik dahil) |

Bu sayılar **hedef tavanlar**. Bridge'de bütçe guard:
- PoC: $8'de uyarı, $10'da Haiku disable
- Production: $20'de uyarı, $25'te Haiku disable

NVR'a yük binmez (direct kamera bağlantısı zorunlu). Sunucu elektrik ek yük marjinal (~$1–3/ay).

## Kıyaslama: Üç Yaklaşım

| Yaklaşım | İlk yatırım | Aylık | 1 yıl | 3 yıl |
|---|---|---|---|---|
| Saf bulut LLM (1 fps, 100 kamera) | $0 | $2.592.000 | $31 M | $93 M |
| Frigate + GPU (saf lokal) | $1.500 | ~$40 | $1.980 | $2.940 |
| **Bu proje — PoC** | **$0** | **~$10** | **~$120** | – |
| **Bu proje — Production** | **$60** | **~$25** | **~$360** | **~$660** |

> Bu proje en pahalı yaklaşımın **1/100.000**'i, en ucuz lokal alternatifin **1/5**'i.

## LLM Maliyeti Detay

### Per-çağrı

| Bileşen | Token | $/M | Maliyet |
|---|---|---|---|
| Sistem prompt (cached, %10 maliyet) | 400 | 0,80 | $0,000032 |
| Görüntü 640×480 | ~400 | 0,80 | $0,000320 |
| User msg | 50 | 0,80 | $0,000040 |
| Output JSON | 200 | 4,00 | $0,000800 |
| **Per çağrı toplam** | | | **~$0,0012** |

### PoC Bütçe Tahsisi ($10/ay)

Pilot 2–3 kamera. Sadece doğrulama amaçlı.

| Olay tipi | Adet/gün | Çağrı/ay | Aylık $ |
|---|---|---|---|
| Tır+dorse renk (pilot kamyon, 5/gün) | 5 | 150 | $0,18 |
| Pilot kapı geçişi enrichment | 50 | 1.500 | $1,80 |
| Anomali / debug | – | 200 | $0,24 |
| Pilot Grup C motion (1 kamera test) | 30 | 900 | $1,08 |
| Manuel test sırasında | – | 500 | $0,60 |
| **Alt toplam** | | **~3.250** | **~$3,90** |
| **Bütçe headroom** | | | **$6,10** |

PoC bütçesi rahat sığar; testler ve kalibrasyon sırasında ekstra çağrılara da yer var.

### Production Bütçe Tahsisi ($25/ay)

**Grup A+B (15 kamera Coral'da)** — Haiku sadece zenginleştirme:

| Olay tipi | Adet/gün | Çağrı/ay | Aylık $ |
|---|---|---|---|
| Tır+dorse renk | 20 | 600 | $0,72 |
| Anomali doğrulama | 10 | 300 | $0,36 |
| Yetkisiz alan (M8+) | 5 | 150 | $0,18 |
| Kapı geçişi enrichment | 150 | 4.500 | $5,40 |
| **Alt toplam (A+B)** | | **5.550** | **~$6,66** |

**Kalan bütçe**: $25 − $6,66 = **$18,34** — bu Grup C'ye gider.

**Grup C (motion-triggered Haiku)** — kamera sayısı bütçeyle kalibre edilir:

| Motion/kamera/gün (varsayım) | Kamera × motion × 30 = çağrı | Aylık $ | Kamera sayısı |
|---|---|---|---|
| 15 (sakin) | 10 × 15 × 30 = 4.500 | $5,40 | **istediğin kadar** |
| 30 (orta) | 10 × 30 × 30 = 9.000 | $10,80 | **10 rahat** |
| 30 (orta) | 12 × 30 × 30 = 10.800 | $12,96 | **12 sınırda** |
| 50 (yoğun) | 10 × 50 × 30 = 15.000 | $18,00 | **10'dur** |

> **Hedef**: 10–12 Grup C kamerası, $25 bütçeye sığar. Motion yoğunluğu ölçüldükçe kalibre edilir.

| **Genel Toplam (Production)** | | **~15.000–16.500** | **~$18–25** |

Güvenli pay: bütçe **$25/ay** sınır (.env'de `LLM_MONTHLY_BUDGET_USD=25`), alarm **$20**'de.

### Grup C Otomatik Kalibrasyon

Bridge her gün motion-event/kamera istatistiği üretir. Eğer:
- Bir kamera × motion/gün >50 → o kamera için Haiku tetikleme **active_hours**'a sıkılaştırılır (örn. mesai dışı)
- Motion threshold +%20 yükseltilir (gürültüden geliyor olabilir)
- 2 hafta sonra hâlâ yüksekse → Grup D'ye düşürme önerisi log atılır

## Donanım Maliyeti

### PoC (sıfır ek yatırım)

- Mevcut Ubuntu sunucu (12 GB RAM, SnipeIT ile paylaşımlı)
- Mevcut kameralar ve NVR
- Mevcut network
- **Toplam: $0**

### Production Upgrade

- **1× Coral USB Accelerator (kesin tavan)**: ~₺2.500–3.500 (≈ $60)
- Disk: mevcut yerde ~25 GB lazım, ayrı disk gerekmez
- (Opsiyonel) UPS: zaten sunucuda var varsayımıyla

> Ek Coral alınmaz. Daha fazla kamera AI'a sokulacaksa **maliyet Haiku tarafında doğrusal** artar; donanım maliyeti sabit kalır.

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

Asıl yük zaten SnipeIT için ödeniyor, AI tarafının marjinal etkisi: ~$2–3/ay.

## ROI ve Karar

Sistem ne işe yarıyor (ekonomik değer)?

1. **İş güvenliği**: yetkisiz personel/araç girişi → potansiyel hırsızlık/sabotaj önleme
2. **Operasyonel görünürlük**: tır giriş çıkışı log → sevkıyat doğrulama
3. **Sorumluluk** (liability): alan ihlali kayıtları → sigorta/yasal koruma
4. **Yöneticiyi gece arayan telefonu azalt**: spam alarm yerine anlamlı alarm

**Geri ödeme**: Sistem 1 ciddi olayı (örn. 1 hırsızlık girişimi) yakalarsa kendini katlayarak öder.

## Riskler ve Bütçe Aşımı Senaryoları

| Senaryo | Maliyet etkisi | Önlem |
|---|---|---|
| Grup C kamerası "yağmurda titreşen yaprak" → her dk motion | Aylık +$10–40 | Motion threshold yükselt, gece-only mode |
| Kamera saatte 50 yanlış-pozitif "truck" | Aylık +$40 | Frigate `min_score` 0.7+, zone'lar dar |
| Anthropic fiyatları %50 arttı | Aylık $18 → $27 | Bütçe artır veya Grup C küçült |
| 15 alan → 30 alan büyüme | Aylık $18 → $35 | Hâlâ ucuz, donanım yok |
| API rate limit yendi | Hizmet kesintisi | Queue + retry + bütçe guard |
| Spam motion → SMTP rate hit | Mail kesintisi | Per-zone 30 mail/saat limit (bkz. `09-notifications.md`) |

## Karşılaştırma Tablosu (Ek)

Türk pazarındaki ticari alternatifler (yaklaşık, 2026):

| Çözüm | Yıllık maliyet | Esneklik |
|---|---|---|
| Hikvision DeepInView analitik | ₺50.000–120.000 lisans | Düşük |
| Avigilon ACC + AI | ₺200.000+ donanım+lisans | Orta |
| Bosch Intelligent Video Analytics | ₺150.000+ | Düşük |
| **Bu proje** | **~₺3.500 (tek seferlik) + ~₺2.000/yıl** | **Yüksek (açık)** |

10–30× ucuz, üstüne istenirse özelleştirilebilir.
