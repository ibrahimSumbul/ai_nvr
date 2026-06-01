# 02 — Donanım

## Mevcut Durum (PoC için)

| Bileşen | Spec | Not |
|---|---|---|
| Sunucu | Linux Ubuntu 22.04 | SnipeIT halihazırda çalışıyor |
| RAM | 12 GB | 4 GB SnipeIT, 8 GB AI için müsait (Frigate + lokal Ollama model dahil) |
| CPU | (modeli teyit edilecek) | Frigate için en az 4 core x86_64 öneri; lokal Ollama vision inference de CPU'da koşar |
| Disk | (boyutu teyit edilecek) | AI snapshot için ~50 GB; ayrıca Ollama modeli `qwen2.5vl:7b` ~5.6 GB |
| Network | LAN | Dahua kameralar + NVR ile aynı erişimde; LLM lokal olduğu için outbound internet gerekmez |
| GPU | Yok | PoC için gerekli değil (Ollama CPU'da çalışır, yavaş ama olay-tetikli olduğu için yeterli) |
| TPU | Yok (planlı) | Coral USB sonra eklenecek — **Frigate detection** hızlandırır, LLM'le ilgisi yok |

> **LLM lokal:** Tır/dorse renk analizi host'taki **Ollama** (`qwen2.5vl:7b`) ile yapılır; container ona `host.docker.internal:11434` üzerinden erişir. Model RAM'de ~6 GB yer kaplar (yüklenince). Aylık LLM maliyeti **$0** (sadece elektrik), görüntüler tesisten çıkmaz. Detay: [`06-llm-strategy.md`](06-llm-strategy.md).

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

**Donanım kararı**: **Maksimum 1 adet Coral USB ($60, opsiyonel, tek seferlik)**. Ek Coral alınmaz. Coral **yalnızca Frigate detection** içindir (LLM değil). Coral'ın detection kapasitesine sığmayan kameralar daha düşük FPS'e çekilir veya NVR-only bırakılır (aşağıdaki kapasite tablosu). Semantik analiz (tır rengi) lokal Ollama'da, olay-tetikli ve $0 marjinal maliyetle koşar.

### Coral USB Kapasitesi (Gerçekçi)

Tek Coral USB, Edge TPU üzerinde **~100 inference/saniye** yapar. Kamera başına FPS düşürüldüğünde:

| FPS / kamera | Maks kamera | Notu |
|---|---|---|
| 10 fps | 8–10 | Hızlı reaksiyon |
| 5 fps | **15** | **Önerilen kapasite** |
| 3 fps | 20–25 | Reaksiyon gecikir |
| 2 fps | 30+ | Sadece olay tetikçi |

> **Karar**: 5 fps'te **15 kamera Coral üzerinde** detection yapılır; geri kalan kameralar ya düşük FPS'te CPU detector'da kalır ya da NVR-only bırakılır. Tespit edilen kamyonlar (hangi kamerada olursa olsun) lokal Ollama'ya gider.

### İki Fazlı Plan

**Faz 1 — PoC (8 GB RAM, Coral yok, lokal Ollama $0)**

| Grup | Kamera | Mekanizma |
|---|---|---|
| A: Pilot oda | 1–2 | Frigate CPU + state machine |
| B: Pilot kapı | 1 | Frigate CPU + door traversal |
| Diğer 97 | – | Sadece NVR kaydı, AI yok |

CPU-only Frigate ~3 kamerayı düşük FPS'te kaldırır. Pilot için yeterli. Kamyon görülürse lokal Ollama tır rengini analiz eder (olay-tetikli, $0).

**Faz 2 — Production (opsiyonel Coral USB + lokal Ollama $0)**

| Grup | Kamera | Mekanizma | LLM maliyeti |
|---|---|---|---|
| **A**: Aktif izlenen alanlar (oda) | 10 | Frigate + Coral (state machine) | $0 (olay-tetikli Ollama) |
| **B**: Kapılar (alarm + giriş/çıkış log) | 5 | Frigate + Coral (door traversal) | $0 (olay-tetikli Ollama) |
| **C**: Düşük öncelik (motion enrichment) | 10–12 | ffmpeg motion + lokal Ollama snapshot | $0 (lokal) |
| **D**: Sadece NVR kaydı | 73–75 | NVR kayıt, AI yok | $0 |
| **Toplam** | **100** | | |

Grup A+B: **15 kamera Coral'da** detection, kapasiteye sığar.
Grup C boyutu artık **bulut bütçesiyle değil, host'un Ollama inference kapasitesiyle** sınırlıdır (lokal LLM maliyeti $0; sınır CPU/RAM ve eşzamanlı çağrı kuyruğu). Bkz. [`07-cost-analysis.md`](07-cost-analysis.md).

> Tüm kameralar AI sunucudan **direct** erişilebilir olmak zorunda. NVR'a ek yük binmez. Bkz. [`05-dahua-integration.md`](05-dahua-integration.md).

## Maks. Kapasite ve Trade-off'lar

"Coral'ı ve mevcut sunucuyu sonuna kadar zorlarsak kaç kamera AI'a alınabilir?" sorusunun cevabı. Lokal Ollama'da **bulut bütçesi darboğazı yoktur** (maliyet $0); yerine **Ollama inference kapasitesi** darboğaz olur. Üç darboğaz vardır; en sıkı olan kazanır.

### Darboğaz 1: Coral USB (Frigate detection)

~100 inference/saniye yapar. FPS düştükçe daha çok kamera, ama reaksiyon hızı düşer.

| FPS | Maks kamera | Reaksiyon | Kullanım uygunluğu |
|---|---|---|---|
| 10 fps | 10 | ~100 ms | Hızlı kapı geçişi |
| **5 fps** | **15** | **200 ms** | **Önerilen** — oda + kapı dengeli |
| 3 fps | 22–25 | 330 ms | Kapı saniye hassasiyeti azalır |
| 2 fps | 30 | 500 ms | Hızlı kişi/araç kaçabilir |
| 1 fps | 50+ | 1 sn | State machine kullanılamaz |

### Darboğaz 2: Lokal Ollama Inference Kapasitesi

LLM maliyeti $0 olduğu için **kamera sayısını para sınırlamaz**; sınır, host'un kaç **eşzamanlı / saatte kaç** vision çağrısını işleyebildiğidir. `qwen2.5vl:7b` GPU'suz CPU'da bir çağrıyı **saniyeler** mertebesinde işler (soğuk/büyük görüntüde `.env` timeout'u 90s'e kadar tanır). Çağrılar Ollama'da sıraya girer; aynı anda çok sayıda kamyon analizi gelirse kuyruk birikir.

Pratik etki: LLM **olay-tetikli** (kamyon görülünce) olduğu için, tipik bir tesiste günde onlarca-yüzlerce çağrı host için sorun değildir. Darboğaz ancak **çok yoğun, sürekli kamyon trafiğinde** veya Grup C motion-enrichment'ı agresif açılırsa devreye girer.

| Senaryo | Lokal Ollama yükü | Önlem |
|---|---|---|
| Kamyon girişleri (Grup A+B, olay-tetikli) | Düşük (gün içine yayılır) | Yeterli — varsayılan |
| Grup C motion enrichment, sakin alanlar | Orta | `min_score` + `active_hours` ile sınırla |
| Çok yoğun trafik / agresif motion | Kuyruk birikir, gecikme artar | FPS düşür, GPU ekle, veya çağrı sıklığını kıs |

> GPU eklenirse (RTX sınıfı) inference saniyeden milisaniyeye düşer ve bu darboğaz büyük ölçüde kalkar. PoC/Production'da CPU yeterli kabul edildi (olay-tetikli kullanım).

### Darboğaz 3: 8 GB RAM + CPU

- Frigate per-kamera: ~100–150 MB RAM
- ffmpeg decode per-kamera: ~2–5% CPU (Coral varsa bile decode CPU'da)
- **Lokal Ollama modeli host RAM'de ~6 GB** (`qwen2.5vl:7b` yüklenince) — bu, container'lardan ayrı host belleğindedir; AI sunucusunun toplam RAM planına dahil edilmeli
- Container tarafı: 8 GB - (Postgres 500MB + Frigate base 500MB + bridge 300MB) = **~6.5 GB**
- 6.5 GB / 150 MB = **~40 kamera RAM tavanı** (Frigate decode için)
- 4-core CPU: ~25–30 kamera CPU decode tavanı; Ollama inference CPU'yu paylaşır, ağır çağrı sırasında detection'ı yavaşlatabilir
- 8-core CPU: ~50+ kamera

### Birleşik Senaryolar

| Konfig | Coral (detect) | Grup C (lokal Ollama enrich) | **Toplam** | Trade-off |
|---|---|---|---|---|
| **Kaliteli** (5 fps, motion orta) | 15 | 12 | **~27** | Önerilen — reaksiyon iyi, kayıp az |
| **Sıkıştırılmış** (3 fps, motion kalibre) | 22 | 15 | **~37** | Kapı saniye hassasiyeti azalır |
| **Maks. teorik** (2 fps, threshold yüksek) | 30 | 17 | **~47** | Hızlı olay kaçabilir, CPU + Ollama kuyruğu sınırı |
| **Çok sakin alanlar** (1 fps, motion <10/gün) | 25 | 30+ | **~55** | State machine yok, sadece olay log |

> Grup C sütunundaki sayılar artık para bütçesiyle değil, **CPU decode + Ollama kuyruğu** ile sınırlıdır. Lokal LLM maliyeti her senaryoda $0'dır.

### Sonuç

- **Üretim kalitesinde**: ~25–30 kamera (kaliteli)
- **Rıza ile sıkıştırılırsa**: ~35–40 kamera (sıkıştırılmış)
- **Teorik maks**: ~45–50 kamera (kalite düşer)

100 kameranın **~%30–40'ı** AI kapsamında olabilir, geri kalanı NVR-only. Sınırlayan faktör artık LLM maliyeti değil, **detection donanımı (CPU/Coral) ve lokal inference kapasitesidir**.

### Pratik Tavsiye

Başlangıç hedefi (10 oda + 5 kapı + 10 Grup C = 25 kamera) bu kapasitenin **rahat altındadır**. Sahaya çıkıldıkça Grup C'ye 5'er kamera ekle; Ollama gecikmesi (Grafana **AI NVR — Genel Bakış** dashboard'unda `llm_usage` latency) belirgin artana kadar büyüt.

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

**Donanım sabitlendi**: PoC/Production için ek donanım zorunlu değil (Ollama CPU'da çalışır, LLM maliyeti $0). Kapsam genişlerse darboğaz para değil, **detection + lokal inference kapasitesidir**; çözüm donanım eklemektir.

İleride donanım yatırımı yapılacaksa:

| Senaryo | Donanım |
|---|---|
| 20+ aktif izleme alanı (detection) | + 2. Coral USB veya RTX 4060 8GB |
| Lokal LLM gecikmesi yüksek / çağrı yoğunsa | + GPU (RTX sınıfı) — Ollama inference saniyeden milisaniyeye iner |
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

- **Outbound internet LLM için gerekmez** — Ollama lokal host'ta çalışır, görüntüler tesisten çıkmaz (gizlilik). (Model ilk indirme `ollama pull` dışında.)
- Kamera VLAN'ına Frigate erişimi
- NVR'a HTTP/HTTPS erişimi (alarm push)
- Bridge → Ollama: host içi `host.docker.internal:11434` (LAN dışına çıkmaz)
- _(Planlı)_ Anthropic bulut hibrit eklenirse outbound 443 gerekir; çağrılar küçük (~50 KB) olduğu için bant genişliği sorun olmaz. Şu an yalnızca `ollama` destekleniyor.
