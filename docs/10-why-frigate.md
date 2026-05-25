# 10 — Neden Frigate? Saf Haiku ile Olmaz mı?

Sık sorulan ve son derece haklı bir soru. Bu doküman teknik gerekçeleri kayıt altına alır.

## Kısa Cevap

**Olmaz.** Saf Haiku ile:
- Maliyet patlar (sürekli analiz: $2.5M/ay)
- Gecikme alarmı kaçırır (1–2 sn LLM çağrısı, olay 0.5 sn'de biter)
- Tracking yapılamaz (LLM stateless) → "boş alana ilk giriş" ve "kapı geçişi" kuralları kurulamaz

Frigate **lokal, anlık, ücretsiz tracking + detection** sağlar. Haiku **semantik anlam** katmanını ekler. İkisi birbirini tamamlar.

## Saf Haiku'nun 5 Teknik Limiti

### 1. Maliyet

| Senaryo | Aylık |
|---|---|
| 25 kamera × 1 fps Haiku | **~$648.000** |
| 25 kamera × 1 frame/dk | **~$11.000** |
| 25 kamera × 1 frame/5dk | **~$2.200** |
| 25 kamera motion-triggered (100 motion/cam/gün) | **~$90** |

Saf Haiku ile **anlamlı bir izleme** için ~$2k+ gerek. Sub-second tepki için $648k. Sürdürülemez.

### 2. Gecikme (Latency)

| Adım | Süre |
|---|---|
| Snapshot al | ~50 ms |
| Base64 encode + HTTP | ~100 ms |
| Anthropic kuyruk + inference | **800–1500 ms** |
| JSON parse + DB yaz | ~50 ms |
| **Toplam** | **~1–2 saniye** |

Bir kişi kapıdan **0.5 saniyede** geçer. Saf Haiku ile gerçek zamanlı tepki imkansız.

Frigate inference süresi: **10 ms** (Coral) / 100 ms (CPU). 10× ile 100× daha hızlı.

### 3. Rate Limit

Anthropic API tier'a göre dakikalık çağrı sınırı:

| Tier | Req/dk | 25 kamera × 5 fps gereksinimi |
|---|---|---|
| Default | 50 | **125 req/sn = 7500/dk → 150× aşım** |
| Tier 2 | 1000 | **7.5× aşım** |
| Enterprise | ? | Yine de pahalı |

Throttling devreye girince frame'ler düşer → olay kaçırılır.

### 4. State / Tracking Yapamama (En Kritik)

Sizin kurallarınız:

- "Boş alana **ilk giren** kişi" → bir önceki frame'i hatırla
- "Aynı kişi 1 dk alanda durursa **heartbeat**" → kişiyi takip et
- "Kapıdan **geçen** kişi (entry_ts + exit_ts)" → giriş ve çıkışı aynı kişiye bağla
- "3 sn cooldown aynı kişi için" → kim olduğunu hatırla

Bunların hepsi **object tracking** ister: kişiye persistent bir ID atamak ve kareler arası takip etmek.

**LLM'ler stateless'dir.** Her API çağrısı bağımsız. Kendisi tracking yapamaz. Yapmaya kalksak:
- Her frame için embedding üret (ek maliyet)
- DB'de embedding'leri sakla, similarity search yap (ek karmaşıklık)
- "Aynı kişi mi?" sorusunu kendin programla (LLM'den ucuza yapılır)

Bu noktada zaten saf LLM'den çıkmış olursunuz; bir tracking algoritması yazmaya başlamış olursunuz. **YOLOv8 + ByteTrack = Frigate.**

### 5. Hassasiyet

| Soru | Frigate (YOLOv8) | Saf Haiku |
|---|---|---|
| Kaç kişi var? | Sayısal kesin | Tahmini |
| Pixel bbox? | Var (kutuyla) | Yok |
| Hangi zone içinde? | Polygon kontrol | Yorum bağımlı |
| Confidence skor? | 0.0–1.0 numeric | Sözel |

Zone polygon'una "girdi mi" sorusunu Haiku'ya sormak garanti değil. Frigate matematik olarak çözer.

## Frigate'in Yapamadığı, Haiku'nun Yaptığı

Buraya kadar Frigate'in üstünlüğü. Şimdi Haiku'nun yaptığı:

| İş | Frigate | Haiku |
|---|---|---|
| **Tır çekici rengi** | ❌ "truck" tek obje | ✅ "kırmızı çekici, beyaz dorse" |
| **Dorse tipi** (tenteli/frigo/konteyner) | ❌ | ✅ semantik anlama |
| **"Bu kişi düşmüş mü?"** | ❌ | ✅ |
| **"Kavga var mı?"** | ❌ (pose model ekleyebiliriz ama zor) | ✅ |
| **"Bu cisim çanta mı, çöp mü, paket mi?"** | ❌ sadece "bag" | ✅ |
| **Anomali tarifi** | ❌ | ✅ |

Bu yüzden **hibrit**: Frigate "ne var, kaç tane, nerede"; Haiku "ne anlama geliyor".

## Frigate Yerine Başka Lokal Çözüm?

| Alternatif | Sorun |
|---|---|
| MotionEye | AI yok, sadece motion → Haiku spam |
| DeepStack | Daha az olgun, Coral desteği sınırlı |
| MediaMTX + custom Python YOLO | Aynı işi yapar, daha fazla bakım |
| Shinobi | Eski, az destek |
| Z-NX / iVMS NVR'larda gömülü AI | Proprietary, açık değil |

Frigate seçimi: **olgun + Coral desteği + zone polygon + tracking + MQTT + Home Assistant ekosistemi**.

## Karar Matrisi (Hatırlatma)

```
                ┌──────────────────────────────────────┐
                │  Hangi soruyu cevaplamak istiyoruz?  │
                └──────────┬───────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
   "Var mı? Kaç tane? Nerede?"   "Ne demek? Anlamı ne?"
              │                         │
              ▼                         ▼
        ┌──────────┐              ┌──────────┐
        │ FRIGATE  │              │  HAIKU   │
        │ - lokal  │              │ - bulut  │
        │ - 10 ms  │              │ - 1.5 sn │
        │ - $0     │              │ - $0.001 │
        └──────────┘              └──────────┘
```

## Sonuç

Frigate **olmazsa olmaz** değil — istisnası **çok düşük olay frekansı** olan setup:

- Eğer 100 kamerada toplam günde 50 olay varsa, saf Haiku $5/ay yapar. Ama:
  - Tracking yok → "ilk giriş" ve "geçiş" kuralları kurulamaz
  - Reaksiyon 2 sn → kapı kaçırılır
  - Bu sınırlamaları kabul edebilirseniz, evet, saf Haiku mümkün

Sizin kural setinizde (tracking + ms-hassasiyet + state machine) **Frigate gerekli**.
