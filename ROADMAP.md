# Yol Haritası

Bu proje **PoC** olarak başlar, ama her milestone **production-ready** kalite hedefler. "Sonra düzeltirim" mantığı yok — her adım kalıcı olacak şekilde yazılır.

## Milestone 0: Dokümantasyon ve Mimari ✅

- [x] Mimari kararları (Frigate + Haiku + Dahua bridge)
- [x] Donanım planı (PoC: CPU, prod: Coral USB)
- [x] Maliyet analizi (PoC $10/ay, Production $25/ay)
- [x] Tüm `docs/` dosyaları tamam (10 doküman)
- [x] Repository açılışı + draft PR #1

**Çıktı**: Bu repodaki `ai-nvr/` klasörü.

---

## Milestone 1: Local Stack İskeleti ✅

**Hedef**: Tek komutla ayağa kalkan, henüz kameraya bağlı olmayan stack.

### Kapsam (dahil)
- [x] `docker-compose.yml` — Frigate (CPU detector), Postgres, Mosquitto, Grafana, Bridge
- [x] `.env.example` — tüm değişkenler (PoC default'ları)
- [x] `frigate/config.yml` — boş şablon, comment'lerle açıklamalı, henüz kamera yok
- [x] `bridge/` Python servis iskeleti
  - `bridge/main.py` — MQTT'ye bağlanır, log atar, idle döner
  - `bridge/config.py` — env'den ayarlar
  - `bridge/db.py` — Postgres async bağlantı (asyncpg)
  - `bridge/mqtt.py` — async MQTT istemci
  - `bridge/__init__.py`
- [x] `bridge/Dockerfile` (python:3.13-slim, multistage)
- [x] `bridge/pyproject.toml` (uv ile)
- [x] `bridge/tests/` — smoke test (config yüklenir, DB bağlanır)
- [x] `db/schema.sql` — tablolar (zone_events, door_events, truck_events, llm_usage, camera_status)
- [x] `bridge/alembic/` — migrasyon altyapısı (`0001_init` baseline)
- [x] `Makefile`: `up / down / logs / shell / test / fmt / lint / migrate`
- [x] Health check tüm container'lar `healthy`
- [x] CI: GitHub Actions — ruff + mypy + pytest + docker build
- [x] `README` quickstart bölümü canlandı

### Kapsam (dışında — sonraki milestone'lar)
- ❌ Gerçek kameraya bağlanma (M2)
- ❌ Haiku LLM çağrısı (M3)
- ❌ Dahua alarm bridge (M4)
- ❌ Zone state machine logic (M2)
- ❌ Door traversal logic (M6.5)
- ❌ E-posta + viewer (M6.5)

**Doğrulama**:
```bash
make up
docker compose ps        # tüm servisler healthy
make test                # smoke testler geçer
docker compose logs bridge   # "Bridge ready, waiting for events" yazar
make down
```

CI yeşil, container 24 saat çakılmadan çalışır (boş loop).

---

## Milestone 2: Tek Kamera Pilot ✅

**Hedef**: 1 kamera, 1 alan, ilk-giriş kuralı çalışıyor.

- [x] Kameradan RTSP sub-stream alımı (Frigate config — M2 pilot için MediaMTX test stream)
- [x] Frigate person detection (CPU YOLOv8n)
- [x] Bridge: MQTT FrigateEvent parse + state machine'e route
- [x] Zone state machine — EMPTY/OCCUPIED + active_hours + alarm/DB insert ayrımı
- [x] PostgreSQL'e `zone_events` insert (her first_entry + exit kaydı)
- [x] Snapshot fetcher (Frigate API) + local disk store
- [x] Restart recovery (`restore_from_db`)
- [x] 28 unit test (events + state machine + active_hours + re-entry)
- [x] Manuel test: end-to-end pipeline doğrulandı (lokal Colima + MediaMTX)

**Doğrulama**: alana giriş → DB'de `first_entry` (`alarm_emitted` metadata ile) + snapshot diskte. Heartbeat dedup çalışıyor. Exit timeout `exit` event üretir.

---

## Milestone 2.5: Sıkılaştırma (M3 öncesi pre-flight) ✅

**Hedef**: M3'te LLM/cloud entegrasyonu eklemeden önce güvenlik, persistence ve dev-prod disiplini sıkılaştırıldı.

- [x] **Mosquitto auth**: anonymous kaldırıldı, `MQTT_USER`/`MQTT_PASSWORD` zorunlu, `mosquitto.conf` `password_file` + container entrypoint env'den passwd üretir
- [x] **Frigate auth sıkılaştırma**: `frigate/config.yml`'e açık `auth: enabled + trusted_proxies: [] + reset_admin_password: true`
- [x] **Frigate `/config` persist**: `frigate-config` named volume — user DB + JWT secret + history persist
- [x] **mypy strict zorunlu**: CI'da `continue-on-error: true` kaldırıldı
- [x] **`dependency-groups` ile incremental install**: M3+ deps (`anthropic`, `fastapi`, `httpx` core'da) `[dependency-groups]` altında `llm` ve `viewer` olarak ayrıldı. Dockerfile build arg `INSTALL_LLM`/`INSTALL_VIEWER` ile aktive
- [x] **`uv.lock` commit edildi**: `.gitignore`'tan kaldırıldı, CI ve Dockerfile `--frozen` kullanır

**Doğrulama**: Anonymous mqtt → `Connection Refused: not authorised`. Auth ile uptime alınıyor. Frigate restart sonrası user DB persist (no "users exist" mesajı). mypy strict CI'da blocker. Core-only image'a `anthropic`/`fastapi` install **edilmiyor**.

---

## Milestone 3: LLM Entegrasyonu (Ollama) ✅

**Hedef**: Tır rengi + dorse tipi analizi lokal Ollama vision model ile yapılıyor. Cost: $0 (electric only). Privacy: görüntüler dış servise gitmiyor.

- [x] `bridge/llm.py` — `OllamaClient` (httpx async), `LLMClient` Protocol provider-agnostic
- [x] `TruckAnalysis` Pydantic schema (renk enum, dorse tipi enum, guven)
- [x] Ollama `/api/generate` çağrısı `format=json` structured output + retry + timeout
- [x] Truck event flow: Frigate "truck" → SnapshotStore → OllamaClient → `truck_events` + `llm_usage` insert
- [x] Dedup: aynı `frigate_event_id` için tekrar LLM çağrısı yok
- [x] **Kalite tuning** (smoke test sonrası): renk prompt fix (bilinmeyen→gerçek renk) + snapshot downscale (480px, latency %73↓)
- [x] **Hibrit fallback altyapısı**: `LLM_PROVIDER` switch + `build_llm_client` factory (anthropic ileride)
- [x] **M3 öncesi prereq**: `reset_admin_password: false` + Ollama host + `qwen2.5vl:7b`

**Doğrulama**: ✅ Smoke test — kamyon görüntüsü → `truck_events` + `llm_usage` insert (FK bağlı), renk JSON doğru (siyah/gri), latency ~30s (480px). PR #6, #9.

---

## Milestone 4: Dahua Alarm Köprüsü ✅ (kod) / ⏳ (gerçek NVR testi)

**Hedef**: Olaylar orijinal Dahua panelinde alarm olarak görünüyor.

- [x] Dahua HTTP alarm API + digest auth (`docs/05` Yöntem 3: Virtual Input CGI)
- [x] `bridge/dahua.py` — `DahuaClient.trigger_external_alarm` + `health_check` + retry/backoff
- [x] Zone first_entry → Dahua external alarm trigger (`zones.py`, `alarm_emitted` flag'i ile)
- [x] Failure handling: inline retry (exp. backoff) + DB pending + `_dahua_retry_loop` worker
- [x] `DAHUA_ALARM_ENABLED` switch (dev'de false → push atlanır, olaylar DB'ye yine yazılır)
- [ ] **Gerçek NVR testi**: bridge'den alarm → Dahua DSS'te görünür doğrulama (production ortamı gerekir; dev'de httpx mock ile path doğrulandı)

**Doğrulama**: Kod + unit test (httpx mock: trigger/retry/fail/health). Gerçek mobile push doğrulaması production NVR'da yapılacak (PoC ilk hafta API uyum testi — docs/05).

---

## Milestone 5: 10 Alan + Çoklu Kamera 🚧

**Hedef**: Production kapsamı, 10 izlenen alan, hepsinde state machine.

- [~] Frigate config: çoklu kamera (dev'de 5 MediaMTX stream aktif; production'da 10 gerçek Dahua kamera)
- [x] Per-zone konfigürasyon (her alanın kendi kuralı — `zones.yaml` ZoneRules, M2'den beri; M4'te `dahua_channel` eklendi)
- [ ] Performans test: CPU yükü, RAM kullanımı, gecikme (24s koşum)
- [ ] **Coral USB değerlendirme** — CPU yetmiyorsa hemen sipariş tetiklenir
- [x] **Grafana dashboard**: provisioning (datasource + dashboard JSON), alan başına ilk giriş, kamyon renk dağılımı, LLM gecikme/başarı, Dahua alarm durumu

**Doğrulama**: 24 saat sürekli koşum, kaçırılan olay <%5, RAM stabil. (Grafana dashboard ✅ — datasource health OK, paneller canlı veriyle render.)

---

## Milestone 6: Coral USB Upgrade

**Hedef**: Türkiye'den Coral USB geldikten sonra TPU'ya geçiş.

- [ ] Coral driver kurulumu (libedgetpu)
- [ ] Frigate detector config değişikliği
- [ ] Performans karşılaştırma (önce/sonra CPU yükü)
- [ ] Dokümantasyon update

**Doğrulama**: Aynı yükte CPU kullanımı %30+ düşmeli.

---

## Milestone 6.5: Kapı Olayları (DMSS push ile bildirim) ✅

**Hedef**: Kapılarda saniye hassasiyetinde giriş/çıkış log. Bildirim **DMSS mobil push** ile (M4 external alarm mekanizması) — ayrı e-posta/viewer altyapısı **kapsam dışı** (bkz. karar kaydı 2026-05-31).

- [x] `bridge/doors.py` — `DoorStateMachine` (alternating in/out, ms hassasiyetli entry/exit, duration_ms)
- [x] DB `door_events` insert/close (`insert_door_event` + `close_door_event`, şema M1'de hazır)
- [x] Kapı geçişi → Dahua external alarm (M4 `DahuaClient`) → DMSS push (best-effort, inline retry)
- [x] `cam_kapi` zone'u `type: door` + main.py tip-bazlı routing (room→ZSM, door→DSM)
- [x] Dedup (heartbeat tracking_id) + cooldown (`cooldown_seconds` debounce)
- [x] 9 unit test + gerçek-Postgres E2E (insert/close SQL, duration hesabı)

**Doğrulama**: ✅ E2E — iki geçiş → `door_events`'e in/close (entry_ts, exit_ts, duration_ms=8000). Yön: basit alternating; **gerçek giriş/çıkış kamera açısına bağlı, kuruluma göre değerlendirilmeli** (`doors.py` not). Gerçek DMSS push production NVR'da.

> **Kapsam dışı** (kullanıcı kararı 2026-05-31): SMTP e-posta, `viewer/` FastAPI, HMAC izleme linki, reverse proxy. Mevcut güvenlik operasyonu zaten DMSS kullandığı için ayrı bildirim kanalı gereksiz. İlgili `docs/09-notifications.md` referans/opsiyonel olarak kalır.

---

## Milestone 7: Operasyonel Olgunluk

**Hedef**: Sistem unutulabilir hale gelsin.

- [ ] Backup stratejisi (Postgres + snapshot diski)
- [ ] Alert kuralları (Grafana → email/Telegram)
- [ ] Disk doluluk + LLM bütçe alarmı
- [ ] Log rotation
- [ ] Sistem restart senaryosu test
- [ ] Operasyon runbook (`docs/08-operations.md`)

**Doğrulama**: 1 hafta dokunmadan stabil.

---

## Milestone 8: Genişletme Fırsatları (opsiyonel)

- [ ] Yüz tanıma (CompreFace) — yetki kontrolü için
- [ ] Davranış/anomali tespiti (kavga, düşme)
- [ ] SnipeIT entegrasyonu (asset link)
- [ ] Mobile push notification
- [ ] Çoklu kullanıcı UI

---

## Risk & Karar Kayıtları

| Tarih | Karar | Gerekçe |
|---|---|---|
| 2026-05-25 | Frigate seçimi (saf bulut LLM yerine) | Aylık $2.5M maliyet yerine ~$5. Donanım bir kere. |
| 2026-05-25 | Coral USB ertelendi | Türkiye tedarik süresi var, PoC CPU ile başlayabilir. |
| 2026-05-25 | Plaka okuma kapsam dışı | Müşteri renk yeterli dedi. ALPR ayrı bir milestone. |
| 2026-05-25 | Yüz tanıma kapsam dışı | İlk fazda zone state machine yeter. M8'e bırakıldı. |
| 2026-05-25 | Donanım tavanı $60 (1× Coral USB) | Ek Coral alınmaz. Aşımı Haiku ile karşılanır. |
| 2026-05-25 | Kapı olayları ayrı event tipi | Oda mantığından farklı: her geçişte alarm, ms hassasiyet log, e-posta + link. |
| 2026-05-25 | NVR bağlantı: direct öncelikli | NVR %50 yükte, üzerine pull eklemek riskli. Direct yapılamayan yerler NVR channel ile. |
| 2026-05-25 | NVR CPU > %80 → Grup C otomatik kapanır | Kayıt güvenliği LLM gözlemden önceliklidir. |
| 2026-05-25 | Saf Haiku reddedildi | Tracking yok, gecikme 1.5 sn, rate limit, maliyet patlar. Frigate ile hibrit zorunlu. |
| 2026-05-25 | **NVR yük opsiyonu iptal — direct bağlantı zorunlu** | NVR %50 yükte, ek pull yapmıyoruz. Kameralar AI sunucudan kendi IP'sinden erişilebilir olmalı. |
| 2026-05-25 | **Bütçe sabitlendi: PoC $10/ay, Production $25/ay** | İki fazlı kesin tavan. Grup C kamera sayısı bu bütçeye göre kalibre edilir. |
| 2026-05-25 | n8n reddedildi | Stateless workflow → state machine için round-trip; node başına 100–300 ms gecikme; 500 MB RAM ek yük; CI/test zor. Gelecekte secondary bildirim dağıtımında değerlendirilir. |
| 2026-05-25 | Python + asyncio seçildi (Node/Go/Rust elendi) | Anthropic/Pydantic/asyncpg olgun, ML ekosistem güçlü, hızlı yazma. Bkz. `docs/11-tech-decisions.md`. |
| 2026-05-31 | **LLM: Haiku → lokal Ollama** (M3) | Aylık $0 (electric), görüntüler tesisten çıkmaz (gizlilik), kota/rate-limit yok. `LLM_PROVIDER` switch ile Anthropic hibrit ileride opsiyonel. Önceki "Haiku bütçe" kararları geçersiz. |
| 2026-05-31 | **E-posta/viewer kapsam dışı — DMSS push yeterli** | Güvenlik operasyonu zaten DMSS mobil app kullanıyor. M4 external alarm → NVR push kuralı → DMSS bildirimi. Ayrı SMTP/viewer/HMAC altyapısı gereksiz karmaşıklık. |
