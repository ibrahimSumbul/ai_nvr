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

## Lokal LLM (Ollama) için kaynak

M3'ten itibaren semantik analiz (tır/dorse renk) **lokal Ollama vision modeli** ile yapılır — bulut LLM değil. Bu, Frigate detection'dan **ayrı** bir kaynak kalemidir; Coral, LLM'i değil **detection'ı** hızlandırır.

| Kalem | Gereksinim |
|---|---|
| Model | `qwen2.5vl:7b` (varsayılan, `.env` `LLM_OLLAMA_MODEL` ile değişir) |
| Disk | ~5.6 GB (model dosyası) |
| RAM (çıkarım anı) | ~6 GB — `keep_alive` (~5 dk) sonrası boşalır, sürekli değil |
| CPU gecikme | ~30 sn/çağrı (480px snapshot) — olay-tetikli, sürekli değil |
| Nerede koşar | **Host process** (container değil); bridge `host.docker.internal:11434` ile erişir |
| İnternet | Gerekmez — görüntüler tesisten çıkmaz |

**Önemli planlama notu**: Aynı 12 GB kutuda hem full docker stack (~7–8 GB) hem Ollama (~6 GB tepe) koşacaksa RAM zorlanır. Seçenekler:

- **16 GB+ host RAM** (co-located çalışacaksa önerilen)
- **Daha küçük model**: `qwen2.5vl:3b` (~3 GB) — daha hızlı, biraz daha düşük kalite
- **Ayrı inference makinesi**: Ollama'yı başka bir host/GPU kutusunda çalıştır, `LLM_OLLAMA_URL`'i ona yönelt
- **GPU / Apple Silicon host**: CPU'daki ~30 sn → birkaç saniyeye iner

> Truck olayları seyrek (günde birkaç) olduğundan ~6 GB tepe geçicidir; ama eşzamanlı detection yüküyle çakışmaması için RAM tamponu hesaba katılmalı. RAM bütçesi: [`docs/01-architecture.md`](01-architecture.md#ram-bütçesi).

## Coral USB Upgrade Yolu

| Ürün | Fiyat (US) | Türkiye yaklaşık | Stok |
|---|---|---|---|
| Coral USB Accelerator | $60 | ₺2.500–3.500 | Hepburn/Robotistan/Direnc |
| Coral M.2 (mini PCIe) | $40 | yok/zor | İthalat gerekir |

**Bütçe kararı**: **Maksimum 1 adet Coral USB ($60)**. Ek Coral alınmaz. Coral, Frigate **detection**'ını hızlandırır (LLM'i değil). Coral kapasitesini aşan kameralar CPU detection ile veya NVR-only kalır (aşağıdaki kapasite tablosu). Semantik analiz (tır/dorse renk) bundan bağımsız, **lokal Ollama**'da olay-tetikli koşar — marjinal maliyet $0.

### Coral USB Kapasitesi (Gerçekçi)

Tek Coral USB, Edge TPU üzerinde **~100 inference/saniye** yapar. Kamera başına FPS düşürüldüğünde:

| FPS / kamera | Maks kamera | Notu |
|---|---|---|
| 10 fps | 8–10 | Hızlı reaksiyon |
| 5 fps | **15** | **Önerilen kapasite** |
| 3 fps | 20–25 | Reaksiyon gecikir |
| 2 fps | 30+ | Sadece olay tetikçi |

> **Karar**: 5 fps'te **15 kamera Coral üzerinde** detection yapar. Geri kalanlar CPU detection veya NVR-only; semantik LLM analizi bundan bağımsız (olay-tetikli, lokal Ollama).

### İki Fazlı Plan

**Faz 1 — PoC (Coral yok, lokal Ollama, $0 LLM)**

| Grup | Kamera | Mekanizma |
|---|---|---|
| A: Pilot oda | 1–2 | Frigate CPU + state machine |
| B: Pilot kapı | 1 | Frigate CPU + door traversal |
| Diğer 97 | – | Sadece NVR kaydı, AI yok |

CPU-only Frigate ~3 kamerayı düşük FPS'te kaldırır. Pilot için yeterli. Bu kameralarda tır görülürse lokal Ollama olay-tetikli renk analizi yapar ($0); host'ta Ollama RAM/throughput için yukarıdaki **Lokal LLM** bölümüne bak.

**Faz 2 — Production (Coral USB + lokal Ollama, $0 LLM)**

