# 11 — Teknoloji Seçim Kararları

Kısa karar kaydı: hangi teknoloji seçildi, neden, ve hangileri elendi.

## 1. Lokal Detection Layer → **Frigate**

| Aday | Sonuç | Neden |
|---|---|---|
| **Frigate** | ✅ Seçildi | Coral USB native, ONVIF + RTSP olgun, zone polygon + tracking + MQTT, aktif community |
| MotionEye | ❌ Elendi | Sadece motion detection, AI yok → her motion'da LLM spam olur |
| DeepStack | ❌ Elendi | Olgunluk düşük, Coral desteği sınırlı, dokümantasyon zayıf |
| Shinobi | ❌ Elendi | Eski mimari, Coral entegrasyonu yok, geliştirme yavaş |
| BlueIris | ❌ Elendi | Windows-only, commercial lisans, container değil |
| Agent DVR | ❌ Elendi | Commercial, esneklik sınırlı |
| viseron | ❌ Elendi | Frigate'in alternatifi ama daha az olgun, küçük community |
| MediaMTX + custom YOLO | ❌ Elendi | Aynı işi yapar ama tüm zone/tracking/MQTT/UI'ı sıfırdan yazmak lazım |
| Dahua gömülü AI (IVS) | ❌ Elendi | Proprietary, açık değil, sadece tetikleyebiliriz extend edemeyiz |

Detay → [`docs/10-why-frigate.md`](10-why-frigate.md)

## 2. Bridge Servisi Dili → **Python 3.13**

| Aday | Sonuç | Neden |
|---|---|---|
| **Python (asyncio)** | ✅ Seçildi | httpx/Pydantic/asyncpg/paho-mqtt olgun, hızlı yazılır, test ekosistemi güçlü; Ollama HTTP API'ye doğrudan async çağrı kolay |
| Node.js | ❌ Elendi | I/O için iyi ama görüntü işleme libs zayıf, Pydantic gibi validation yok |
| Go | ❌ Elendi | Hızlı ama MQTT/LLM client ekosistemi daha az olgun, kapsam küçük olduğu için fayda yok |
| Rust | ❌ Elendi | Performans gerekmiyor, yazma süresi 3–5× uzar |
| Java/Kotlin | ❌ Elendi | RAM ayak izi büyük, JVM overhead 8 GB tampona ek yük |
| C# / .NET | ❌ Elendi | Cross-platform tamam ama Python kadar AI/ML ekosistemi yok |

Karar kriterleri: **hızlı yazma + AI/ML ekosistem + üretim kalitesi**. Python üçünü de veriyor.

## 3. LLM Sağlayıcı → **Lokal Ollama (`qwen2.5vl:7b`)**

> **M3'te değişti (2026-05-31): Claude Haiku → lokal Ollama.** Başlangıçta bulut Claude Haiku seçilmişti; M3'te gizlilik + sıfır marjinal maliyet + kota-yok gerekçeleriyle lokal Ollama'ya geçildi. Bulut Anthropic hibrit artık **planlı fallback** (switch + factory hazır, `AnthropicClient` yok). Aşağıdaki tablo bu kararı yansıtır.

| Aday | Maliyet | Sonuç | Neden |
|---|---|---|---|
| **Ollama `qwen2.5vl:7b` (lokal)** | $0 (sadece elektrik) | ✅ Seçildi (M3) | **Gizlilik** (görüntüler tesisten çıkmaz), **$0 marjinal maliyet**, **kota/rate-limit yok**, vizyon + `format=json` structured output yeterli, CPU'da çalışır (GPU şart değil) |
| Claude Haiku (bulut) | ~$0.80 / $4.00 /M | 🟡 Planlı fallback | Hızlı + güçlü vizyon ama: token maliyeti, görüntü dışarı çıkar (gizlilik), API kotası. `LLM_PROVIDER=anthropic` switch + `ANTHROPIC_*` ayarları rezerve; implementasyon henüz yok |
| Gemini 2.5 Flash (bulut) | ~$0.30 / $2.50 /M | ❌ | Yine bulut: görüntü dışarı çıkar + ekosistem bağımlılığı |
| GPT-4o-mini (bulut) | ~$0.15 / $0.60 /M | ❌ | Yine bulut: gizlilik + vendor kararı |
| Daha büyük lokal model (`qwen2.5vl:32b`) | $0 (RAM/VRAM ister) | 🟡 Gelecek | Kalite için; daha çok bellek/GPU gerekir |

