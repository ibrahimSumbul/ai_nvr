# 11 — Teknoloji Seçim Kararları

Kısa karar kaydı: hangi teknoloji seçildi, neden, ve hangileri elendi.

## 1. Lokal Detection Layer → **Frigate**

| Aday | Sonuç | Neden |
|---|---|---|
| **Frigate** | ✅ Seçildi | Coral USB native, ONVIF + RTSP olgun, zone polygon + tracking + MQTT, aktif community |
| MotionEye | ❌ Elendi | Sadece motion detection, AI yok → her motion'da LLM spam olur (lokalde throughput'u boğar) |
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
| **Python (asyncio)** | ✅ Seçildi | Pydantic/asyncpg/aiomqtt/httpx olgun, vision/ML ekosistemi güçlü, hızlı yazılır, test ekosistemi sağlam (Anthropic SDK de gelecekteki bulut hibrit için hazır) |
| Node.js | ❌ Elendi | I/O için iyi ama görüntü işleme libs zayıf, Pydantic gibi validation yok |
| Go | ❌ Elendi | Hızlı ama Pydantic-eşi validation + vision/ML + LLM client ekosistemi zayıf, MQTT libs daha az olgun, kapsam küçük olduğu için fayda yok |
| Rust | ❌ Elendi | Performans gerekmiyor, yazma süresi 3–5× uzar |
| Java/Kotlin | ❌ Elendi | RAM ayak izi büyük, JVM overhead 8 GB tampona ek yük |
| C# / .NET | ❌ Elendi | Cross-platform tamam ama Python kadar AI/ML ekosistemi yok |

Karar kriterleri: **hızlı yazma + AI/ML ekosistem + üretim kalitesi**. Python üçünü de veriyor.

## 3. LLM Sağlayıcı → **Lokal Ollama (`qwen2.5vl`)** _(M3'te Haiku'dan geçildi)_

**Karar geçmişi**: M0'da bulut **Claude Haiku 4.5** seçilmişti (vizyon + JSON + prompt caching). **M3'te lokal Ollama'ya geçildi** — gerekçe: gizlilik (görüntüler tesisten çıkmaz), **$0 marjinal maliyet**, kotasız/offline çalışma. Karşılığı CPU'da daha yüksek gecikme (~30 sn vs ~1.5 sn), ki olay-tetikli renk kaydı için kabul edilebilir.

| Aday | Tip | Sonuç | Neden |
|---|---|---|---|
| **Ollama `qwen2.5vl:7b`** | Lokal | ✅ **Seçildi (M3)** | $0 marjinal, gizli, kotasız, `format=json` structured output; ~5.6 GB model |
| Claude Haiku 4.5 | Bulut (0.80/4.00 /M) | 🟡 Planlı hibrit | M0'ın eski seçimi; gizlilik + $0 için lokale bırakıldı. `LLM_PROVIDER=anthropic` switch hazır ama **implementasyon henüz yok** |
| Gemini 2.5 Flash | Bulut (0.30/2.50) | ❌ Şimdilik | Bulut hibrit gerekirse aday; lokal $0 varken gerek yok |
| GPT-4o-mini | Bulut (0.15/0.60) | ❌ Şimdilik | Aynı — bulut hibrit alternatifi |
| Lokal `qwen2.5vl:3b` | Lokal | 🟡 Alternatif | Daha hızlı/küçük (~3 GB), düşük-RAM host için; kalite biraz düşer |
| Lokal `qwen2.5vl:32b` | Lokal | 🟡 Gelecek | Daha kaliteli; GPU + bol RAM gerektirir |

**Neden lokal kazandı (M3 karar kaydı)**:
- **Gizlilik**: endüstriyel CCTV görüntüsü hassas veridir; bulut LLM'de her snapshot dış servise giderdi. Lokalde tesisten çıkmaz (KVKK/GDPR avantajı).
- **Maliyet**: çağrı başına $0, aylık fatura yok, bütçe guard gereksiz. Bkz. [`07-cost-analysis.md`](07-cost-analysis.md).
- **Bağımsızlık**: API kota/rate-limit yok, internet kesintisinde de çalışır.
- **Takas**: CPU gecikmesi ~30 sn (480px snapshot). Alarm yolu Frigate'te olduğundan bu zenginleştirme adımı için sorun değil. Bkz. [`10-why-frigate.md`](10-why-frigate.md).

**Provider-agnostic mimari**: [`bridge/bridge/llm.py`](../bridge/bridge/llm.py)'de `LLMClient` Protocol + `build_llm_client` factory. Şu an yalnızca `OllamaClient` uygulanmıştır; `LLM_PROVIDER=anthropic` için switch hazır ama `AnthropicClient` henüz yok (factory `ValueError` yükseltir). Bulut hibrit gerekirse (daha düşük gecikme / daha yüksek kalite) drop-in eklenecek — bu yüzden `.env`'de `ANTHROPIC_*` değişkenleri korunur.

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
5. **Maliyet** — açık kaynak veya $0 marjinal (lokal LLM); tek seferlik donanım dışında aylık ücret yok
6. **Genişlemeye uygun** — gelecekte modül eklenebilir (yüz tanıma, davranış, vb.)

n8n, BlueIris, ticari analitik ürünleri 3., 4. ve 5. kriterlerde kayıp veriyor. Bu projedeki seçimler bu altı kriterin **kesişimi**dir.