| Grup | Kamera | Mekanizma | Hızlandırma |
|---|---|---|---|
| **A**: Aktif izlenen alanlar (oda) | 10 | Frigate + Coral (state machine) | TPU detection |
| **B**: Kapılar (alarm + giriş/çıkış log) | 5 | Frigate + Coral (door traversal) | TPU detection |
| **C**: Düşük öncelik (detection + olay log) | 10–15 | CPU/Coral detection | — |
| **D**: Sadece NVR kaydı | ~70 | NVR kayıt, AI yok | $0 |
| **Toplam** | **100** | | |

Grup A+B: **15 kamera Coral'da** detection yapar, kapasiteye sığar.
Grup C boyutu artık **bütçeyle değil, detection throughput'u** (Coral inference/sn + CPU decode) ile sınırlıdır — LLM marjinal maliyeti $0 olduğundan eski "$25 Haiku bütçesi" tavanı geçersiz. Semantik LLM analizi (tır/dorse renk) tüm gruplar için **olay-tetiklidir** ve lokal Ollama host throughput'u ile sınırlanır (bütçe değil). Bkz. [`07-cost-analysis.md`](07-cost-analysis.md).

> Tüm kameralar AI sunucudan **direct** erişilebilir olmak zorunda. NVR'a ek yük binmez. Bkz. [`05-dahua-integration.md`](05-dahua-integration.md).

## Maks. Kapasite ve Trade-off'lar

"Coral'ı ve lokal kaynakları sonuna kadar zorlarsak kaç kamera AI'a alınabilir?" sorusunun cevabı. Üç darboğaz vardır; en sıkı olan kazanır. **Not:** Lokal LLM marjinal maliyeti $0 olduğundan eski "Haiku bütçesi" darboğazı yerini **lokal inference throughput**'una bıraktı.

### Darboğaz 1: Coral USB

~100 inference/saniye yapar. FPS düştükçe daha çok kamera, ama reaksiyon hızı düşer.

| FPS | Maks kamera | Reaksiyon | Kullanım uygunluğu |
|---|---|---|---|
| 10 fps | 10 | ~100 ms | Hızlı kapı geçişi |
| **5 fps** | **15** | **200 ms** | **Önerilen** — oda + kapı dengeli |
| 3 fps | 22–25 | 330 ms | Kapı saniye hassasiyeti azalır |
| 2 fps | 30 | 500 ms | Hızlı kişi/araç kaçabilir |
| 1 fps | 50+ | 1 sn | State machine kullanılamaz |

### Darboğaz 2: Lokal LLM throughput

LLM **$0** olduğundan kamera sayısını maliyet sınırlamaz; sınır **host inference hızıdır**. `qwen2.5vl:7b` CPU'da ~30 sn/çağrı → sürekli ~2 çağrı/dk (~120/saat). GPU/Apple Silicon ile kat kat fazla.

| LLM kullanım profili | Throughput uygunluğu |
|---|---|
| **Tır renk** (kapı başına birkaç tır/saat) | ✅ Rahat — inference kapasitesinin çok altında |
| Birkaç kapıda yoğun tır trafiği | ⚠️ Saatte onlarca → CPU'da kuyruk birikebilir, GPU önerilir |
| **Sürekli motion → LLM** (onlarca kamera) | ❌ Desteklenmez — CPU'da 30 sn/çağrı buna yetmez |

> Tasarım sınırı: LLM **olay-tetiklidir** (tır gibi anlamlı olaylar), her motion için değil. Eski "motion → bulut Haiku" modeli lokal CPU'da zaten throughput'a takılırdı; lokalde bu yüzden olay-tetikli kaldı. Daha yüksek hacim gerekirse GPU host veya planlı bulut hibrit.

### Darboğaz 3: 8 GB RAM + CPU

