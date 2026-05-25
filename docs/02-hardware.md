# 02 — Donanım

## Mevcut Durum (PoC için)

| Bileşen | Spec | Not |
|---|---|---|
| Sunucu | Linux Ubuntu 22.04 | SnipeIT halihazırda çalışıyor |
| RAM | 12 GB | 4 GB SnipeIT, 8 GB AI için müsait |
| CPU | (modeli teyit edilecek) | Frigate için en az 4 core x86_64 öneri |
| Disk | (boyutu teyit edilecek) | AI snapshot için ~50 GB yeterli |
| Network | LAN | Dahua kameralar + NVR ile aynı erişimde |
| GPU | Yok | PoC için gerekli değil |
| TPU | Yok (planlı) | Coral USB sonra eklenecek |

## PoC İçin Yeterli Mi?

**Evet, koşullu olarak.** Frigate CPU modunda 10 kamerayı **sub-stream'de düşük FPS** ile işleyebilir.

CPU detector ile beklenen yük (10 kamera, 640×480 @ 5fps, YOLOv8n):
- Tek detection: ~80–150 ms (modern x86 CPU)
- Toplam yük: ~%30–50 CPU sürekli
- Risk: tepe trafiği (örn. ardışık 5 hareket) gecikme yaratabilir

> Eğer CPU kullanımı %70'i aşıyorsa Coral USB'yi beklemeden FPS'i 3'e düşürün veya kamera sayısını azaltın. Doğru çözüm Coral USB.

## Coral USB Upgrade Yolu

| Ürün | Fiyat (US) | Türkiye yaklaşık | Stok |
|---|---|---|---|
| Coral USB Accelerator | $60 | ₺2.500–3.500 | Hepburn/Robotistan/Direnc |
| Coral M.2 (mini PCIe) | $40 | yok/zor | İthalat gerekir |

**Bütçe kararı**: **Maksimum 1 adet Coral USB ($60)**. Ek Coral alınmaz. Coral'a sığmayan kameralar Haiku ile desteklenir (aşağıdaki kapasite tablosu).

### Coral USB Kapasitesi (Gerçekçi)

Tek Coral USB, Edge TPU üzerinde **~100 inference/saniye** yapar. Kamera başına FPS düşürüldüğünde:

| FPS / kamera | Maks kamera | Notu |
|---|---|---|
| 10 fps | 8–10 | Hızlı reaksiyon |
| 5 fps | **15** | **Önerilen kapasite** |
| 3 fps | 20–25 | Reaksiyon gecikir |
| 2 fps | 30+ | Sadece olay tetikçi |

> **Karar**: 5 fps'te **15 kamera Coral üzerinde**, geri kalanlar motion-triggered Haiku ile çalışır.

### İki Fazlı Plan

**Faz 1 — PoC (8 GB RAM, Coral yok, $10/ay Haiku bütçesi)**

| Grup | Kamera | Mekanizma |
|---|---|---|
| A: Pilot oda | 1–2 | Frigate CPU + state machine |
| B: Pilot kapı | 1 | Frigate CPU + door traversal |
| Diğer 97 | – | Sadece NVR kaydı, AI yok |

CPU-only Frigate ~3 kamerayı düşük FPS'te kaldırır. Pilot için yeterli.

**Faz 2 — Production (Coral USB + $25/ay Haiku bütçesi)**

| Grup | Kamera | Mekanizma | Maliyet |
|---|---|---|---|
| **A**: Aktif izlenen alanlar (oda) | 10 | Frigate + Coral (state machine) | TPU |
| **B**: Kapılar (alarm + giriş/çıkış log) | 5 | Frigate + Coral (door traversal) | TPU |
| **C**: Düşük öncelik (motion → Haiku) | 10–12 | ffmpeg motion + Haiku snapshot | LLM |
| **D**: Sadece NVR kaydı | 73–75 | NVR kayıt, AI yok | $0 |
| **Toplam** | **100** | | |

Grup A+B: **15 kamera Coral'da**, kapasiteye sığar.
Grup C boyutu **$25 Haiku bütçesine** göre kalibre edilir (motion sıklığına bağlı, 10–12 arası). Bkz. [`07-cost-analysis.md`](07-cost-analysis.md).

> Tüm kameralar AI sunucudan **direct** erişilebilir olmak zorunda. NVR'a ek yük binmez. Bkz. [`05-dahua-integration.md`](05-dahua-integration.md).

## Maks. Kapasite ve Trade-off'lar

"Coral'ı ve $25 Haiku bütçesini sonuna kadar zorlarsak kaç kamera AI'a alınabilir?" sorusunun cevabı. Üç darboğaz vardır; en sıkı olan kazanır.

### Darboğaz 1: Coral USB

~100 inference/saniye yapar. FPS düştükçe daha çok kamera, ama reaksiyon hızı düşer.

