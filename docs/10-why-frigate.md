# 10 — Neden Frigate? Saf LLM ile Olmaz mı?

Sık sorulan ve son derece haklı bir soru. Bu doküman teknik gerekçeleri kayıt altına alır. (Soru ister bulut LLM ister lokal LLM için sorulsun — cevap aynı.)

## Kısa Cevap

**Olmaz.** Saf LLM ile (bulut **veya** lokal):
- **Maliyet/throughput patlar**: bulutta sürekli analiz ~$2.5M/ay; lokalde para $0 ama CPU'da ~30 sn/çağrı → her frame'i analiz etmek **fiziksel olarak** imkânsız
- **Gecikme alarmı kaçırır**: bulut LLM 1–2 sn, lokal LLM CPU'da ~30 sn; olay 0.5 sn'de biter
- **Tracking yapılamaz** (LLM stateless) → "boş alana ilk giriş" ve "kapı geçişi" kuralları kurulamaz

Frigate **lokal, anlık (~10 ms), ücretsiz tracking + detection** sağlar. LLM (bu projede **lokal Ollama `qwen2.5vl`**) **semantik anlam** katmanını ekler. İkisi birbirini tamamlar — bu yüzden **hibrit**.

> **Lokale geçince argüman zayıflamaz, güçlenir**: M3'te bulut Haiku yerine lokal Ollama'ya geçtik. Bu maliyet itirazını sıfırladı ($0), ama gecikme itirazını **artırdı** (CPU'da ~30 sn ≫ bulut ~1.5 sn). Yani "her şeyi LLM'e sor" lokalde daha da imkânsız — Frigate'in detection/tracking katmanı hâlâ zorunlu.

## Saf LLM'in 5 Teknik Limiti

### 1. Maliyet (bulut) / Throughput (lokal)

**Bulut LLM** ile sürekli analizin maliyeti:

| Senaryo | Aylık (bulut) |
|---|---|
| 25 kamera × 1 fps | **~$648.000** |
| 25 kamera × 1 frame/dk | **~$11.000** |
| 25 kamera × 1 frame/5dk | **~$2.200** |
| 25 kamera motion-triggered (100 motion/cam/gün) | **~$90** |

Bulutta **anlamlı bir izleme** için ~$2k+, sub-second tepki için $648k gerek → sürdürülemez.

**Lokal LLM** (bu projede Ollama) bu faturayı **$0** yapar — ama parayı **throughput'a** çevirir: `qwen2.5vl:7b` CPU'da ~30 sn/çağrı → sürekli ~2 çağrı/dk. 25 kamerayı 1 fps analiz etmek ~1.500 çağrı/sn ister; lokal CPU bunun **binlerce katı** gerisinde. Yani sürekli LLM ne bulutta (para) ne lokalde (throughput) mümkün → **olay-tetikli + Frigate ön-filtre** her iki durumda da zorunlu.

### 2. Gecikme (Latency)

| Adım | Bulut LLM | Lokal LLM (CPU) |
|---|---|---|
| Snapshot al + encode + HTTP | ~150 ms | ~150 ms |
| Inference | **800–1.500 ms** | **~30.000 ms** |
| JSON parse + DB yaz | ~50 ms | ~50 ms |
| **Toplam** | **~1–2 saniye** | **~30 saniye** |

Bir kişi kapıdan **0.5 saniyede** geçer. Saf LLM ile gerçek zamanlı tepki imkânsız — lokalde bulutta olduğundan **kat kat** daha imkânsız.

Frigate inference süresi: **~10 ms** (Coral) / ~100 ms (CPU). LLM'den 10×–3000× hızlı. Bu yüzden alarm/tracking yolu Frigate'te; LLM yalnızca **olay sonrası zenginleştirme** (renk kaydı gibi, gerçek-zaman gerektirmeyen) için.

### 3. Rate Limit (bulut) / Inference kapasitesi (lokal)

**Bulut LLM** — API tier'a göre dakikalık çağrı sınırı:

| Tier | Req/dk | 25 kamera × 5 fps gereksinimi |
|---|---|---|
| Default | 50 | **125 req/sn = 7.500/dk → 150× aşım** |
| Tier 2 | 1.000 | **7.5× aşım** |
| Enterprise | ? | Yine de pahalı |

Throttling devreye girince frame'ler düşer → olay kaçırılır.

**Lokal LLM** — API limiti yok, ama **donanım throughput'u** sert bir tavan: CPU'da ~2 çağrı/dk. Aynı 7.500/dk gereksinimi lokalde **~3.750× aşım**. Sonuç değişmez: Frigate ön-filtre olay sayısını saniyedeki binlerden günde birkaça indirir.

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

| Soru | Frigate (YOLOv8) | Saf LLM |
|---|---|---|
| Kaç kişi var? | Sayısal kesin | Tahmini |
| Pixel bbox? | Var (kutuyla) | Yok |
| Hangi zone içinde? | Polygon kontrol | Yorum bağımlı |
| Confidence skor? | 0.0–1.0 numeric | Sözel |

Zone polygon'una "girdi mi" sorusunu LLM'e (bulut ya da lokal) sormak garanti değil. Frigate matematik olarak çözer.

## Frigate'in Yapamadığı, Lokal LLM'in Yaptığı

Buraya kadar Frigate'in üstünlüğü. Şimdi lokal LLM'in (Ollama `qwen2.5vl`) yaptığı:

| İş | Frigate | Lokal LLM (Ollama) |
|---|---|---|
| **Tır çekici rengi** | ❌ "truck" tek obje | ✅ "kırmızı çekici, beyaz dorse" (M3 — aktif) |
| **Dorse tipi** (tenteli/frigo/konteyner) | ❌ | ✅ semantik anlama (M3 — aktif) |
| **"Bu kişi düşmüş mü?"** | ❌ | ✅ (M8 planlı) |
| **"Kavga var mı?"** | ❌ (pose model ekleyebiliriz ama zor) | ✅ (M8 planlı) |
| **"Bu cisim çanta mı, çöp mü, paket mi?"** | ❌ sadece "bag" | ✅ |
| **Anomali tarifi** | ❌ | ✅ (M8 planlı) |

Bu yüzden **hibrit**: Frigate "ne var, kaç tane, nerede"; lokal LLM "ne anlama geliyor" — hepsi tesiste, marjinal maliyet $0.

## Frigate Yerine Başka Lokal Çözüm?

| Alternatif | Sorun |
|---|---|
| MotionEye | AI yok, sadece motion → her harekette LLM spam (lokalde throughput'u boğar) |
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
        │ FRIGATE  │              │  OLLAMA  │
        │ - lokal  │              │ - lokal  │
        │ - 10 ms  │              │ - ~30 sn │
        │ - $0     │              │ - $0     │
        └──────────┘              └──────────┘
```

> Lokal LLM bulut Haiku'dan yavaştır (~30 sn vs ~1.5 sn) ama **$0 + gizli** (görüntü tesisten çıkmaz). Gerçek-zaman gerektirmeyen zenginleştirme için bu takas kabul edildi (M3). Daha hızlı gerekirse GPU host veya planlı bulut hibrit.

## Sonuç

Frigate **olmazsa olmaz** değil — istisnası **çok düşük olay frekansı** olan setup:

- Lokal Ollama maliyeti zaten $0 olduğundan "düşük hacimde saf LLM ucuz" argümanı artık geçersiz — para hiç konu değil. Geriye yalnızca iki itiraz kalıyor:
  - **Tracking yok** (LLM stateless) → "ilk giriş" ve "geçiş" kuralları kurulamaz
  - **Reaksiyon yavaş** (lokalde ~30 sn, bulutta ~1.5 sn) → kapı/anlık olay kaçırılır
  - Bu sınırlamaları kabul edebilirseniz, evet, saf LLM mümkün — ama tipik güvenlik kural seti kabul edemez

Sizin kural setinizde (tracking + ms-hassasiyet + state machine) **Frigate gerekli**. Lokal Ollama bunun üstüne, **gerçek-zaman gerektirmeyen** semantik zenginleştirmeyi $0 maliyetle ve tesiste tutarak ekler.
