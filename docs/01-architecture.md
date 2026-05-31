# 01 — Mimari

## Tasarım İlkeleri

1. **Orijinal sistemi bozma.** Dahua NVR kayda devam eder, DSS/SmartPSS paneli aynen çalışır. AI katmanı sadece RTSP'yi okur ve geri alarm besler.
2. **Hibrit zekâ.** Frigate lokalde ucuz/hızlı detection yapar (kişi, araç, kamyon). **Lokal LLM (Ollama `qwen2.5vl`, host'ta)** **sadece** anlam katmanı gerektiren işlerde devreye girer (tır+dorse renk ayrımı, anomali doğrulama). Görüntüler tesisten çıkmaz.
3. **Olay tetikli.** Sürekli analiz yok. Hareket → Frigate → state machine → gerekirse LLM.
4. **State machine + idempotent.** Aynı durum tekrar tekrar alarm üretmez. "Alan dolu" durumunda spam yok.
5. **Production-grade davran.** Tüm servisler container, restart policy `unless-stopped`, health check, log rotation, backup planı.

## Bileşenler

```
┌────────────────────────────────────────────────────────────────────┐
│                         Dahua Kameralar                            │
│              100 IP kamera (10'u aktif AI izlemede)                │
└──────────┬──────────────────────────────────────────────┬──────────┘
           │ RTSP main-stream                              │ RTSP sub-stream
           ▼                                               ▼
   ┌──────────────────┐                       ┌──────────────────────┐
   │   Dahua NVR(s)   │                       │   Frigate (Docker)   │
   │  - Tam kayıt     │                       │  - YOLOv8n (CPU/TPU) │
   │  - DSS/SmartPSS  │                       │  - Zone detection    │
   │  - HDD storage   │◄──────HTTP alarm──────┤  - MQTT publisher    │
   └──────────────────┘                       └──────────┬───────────┘
                                                         │ events
                                                         ▼
                                              ┌─────────────────────┐
                                              │     Mosquitto       │
                                              │     (MQTT broker)   │
                                              └──────────┬──────────┘
                                                         │ subscribe
                                                         ▼
                                              ┌─────────────────────┐
                                              │   Bridge servisi    │
                                              │  (Python, async)    │
                                              │                     │
                                              │  ├─ Zone state FSM  │
                                              │  ├─ LLM (Ollama)    │
                                              │  ├─ Dahua HTTP API  │
                                              │  └─ Snapshot store  │
                                              └────┬──────────┬─────┘
                                                   │          │
                              ┌────────────────────┘          └─────────┐
                              ▼                                          ▼
                    ┌──────────────────┐         HTTP          ┌───────────────────┐
                    │   PostgreSQL     │      (host.docker     │   Ollama (host)   │
                    │  - zone_events   │       .internal)      │   qwen2.5vl       │
                    │  - truck_events  │                       │  - tır/dorse renk │
                    │  - llm_usage     │                       │  - lokal · $0     │
                    └────────┬─────────┘                       │  - offline        │
                             │                                 └───────────────────┘
                             ▼
                    ┌──────────────────┐
                    │     Grafana      │
                    │   (dashboard)    │
                    └──────────────────┘
```

## Veri Akışı: Tipik Bir Olay

### Senaryo 1: Boş alana ilk giriş

1. Frigate `cam_01`'de hareket görür, YOLO `person` etiketi `zone_depo` içinde tespit eder.
2. Frigate MQTT'ye event publish eder: `frigate/events {"type":"new", "after":{"label":"person", "current_zones":["zone_depo"]}}`
3. Bridge servisi event'i alır. State machine `zone_depo`'nun durumuna bakar:
   - `occupied=False` ise → **first_entry** olayı. DB'ye yaz, Dahua'ya alarm, state'i `occupied=True` yap.
   - `occupied=True` ise → sessiz, sadece `last_seen` güncelle.
4. 60+ saniye kişi gözükmezse → bridge zone'u tekrar `occupied=False` yapar, çıkış event'i yazar.

### Senaryo 2: Kamyon girişi (renk analizi)

1. Frigate `cam_giris`'te `truck` tespit eder (YOLO) ve MQTT'ye publish eder.
2. Bridge truck handler event'i alır. Filtre: `score >= LLM_TRUCK_MIN_SCORE` (0.6) — altındaysa atlanır. Dedup: aynı `frigate_event_id` daha önce işlendiyse atlanır (memory + DB).
3. Frigate snapshot endpoint'inden frame'i **480px'e küçültülmüş** indirir (`?height=480` — latency kontrolü).
4. Snapshot'ı **host'taki Ollama'ya** gönderir (base64, `format=json`); `qwen2.5vl` çekici + dorse rengi + tipi JSON döndürür (CPU'da ~30 sn).
5. Sonucu `truck_events` tablosuna, çağrı metadata'sını (gecikme, model, `cost_usd=0`) `llm_usage` tablosuna yazar; snapshot diskte kalır.
6. Truck akışı **kendisi alarm üretmez** — bu bir zenginleştirmedir. Kamyon ayrıca izlenen bir zone'a girdiyse, Dahua alarmını **zone state machine** (Senaryo 1) paralel olarak tetikler.