- Frigate per-kamera: ~100–150 MB RAM
- ffmpeg decode per-kamera: ~2–5% CPU (Coral varsa bile decode CPU'da)
- 8 GB - (Postgres 500MB + Frigate base 500MB + bridge 300MB) = **~6.5 GB**
- 6.5 GB / 150 MB = **~40 kamera RAM tavanı**
- 4-core CPU: ~25–30 kamera CPU decode tavanı
- 8-core CPU: ~50+ kamera
- **Ollama co-located ise**: çıkarım anında ~6 GB host RAM tepe → docker tamponu o an daralır. Ayrı inference host'u veya 16 GB+ RAM bu darboğazı kaldırır (bkz. **Lokal LLM (Ollama) için kaynak**).

### Birleşik Senaryolar

LLM artık kamera sayısını **sınırlamaz** (olay-tetikli, $0). Tavan **detection** kapasitesidir (Coral + CPU decode + RAM):

| Konfig | Coral detect | CPU detect (ek) | **Toplam AI** | Trade-off |
|---|---|---|---|---|
| **Kaliteli** (5 fps) | 15 | ~12 | **~27** | Önerilen — reaksiyon iyi, kayıp az |
| **Sıkıştırılmış** (3 fps) | 22 | ~15 | **~37** | Kapı saniye hassasiyeti azalır |
| **Maks. teorik** (2 fps) | 30 | ~17 | **~47** | Hızlı olay kaçabilir, CPU/RAM sınırı |
| **Çok sakin** (1 fps, olay log) | 25 | ~30 | **~55** | State machine yok, sadece olay log |

> Semantik LLM analizi bu kameraların **herhangi birinde** tır görülünce olay-tetikli çalışır — ek kamera başına maliyet yoktur. Tek sınır host inference throughput'u (Darboğaz 2), ki tipik kapı tır trafiği bunun çok altındadır.

### Sonuç

- **Üretim kalitesinde**: ~25–30 kamera (kaliteli)
- **Rıza ile sıkıştırılırsa**: ~35–40 kamera (sıkıştırılmış)
- **Teorik maks**: ~45–50 kamera (kalite düşer)

100 kameranın **~%30–40'ı** AI kapsamında olabilir, geri kalanı NVR-only.

### Pratik Tavsiye

Başlangıç hedefi (10 oda + 5 kapı + 10 Grup C = 25 kamera) bu kapasitenin **rahat altındadır**. Sahaya çıkıldıkça Grup C'ye 5'er kamera ekle, CPU/RAM yükü (Grafana'dan izle) sınıra dayanana kadar büyüt — LLM tarafında bütçe sınırı yok ($0).

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

**Bütçe sabitlendi**: ek detection donanımı alınmaz. Kapsam genişlerse Frigate detection (Coral/CPU) tarafında ölçeklenir; semantik LLM lokal Ollama'da kalır ($0 marjinal). LLM hacmi/hızı artması gerekirse GPU **tek seferlik** yatırımdır — aylık ücret yoktur (bulut LLM'in tersine).

İleride donanım yatırımı yapılacaksa:

| Senaryo | Donanım |
|---|---|
| 20+ aktif izleme alanı (detection) | + 2. Coral USB veya RTX 4060 8GB |
| Lokal LLM hızı/hacmi artması gerekirse | + GPU (örn. RTX 4060 8GB) — Ollama'yı CPU'daki ~30 sn'den saniyeler-altına indirir |
| Yüz tanıma eklenirse | + RTX 3060 12GB (CompreFace için) |
| Davranış analizi eklenirse | + RTX 4060 Ti 16GB |

## Disk Planı

| Veri | Tahmini boyut | Tutma süresi |
|---|---|---|
| Olay snapshot (JPG) | ~100 KB × 50 olay/gün | 90 gün → ~450 MB |
| Olay clip (mp4, opsiyonel) | ~5 MB × 50 olay/gün | 30 gün → ~7.5 GB |
| Postgres DB | ~50 MB/ay | 5 yıl → ~3 GB |
| Frigate cache | değişken | 7 gün → ~10 GB |
| Ollama modeli (`qwen2.5vl:7b`, host) | ~5.6 GB | kalıcı (host `~/.ollama`) |
| **Toplam** | | **~30 GB** rahat |

50 GB ayırın, rahat olur. Mevcut diskte yer varsa ayrı disk gerekmez.

## Ağ Gereksinimleri

- **LLM (Ollama): lokal** — bridge, host'taki Ollama'ya `host.docker.internal:11434` ile erişir. **Outbound internet gerekmez** (görüntüler tesisten çıkmaz). _(Yalnızca opsiyonel/planlı bulut hibritte outbound HTTPS 443 gerekir.)_
- Ollama **ayrı bir inference makinesinde** ise: bridge host'tan o makineye LAN içi TCP 11434 erişimi (yine internet değil)
- Kamera VLAN'ına Frigate erişimi (RTSP sub-stream, direct)
- NVR'a HTTP/HTTPS erişimi (alarm push — sadece alarm, RTSP yok)