| FPS | Maks kamera | Reaksiyon | Kullanım uygunluğu |
|---|---|---|---|
| 10 fps | 10 | ~100 ms | Hızlı kapı geçişi |
| **5 fps** | **15** | **200 ms** | **Önerilen** — oda + kapı dengeli |
| 3 fps | 22–25 | 330 ms | Kapı saniye hassasiyeti azalır |
| 2 fps | 30 | 500 ms | Hızlı kişi/araç kaçabilir |
| 1 fps | 50+ | 1 sn | State machine kullanılamaz |

### Darboğaz 2: Haiku Bütçesi ($25/ay Production)

$6,66'sı Grup A+B enrichment için ayrılır → **$18,34** Grup C'ye kalır.

| Motion/cam/gün | Cam başı $/ay | Maks Grup C kamera |
|---|---|---|
| 10 (çok sakin) | $0,36 | 50+ |
| 20 (sakin) | $0,72 | **25** |
| 30 (orta) | $1,08 | **17** |
| 50 (aktif) | $1,80 | 10 |
| 100 (çok aktif) | $3,60 | 5 |

### Darboğaz 3: 8 GB RAM + CPU

- Frigate per-kamera: ~100–150 MB RAM
- ffmpeg decode per-kamera: ~2–5% CPU (Coral varsa bile decode CPU'da)
- 8 GB - (Postgres 500MB + Frigate base 500MB + bridge 300MB) = **~6.5 GB**
- 6.5 GB / 150 MB = **~40 kamera RAM tavanı**
- 4-core CPU: ~25–30 kamera CPU decode tavanı
- 8-core CPU: ~50+ kamera

### Birleşik Senaryolar

| Konfig | Coral | Haiku C | **Toplam** | Trade-off |
|---|---|---|---|---|
| **Kaliteli** (5 fps, motion orta) | 15 | 12 | **~27** | Önerilen — reaksiyon iyi, kayıp az |
| **Sıkıştırılmış** (3 fps, motion kalibre) | 22 | 15 | **~37** | Kapı saniye hassasiyeti azalır |
| **Maks. teorik** (2 fps, threshold yüksek) | 30 | 17 | **~47** | Hızlı olay kaçabilir, CPU sınırı |
| **Çok sakin alanlar** (1 fps, motion <10/gün) | 25 | 30+ | **~55** | State machine yok, sadece olay log |

### Sonuç

- **Üretim kalitesinde**: ~25–30 kamera (kaliteli)
- **Rıza ile sıkıştırılırsa**: ~35–40 kamera (sıkıştırılmış)
- **Teorik maks**: ~45–50 kamera (kalite düşer)

100 kameranın **~%30–40'ı** AI kapsamında olabilir, geri kalanı NVR-only.

### Pratik Tavsiye

Başlangıç hedefi (10 oda + 5 kapı + 10 Grup C = 25 kamera) bu kapasitenin **rahat altındadır**. Sahaya çıkıldıkça Grup C'ye 5'er kamera ekle, $25 bütçe alarmı uyarı verene kadar büyüt.

### Coral USB'nin sağladığı

- Tek Coral: ~15 stream (5 fps) detection
- Inference süresi: ~7–10 ms (CPU'nun ~10 katı hızlı)
- CPU yükünü ~%70 azaltır
- Daha hızlı reaksiyon, daha az gecikme

### Kurulum (Coral geldiğinde)

```bash
# Ubuntu 22.04
echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" \
  | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt update
sudo apt install libedgetpu1-std

# USB takıldıktan sonra
lsusb | grep Google  # "Google Inc." görmek lazım
```

Sonra `frigate/config.yml` içinde:

```yaml
detectors:
  coral:
    type: edgetpu
    device: usb
```

## Üretim Donanım Hedefi (12 ay sonra)

**Bütçe sabitlendi**: ek donanım alınmaz. Kapsam genişlerse Haiku üzerinden ölçeklenir (maliyeti çok küçük artar).

İleride donanım yatırımı yapılacaksa:

| Senaryo | Donanım |
|---|---|
| 20+ aktif izleme alanı | + 2. Coral USB veya RTX 4060 8GB |
| Yüz tanıma eklenirse | + RTX 3060 12GB (CompreFace için) |
| Davranış analizi eklenirse | + RTX 4060 Ti 16GB |

## Disk Planı

| Veri | Tahmini boyut | Tutma süresi |
|---|---|---|
| Olay snapshot (JPG) | ~100 KB × 50 olay/gün | 90 gün → ~450 MB |
| Olay clip (mp4, opsiyonel) | ~5 MB × 50 olay/gün | 30 gün → ~7.5 GB |
| Postgres DB | ~50 MB/ay | 5 yıl → ~3 GB |
| Frigate cache | değişken | 7 gün → ~10 GB |
| **Toplam** | | **~25 GB** rahat |

50 GB ayırın, rahat olur. Mevcut diskte yer varsa ayrı disk gerekmez.

## Ağ Gereksinimleri

- Outbound 443 (Anthropic API)
- Kamera VLAN'ına Frigate erişimi
- NVR'a HTTP/HTTPS erişimi (alarm push)
- Internet bant genişliği: Haiku çağrıları küçük (her biri ~50 KB), 100 çağrı/saat = ~5 MB/saat. Sıkıntı yok.
