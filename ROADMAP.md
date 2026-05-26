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

## Milestone 3: LLM Entegrasyonu (Haiku)

**Hedef**: Tır rengi ve şüpheli olay doğrulama Haiku'ya gidiyor.

- [ ] Anthropic SDK + prompt caching kurulumu
- [ ] `bridge/llm.py` — tır renk analiz fonksiyonu
- [ ] JSON schema doğrulama (Pydantic)
- [ ] Retry + timeout + cost log (her çağrının maliyetini DB'ye yaz)
- [ ] Truck event flow: Frigate "truck" → snapshot al → Haiku → DB
- [ ] Rate limit guard (saatlik max çağrı)

**Doğrulama**: 1 kamyon görüntüsü ile manuel test, renk JSON çıkışı doğrulanır. Maliyet logu kontrol.

---

## Milestone 4: Dahua Alarm Köprüsü

**Hedef**: Olaylar orijinal Dahua panelinde alarm olarak görünüyor.

- [ ] Dahua HTTP alarm API araştırma + auth
- [ ] `bridge/dahua.py` — alarm gönderme fonksiyonu
- [ ] Zone first_entry → Dahua external alarm trigger
- [ ] Test: bridge'den alarm tetikle, Dahua DSS'te göründüğünü doğrula
- [ ] Failure handling: Dahua erişilemezse retry queue

**Doğrulama**: Bridge'den alarm tetiklenince Dahua mobile push gelir.

---

## Milestone 5: 10 Alan + Çoklu Kamera

**Hedef**: Production kapsamı, 10 izlenen alan, hepsinde state machine.

- [ ] Frigate config: 10 kamera tanımı
- [ ] Per-zone konfigürasyon (her alanın kendi kuralı)
- [ ] Performans test: CPU yükü, RAM kullanımı, gecikme
- [ ] **Coral USB değerlendirme** — CPU yetmiyorsa hemen sipariş tetiklenir
- [ ] Grafana dashboard: alan başına olay sayısı, LLM çağrı/maliyet

**Doğrulama**: 24 saat sürekli koşum, kaçırılan olay <%5, RAM stabil.

---

## Milestone 6: Coral USB Upgrade

**Hedef**: Türkiye'den Coral USB geldikten sonra TPU'ya geçiş.

- [ ] Coral driver kurulumu (libedgetpu)
- [ ] Frigate detector config değişikliği
- [ ] Performans karşılaştırma (önce/sonra CPU yükü)
- [ ] Dokümantasyon update

**Doğrulama**: Aynı yükte CPU kullanımı %30+ düşmeli.

---

## Milestone 6.5: Kapı Olayları + E-posta Bildirim

**Hedef**: Kapılarda saniye hassasiyetinde giriş/çıkış log + e-posta linki.

- [ ] `bridge/door.py` — kapı state machine (entry_ts, exit_ts, direction)
- [ ] DB tablosu `door_events`
- [ ] `bridge/mailer.py` — SMTP entegrasyonu (Gmail App Password)
- [ ] HTML e-posta şablonu (snapshot inline)
- [ ] View token üretimi (HMAC, 7 gün TTL)
- [ ] `viewer/` FastAPI servisi (`/v/{event_id}?t={token}`)
- [ ] Snapshot clip (5 sn) opsiyonel kayıt
- [ ] Reverse proxy (Nginx + Let's Encrypt) konfigürasyon dokümanı
- [ ] SMTP rate limit + retry

**Doğrulama**: Bir kapı kameraya bir kişi geçer → 30 sn içinde e-posta gelir, linke tıklanır, snapshot ve klip oynatılır.

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
