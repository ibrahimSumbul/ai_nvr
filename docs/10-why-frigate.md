# 10 — Neden Frigate? Saf Bir Vision LLM ile Olmaz mı?

Sık sorulan ve son derece haklı bir soru. Bu doküman teknik gerekçeleri kayıt altına alır.

> **Not:** Bu proje semantik analizde **lokal Ollama** vision modeli kullanır (bkz. [`06-llm-strategy.md`](06-llm-strategy.md)). Aşağıdaki gerekçeler hem lokal hem bulut LLM için geçerlidir — bir vision LLM'i Frigate yerine "tek başına detection + tracking motoru" olarak kullanmak çalışmaz. Maliyet argümanı özellikle **bulut** (token başına ücret) için kritiktir; lokal Ollama'da marjinal maliyet $0 olsa bile gecikme ve stateless tracking sorunları aynen kalır — hatta CPU/GPU darboğazı yüzünden sürekli-analiz lokalde de imkânsızdır.

## Kısa Cevap

**Olmaz.** Saf bir vision LLM ile (lokal veya bulut):
- **Gecikme** alarmı kaçırır (her frame için ~1–2 sn inference, olay 0.5 sn'de biter)
- **Tracking** yapılamaz (LLM stateless) → "boş alana ilk giriş" ve "kapı geçişi" kuralları kurulamaz
- **Bulut** LLM ise üstüne maliyet patlar (sürekli analiz milyon $/ay) ve rate-limit/kota devreye girer; **lokal** LLM ise tek makinenin inference kapasitesini aşar

Frigate **lokal, anlık, ücretsiz tracking + detection** sağlar. LLM (bu projede lokal Ollama) yalnızca **semantik anlam** katmanını ekler. İkisi birbirini tamamlar.

## Saf Bir LLM'in 5 Teknik Limiti

### 1. Maliyet / Kapasite

**Bulut LLM** senaryosu — token başına ücret sürekli analizi imkânsız kılar (örnek fiyatlandırma ile):

| Senaryo | Aylık (bulut) |
|---|---|
| 25 kamera × 1 fps | **~$648.000** |
| 25 kamera × 1 frame/dk | **~$11.000** |
| 25 kamera × 1 frame/5dk | **~$2.200** |
| 25 kamera motion-triggered (100 motion/cam/gün) | **~$90** |

Bulut LLM ile **anlamlı bir sürekli izleme** için ~$2k+ gerek; sub-second tepki için $648k. Sürdürülemez.

**Lokal LLM (bu projenin tercihi — Ollama):** token ücreti yok, marjinal maliyet **$0**. Ama bu sefer **donanım kapasitesi** darboğaz olur: tek makinede `qwen2.5vl:7b` CPU'da bir vision çağrısını saniyeler mertebesinde işler (bkz. [`02-hardware.md`](02-hardware.md)). 25 kamerayı 1 fps sürekli LLM'e sokmak fiziksel olarak imkânsızdır. Bu yüzden Ollama **yalnızca olay-tetikli** çağrılır (kamyon girince), her frame için değil. Sürekli detection işini Frigate yapar.

### 2. Gecikme (Latency)

| Adım | Süre |
|---|---|
| Snapshot al | ~50 ms |
| Base64 encode + HTTP | ~100 ms |
| LLM inference (Ollama lokal CPU / bulut kuyruk) | **800–1500 ms+** |
| JSON parse + DB yaz | ~50 ms |
| **Toplam** | **~1–2 saniye** |

Bir kişi kapıdan **0.5 saniyede** geçer. Saf bir LLM ile gerçek zamanlı tepki imkânsız — bu lokal Ollama için de geçerli (CPU inference üstelik daha yavaş olabilir).

Frigate inference süresi: **10 ms** (Coral) / 100 ms (CPU). 10× ile 100× daha hızlı.

> **Hibritte gecikme bir kusur değil — senaryoya uygundur.** Yukarıdaki argüman *saf LLM'i sürekli detection motoru yapmak* içindir; gerçek-zamanlı tespit/tracking'i (ve gerektiğinde alarmı) Frigate (ms mertebesi) üstlenir. LLM yalnızca **olay-tetikli semantik zenginleştirme** yapar ve buradaki saniyeler süren gecikme hedef kullanımda bilinçli olarak kabul edilir: bu sistem **ofis/depo operasyonel görünürlüğü** içindir (tır/alan/kapı logu, yetkisiz giriş alarmı dahil) — ama **gerçek-zamanlı, milisaniye-tepkili otomatik savunma/müdahale sistemi değil**; bkz. [`07-cost-analysis.md`](07-cost-analysis.md), dolayısıyla bir kamyonun rengini birkaç saniye — gerekirse dakikalar — sonra öğrenmek hâlâ fazlasıyla zamanındadır. **Asıl kazanç güvenilirliktir:** lokal/$0/kotasız yol, olayı bulut maliyeti veya rate-limit'i yüzünden **hiç işleyememe** riskini ortadan kaldırır. Çerçeve: "biraz gecikme" değil, "olayı kaçırmama".

### 3. Kota / Kapasite Sınırı

**Bulut LLM** tier'a göre dakikalık çağrı sınırına (rate-limit) takılır:

| Tier (örnek) | Req/dk | 25 kamera × 5 fps gereksinimi |
|---|---|---|
| Default | 50 | **125 req/sn = 7500/dk → 150× aşım** |
| Tier 2 | 1000 | **7.5× aşım** |
| Enterprise | ? | Yine de pahalı |

**Lokal Ollama**'da API kotası yoktur, ama yerine **tek makinenin inference kapasitesi** sınırdır: aynı anda kuyruklanan çağrılar birbirini bekletir. Her iki durumda da sürekli yüksek-FPS analiz frame düşürür → olay kaçar. Çözüm aynı: detection'ı Frigate'e bırak, LLM'i seyrek/olay-tetikli kullan.

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

| Soru | Frigate (YOLOv8) | Saf Vision LLM |
|---|---|---|
| Kaç kişi var? | Sayısal kesin | Tahmini |
| Pixel bbox? | Var (kutuyla) | Yok |
| Hangi zone içinde? | Polygon kontrol | Yorum bağımlı |
| Confidence skor? | 0.0–1.0 numeric | Sözel |

Zone polygon'una "girdi mi" sorusunu bir LLM'e sormak garanti değil. Frigate matematik olarak çözer.

## Frigate'in Yapamadığı, LLM'in Yaptığı

Buraya kadar Frigate'in üstünlüğü. Şimdi LLM'in (bu projede lokal Ollama vision modeli) yaptığı:

| İş | Frigate | Ollama (lokal LLM) |
|---|---|---|
| **Tır çekici rengi** | ❌ "truck" tek obje | ✅ "kırmızı çekici, beyaz dorse" |
| **Dorse tipi** (tenteli/frigo/konteyner) | ❌ | ✅ semantik anlama |
| **"Bu kişi düşmüş mü?"** | ❌ | ✅ |
| **"Kavga var mı?"** | ❌ (pose model ekleyebiliriz ama zor) | ✅ |
| **"Bu cisim çanta mı, çöp mü, paket mi?"** | ❌ sadece "bag" | ✅ |
| **Anomali tarifi** | ❌ | ✅ |

Bu yüzden **hibrit**: Frigate "ne var, kaç tane, nerede"; Ollama "ne anlama geliyor". Üstelik Ollama lokal koştuğu için bu semantik analiz **görüntüleri tesisten çıkarmadan, $0 marjinal maliyetle** yapılır.

## Frigate Yerine Başka Lokal Çözüm?

| Alternatif | Sorun |
|---|---|
| MotionEye | AI yok, sadece motion → her motion'da LLM spam |
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
        ┌──────────┐              ┌──────────────┐
        │ FRIGATE  │              │    OLLAMA    │
        │ - lokal  │              │ - lokal host │
        │ - 10 ms  │              │ - ~1–2 sn    │
        │ - $0     │              │ - $0 (lokal) │
        └──────────┘              └──────────────┘
   (sürekli detection)      (olay-tetikli semantik analiz)
```

## Sonuç

Frigate **olmazsa olmaz** değil — istisnası **çok düşük olay frekansı** olan setup:

- Eğer 100 kamerada toplam günde 50 olay varsa, saf bir LLM ile analiz teorik olarak mümkündür (lokal Ollama'da maliyet zaten $0). Ama:
  - Tracking yok → "ilk giriş" ve "geçiş" kuralları kurulamaz
  - Reaksiyon 2 sn → kapı kaçırılır
  - Bu sınırlamaları kabul edebilirseniz, evet, saf LLM mümkün

Sizin kural setinizde (tracking + ms-hassasiyet + state machine) **Frigate gerekli**. Ollama bu mimaride Frigate'in yerini almaz; onun üstüne **semantik bir zenginleştirme katmanı** olarak oturur.