## Network Topolojisi

- Kameralar: ayrı VLAN (örn. `192.168.10.0/24`), AI sunucusu **direct erişebilmeli** (NVR'a RTSP pull yapmıyoruz).
- AI sunucu: SnipeIT ile aynı VLAN'da olabilir ama Frigate kamera VLAN'ına da erişmeli.
- LLM (Ollama): **lokal** — bridge, host'taki Ollama servisine `host.docker.internal:11434` üzerinden erişir. **Outbound internet gerekmez** (görüntüler tesisten çıkmaz). _(Opsiyonel/planlı bulut hibrit kullanılırsa outbound HTTPS 443 gerekir.)_
- Dahua NVR HTTP API: AI sunucudan NVR'a alarm push için erişim (genelde 80/443) — sadece alarm, RTSP yok.
- SMTP: outbound 587 (Gmail TLS).
- Viewer (FastAPI): reverse proxy arkasında 443, kullanıcılar e-posta linkinden erişir.

## RAM Bütçesi

Docker AI stack'i (container'lar) tek başına ~7–8 GB'a sığar. **Lokal LLM (Ollama) bir container değil, host process'idir** — bu yüzden ayrı bir satır olarak ele alınır.

| Bileşen | PoC (CPU) | Production (Coral) |
|---|---|---|
| Ubuntu 22.04 + sistem | ~1 GB | ~1 GB |
| SnipeIT (Apache + MySQL + PHP) | ~3 GB | ~3 GB |
| Frigate (2–3 kamera CPU / 15 Coral) | ~1.5 GB | ~2.5 GB |
| PostgreSQL | ~0.5 GB | ~0.5 GB |
| Bridge Python servisi | ~0.3 GB | ~0.3 GB |
| Mosquitto | ~0.05 GB | ~0.05 GB |
| Grafana | ~0.3 GB | ~0.3 GB |
| Viewer (FastAPI, M6.5) | ~0.2 GB | ~0.2 GB |
| **Docker stack toplam** | **~6.85 GB** | **~7.85 GB** |
| **+ Ollama (host, `qwen2.5vl:7b` inference)** | **~6 GB**¹ | **~6 GB**¹ |

> ¹ Ollama modeli **yalnızca çıkarım sırasında** belleğe yüklenir ve `keep_alive` (varsayılan ~5 dk) sonrası boşalır. Truck olayları seyrek (günde birkaç) olduğundan bu ~6 GB **geçici tepe**dir, sürekli değil. Yine de aynı kutuda hem full stack hem Ollama koşacaksa **16 GB+ host RAM önerilir**. Alternatifler: daha küçük model (`qwen2.5vl:3b` ~3 GB), Ollama'yı **ayrı bir makinede** çalıştırıp `LLM_OLLAMA_URL`'i ona yöneltmek, veya GPU/Apple Silicon host. Detay: [`docs/02-hardware.md`](02-hardware.md#lokal-llm-ollama-için-kaynak).

Mevcut 12 GB sunucu **docker stack için yeterli**; lokal LLM co-located çalışacaksa RAM yükseltmesi veya ayrı inference host'u planlanmalı.

## Erişim Modeli

| Servis | Port | Network | Auth |
|---|---|---|---|
| Frigate Web UI | 5100 (→ 5000 container) | Iç (LAN) | reverse-proxy basic auth |
| Grafana | 3000 | Iç (LAN) | Username/password |
| Viewer (FastAPI) | 8080 | İç + reverse proxy 443 | HMAC view token |
| Postgres | 5432 | Sadece Docker network | DB user/pass |
| MQTT | 1883 | Sadece Docker network | DB user/pass |
| Bridge | yok | Docker internal | - |

## Hata Toleransı

| Senaryo | Davranış |
|---|---|
| Kamera offline | Frigate yeniden bağlanır (ffmpeg retry), bridge log'lar |
| Ollama erişilemez / timeout | Truck handler `LLM_MAX_RETRIES` (2) dener; başarısızsa `llm_usage.success=false` + `error` yazar, `truck_events` boş bırakılır. Zone/Dahua akışı etkilenmez (renk analizi best-effort, alarm yolu değil). |
| Postgres down | Bridge MQTT'den event alır ama yazamaz → critical log, alarm |
| Dahua API down | Alarm gönderimi kuyruğa girer, max 100 retry, sonra atılır |
| Disk dolu | Frigate eski snapshot'ları sil, log alarm |

Detaylar → [`docs/08-operations.md`](08-operations.md)