**Neden lokal kazandı (M3 gerekçesi):**
- **Gizlilik / KVKK-GDPR**: Endüstriyel tesis görüntüleri (kişi, araç) hiçbir bulut servise gitmez — host'ta kalır.
- **Maliyet**: Marjinal LLM maliyeti $0; aylık tekrarlayan ücret yok (eski "$10–25/ay Haiku bütçesi" tamamen geçersiz).
- **Bağımsızlık**: API kotası / rate-limit / fiyat değişikliği riski yok.
- **Yeterlilik**: Tır renk + dorse tipi gibi görevler için `qwen2.5vl:7b` + `format=json` yeterli (M3 kalite tuning ile renk prompt'u sağlamlaştırıldı).

**Mimari hazırlık**: Bridge `bridge/bridge/llm.py` provider-agnostic interface (`LLMClient` Protocol) ile yazıldı; `build_llm_client` şu an yalnızca `ollama` döndürür, başka provider'a `ValueError`. Bu sayede planlı Anthropic fallback ileride sadece `AnthropicClient` eklenerek aktive edilebilir — switch + factory hazır.

## 4. Otomasyon Katmanı → **Custom Python servisi** (n8n değil)

| Aday | Sonuç | Neden |
|---|---|---|
| **Custom Python (asyncio)** | ✅ Seçildi | Stateful, düşük gecikme, version control, test edilebilir, mini RAM |
| n8n | ❌ Elendi | Workflow stateless → state machine ve tracking için ek DB round-trip; her node ~100–300 ms gecikme; ~500 MB RAM ek yük; testing/CI zor |
| Node-RED | ❌ Elendi | n8n ile aynı problemler, biraz daha hafif ama Python ekosistem yok |
| Apache Airflow | ❌ Elendi | Batch/scheduling için, gerçek-zamanlı event için tasarlanmamış |
| Home Assistant otomasyonları | ❌ Elendi | UI iyi ama HA'nın kendisi büyük bir bağımlılık |

> **Gelecek opsiyonu**: yönetici bildirim dağıtımı (Slack/Telegram/Notion) için n8n **secondary** katman olarak eklenebilir. Çekirdek state machine her zaman Python servisinde kalır.

## 5. Veritabanı → **PostgreSQL 16**

| Aday | Sonuç | Neden |
|---|---|---|
| **PostgreSQL** | ✅ Seçildi | JSONB (LLM yanıtları), timestamptz(3) ms hassasiyet, asyncpg olgun, Grafana plugin |
| SQLite | ❌ Elendi | Concurrent write zayıf, bridge + viewer ikisi yazarsa kilit problemi |
| MySQL | ❌ Elendi | SnipeIT zaten kullanıyor ama JSONB ve advanced indexing Postgres'te daha iyi |
| MongoDB | ❌ Elendi | Relational sorgular daha sık (zone × time × event_type), JOIN gerekir |
| TimescaleDB | 🟡 Gelecek | Postgres extension; olay sayısı ay başına >1M olursa düşünülür |

## 6. MQTT Broker → **Mosquitto**

| Aday | Sonuç | Neden |
|---|---|---|
| **Mosquitto** | ✅ Seçildi | Hafif (~50 MB), Frigate doğal destek, kurulum 1 dosya |
| EMQX | ❌ Elendi | Daha çok feature ama 200+ MB RAM, gereksiz |
| HiveMQ Community | ❌ Elendi | Java tabanlı, ağır |
| RabbitMQ (MQTT plugin) | ❌ Elendi | Kapsamı aşar, AMQP yetenekleri kullanılmıyor |

## 7. Viewer Servisi → **FastAPI**

| Aday | Sonuç | Neden |
|---|---|---|
| **FastAPI** | ✅ Seçildi | Python ekosistemde kalır (bridge ile aynı dil), async, otomatik OpenAPI |
| Flask | ❌ Elendi | Sync default, async setup ek karmaşa |
| Express (Node) | ❌ Elendi | Ayrı runtime, ayrı bağımlılık ağacı |
| nginx + statik HTML | ❌ Elendi | Token doğrulama için backend lazım, sadece nginx yetmez |

## 8. Dashboard → **Grafana**

| Aday | Sonuç | Neden |
|---|---|---|
| **Grafana** | ✅ Seçildi | Postgres data source native, alert kuralları güçlü, ücretsiz |
| Metabase | ❌ Elendi | İyi ama alert/notification katmanı Grafana'dan zayıf |
| Custom React dashboard | ❌ Elendi | M8'de düşünülebilir, M0–M7 için Grafana yeter |
| Superset | ❌ Elendi | Analytics odaklı, real-time dashboard değil |

---

## Karar Kriterleri Özeti

Bu seçimlerin hepsi şu sıralamayı izledi:

1. **Üretim kalitesi** — açık kaynak, olgun, aktif geliştirme
2. **Düşük kaynak tüketimi** — 8 GB tampon içinde rahatça çalışmalı
3. **Production-grade davranış** — health check, restart policy, log, backup
4. **Test edilebilirlik** — CI'da koşturulabilir
5. **Maliyet** — açık kaynak veya $25 bütçe içinde
6. **Genişlemeye uygun** — gelecekte modül eklenebilir (yüz tanıma, davranış, vb.)

n8n, BlueIris, ticari analitik ürünleri 3., 4. ve 5. kriterlerde kayıp veriyor. Bu projedeki seçimler bu altı kriterin **kesişimi**dir.
