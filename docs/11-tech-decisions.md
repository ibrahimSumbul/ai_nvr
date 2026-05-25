# 11 — Teknoloji Seçim Kararları

Kısa karar kaydı: hangi teknoloji seçildi, neden, ve hangileri elendi.

## 1. Lokal Detection Layer → **Frigate**

| Aday | Sonuç | Neden |
|---|---|---|
| **Frigate** | ✅ Seçildi | Coral USB native, ONVIF + RTSP olgun, zone polygon + tracking + MQTT, aktif community |
| MotionEye | ❌ Elendi | Sadece motion detection, AI yok → her motion'da Haiku spam olur |
| DeepStack | ❌ Elendi | Olgunluk düşük, Coral desteği sınırlı, dokümantasyon zayıf |
| Shinobi | ❌ Elendi | Eski mimari, Coral entegrasyonu yok, geliştirme yavaş |
| BlueIris | ❌ Elendi | Windows-only, commercial lisans, container değil |
| Agent DVR | ❌ Elendi | Commercial, esneklik sınırlı |
| viseron | ❌ Elendi | Frigate'in alternatifi ama daha az olgun, küçük community |
| MediaMTX + custom YOLO | ❌ Elendi | Aynı işi yapar ama tüm zone/tracking/MQTT/UI'ı sıfırdan yazmak lazım |
| Dahua gömülü AI (IVS) | ❌ Elendi | Proprietary, açık değil, sadece tetikleyebiliriz extend edemeyiz |

Detay → [`docs/10-why-frigate.md`](10-why-frigate.md)

## 2. Bridge Servisi Dili → **Python 3.12**

| Aday | Sonuç | Neden |
|---|---|---|
| **Python (asyncio)** | ✅ Seçildi | Anthropic/Pydantic/asyncpg/paho-mqtt olgun, hızlı yazılır, test ekosistemi güçlü |
| Node.js | ❌ Elendi | I/O için iyi ama görüntü işleme libs zayıf, Pydantic gibi validation yok |
| Go | ❌ Elendi | Hızlı ama Anthropic SDK resmi yok, MQTT libs daha az olgun, kapsam küçük olduğu için fayda yok |
| Rust | ❌ Elendi | Performans gerekmiyor, yazma süresi 3–5× uzar |
| Java/Kotlin | ❌ Elendi | RAM ayak izi büyük, JVM overhead 8 GB tampona ek yük |
| C# / .NET | ❌ Elendi | Cross-platform tamam ama Python kadar AI/ML ekosistemi yok |

Karar kriterleri: **hızlı yazma + AI/ML ekosistem + üretim kalitesi**. Python üçünü de veriyor.

## 3. LLM Sağlayıcı → **Claude Haiku 4.5**

| Aday | $/M token (in/out) | Sonuç | Neden |
|---|---|---|---|
| **Claude Haiku 4.5** | 0.80 / 4.00 | ✅ Seçildi | Vizyon güçlü, JSON çıktı güvenilir, prompt caching desteği, Anthropic SDK |
| Gemini 2.5 Flash | 0.30 / 2.50 | ❌ Şimdilik | ~3× ucuz ama: Google ekosistem bağımlılığı, SDK olgunluk Anthropic'in altında |
| GPT-4o-mini | 0.15 / 0.60 | ❌ Şimdilik | En ucuz ama: vendor neutrality için ayrı bir karar olur, JSON mode güvenirliği test edilmedi |
| Sonnet 4.6 | 3.00 / 15.00 | ❌ Elendi | 4× pahalı, gerek yok — sorularımız Haiku için yeterince basit |
| GPT-4 | 30 / 60 | ❌ Elendi | Saçma pahalı |
| Lokal Qwen2.5-VL 7B | $0 (donanım var) | 🟡 Gelecek | Offline çalışma için ileride, ekstra GPU lazım |

**Geri dönüş noktası**: Eğer aylık $25 bütçeyi 6 ay üst üste aşarsak → Gemini Flash veya GPT-4o-mini'ye geçiş ciddi değerlendirilir. Bridge'de `bridge/llm.py` provider-agnostic interface ile yazılır (M3).

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
