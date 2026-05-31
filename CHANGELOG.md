# Changelog

Bu dosya tüm önemli değişiklikleri kayıt altına alır.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) tarzı.

## [Unreleased]

### Added

**M5 — Grafana Dashboard (kısmi)**
- `grafana/provisioning/datasources/postgres.yml` — AINVR Postgres datasource (otomatik, `$VAR` expansion ile credentials)
- `grafana/provisioning/dashboards/provider.yml` — dosya tabanlı dashboard provider
- `grafana/dashboards/ainvr-overview.json` — "AI NVR — Genel Bakış" dashboard: ilk giriş (24s) / kamyon / LLM başarı / Dahua bekleyen stat'ları, alan başına ilk giriş (saatlik bar), kamyon çekici rengi (donut), LLM gecikme (timeseries), son zone olayları (table)
- `docker-compose.yml` — grafana servisine provisioning + dashboards mount (RO) + Postgres env (datasource expansion)
- Doğrulama: datasource health `Database Connection OK`, dashboard provisioned, panel SQL'leri canlı veriyle çalışıyor

**M4 — Dahua Alarm Köprüsü**
- `bridge/dahua.py` — `DahuaClient` (Virtual Input CGI `/cgi-bin/alarm.cgi` + httpx DigestAuth):
  - `trigger_external_alarm(channel, event_type, description)` — inline retry + exponential backoff (2s/4s/8s)
  - `health_check()` — `magicBox.cgi getDeviceType` ile NVR yoklama
  - `DahuaAlarmClient` Protocol (provider-agnostic — onvif/dss_custom ileride), `DahuaAlarmError`
  - `build_dahua_client` factory — `DAHUA_ALARM_ENABLED=false` → None (dev'de push atlanır)
- `bridge/zones.py` — `ZoneStateMachine` Dahua entegrasyonu: `alarm_emitted` + client varsa external alarm tetiklenir; başarısızlıkta event DB'de pending kalır (`dahua_alarm_sent=false` + retry sayacı)
- `bridge/db.py` — `mark_dahua_alarm_sent`, `increment_dahua_retry`, `get_pending_dahua_alarms` (retry queue)
- `bridge/main.py` — `_dahua_retry_loop` worker: pending alarm'ları `DAHUA_RETRY_INTERVAL_S` periyodunda tekrar dener
- `bridge/zone_config.py` — `ZoneRules.dahua_channel` (zone→NVR channel eşlemesi)
- `bridge/config.py` — Dahua alarm ayarları (enabled, method, port, channel, timeout, max_retries, retry_interval)
- 13 yeni unit test (test_dahua.py: 9 — trigger/retry/fail/health/build; test_zones.py: 4 — alarm tetik/fail-retry/emitted-değil/none-client)

**M3 — LLM kalite tuning** (smoke test sonrası)
- Renk prompt fix: model rengi görse de "bilinmeyen" döndürüyordu → enum'a commit (siyah/gri doğru çıkıyor)
- Snapshot downscale: `llm_snapshot_max_height=480` + Frigate `?height=N` → latency %73↓ (800px 121s → 480px 33s)
- `num_predict` 512→256, `llm_timeout_s` 60→90

**M3 — LLM Entegrasyonu (Ollama)**
- `bridge/llm.py` — Provider-agnostic `LLMClient` Protocol + `OllamaClient` implementation:
  - `httpx.AsyncClient` ile `/api/generate` (Ollama vision endpoint)
  - `format=json` structured output, Pydantic schema parse
  - Retry (max_retries default 2) + timeout (default 60s)
  - `TruckAnalysis` Pydantic: Color enum (16 renk), TrailerType enum, Direction enum, guven (0.0-1.0)
  - `LLMResult` wrapper: parsed + raw + model + latency_ms + tokens + cost (Ollama'da 0)
  - `LLMError` exception — tüm retry'lar başarısız olunca yükselir
- `bridge/trucks.py` — `TruckEventHandler`:
  - Filter: `label == "truck"` + `score >= LLM_TRUCK_MIN_SCORE` (default 0.6)
  - Snapshot fetch (mevcut SnapshotStore)
  - LLM analyze → `llm_usage` + `truck_events` insert
  - Dedup: memory cache + DB sorgu (`truck_event_exists`)
  - LLM hata durumunda `llm_usage.success=false` + `error` yazılır, `truck_events` boş bırakılır
- `bridge/db.py` — `insert_llm_usage` + `insert_truck_event` + `truck_event_exists` fonksiyonları
- `bridge/config.py` — yeni LLM env vars:
  - `LLM_PROVIDER` (default `ollama`; `anthropic` hibrit fallback için kayıtlı)
  - `LLM_OLLAMA_URL` (default `http://host.docker.internal:11434` — mac host'taki native ollama)
  - `LLM_OLLAMA_MODEL` (default `qwen2.5vl:7b`, `.env` ile override)
  - `LLM_TIMEOUT_S` (60s), `LLM_MAX_RETRIES` (2), `LLM_TRUCK_MIN_SCORE` (0.6)
- `bridge/main.py` refactor: `build_llm_client` + `build_truck_handler` + `_listen_loop`'a truck handler bağlandı (zone'lara paralel akış)
- `.env.example` — LLM env değişkenleri eklendi, Anthropic ayrı tutuldu (hibrit gelecek)
- 14 yeni unit test:
  - `test_llm.py` (7): TruckAnalysis Pydantic parsing, invalid color/trailer_type/guven, extra field tolerance, JSON string parse
  - `test_trucks.py` (7): success path, non-truck label, low score, dedup (memory + DB), no_snapshot, LLM failure

**M3 prereq commit** (frigate/config.yml + docker-compose.yml):
- `frigate/config.yml`: `reset_admin_password: true → false` (admin parolası artık sabit, ilk login sonrası UI'dan değiştirilir)
- `docker-compose.yml`: bridge `INSTALL_LLM: "false"` olarak kaldı — M3 Ollama HTTP-only, anthropic SDK image'a girmiyor (httpx core'da)

**M2 — Tek kamera pilot**
- `bridge/events.py` — Pydantic `FrigateEvent` / `FrigateObject` (extra=allow ile Frigate sürüm toleransı)
- `bridge/zone_config.py` — `ZoneRules` / `ZoneConfig` / `ZonesConfig` Pydantic + YAML loader (room + door şeması, M6.5 için door alanları şimdiden tanımlı)
- `bridge/zones.py` — `ZoneStateMachine` (EMPTY/OCCUPIED + restore_from_db + active_hours overnight + clock injection). **DB insert HER ZAMAN, alarm tetikleme ayrı karar** (`first_entry_alarm AND active_hour AND alert_on_empty_arrival` → `alarm_emitted` metadata)
- `bridge/snapshots.py` — Frigate `/api/events/<id>/snapshot.jpg` async fetcher (httpx)
- `bridge/db.py` — `insert_zone_event` + `get_zone_last_event` eklendi
- `bridge/main.py` — listener refactor: FrigateEvent parse + cameras_to_zones routing + 10s tick loop + zone başına exception izolasyonu
- `bridge/config/zones.yaml` — pilot_zone tanımı
- `frigate/config.yml` — pilot_kamera (RTSP: `host.docker.internal:8554/cam_test`) + zone_pilot polygon
- `docker-compose.yml` — bridge image `0.2.0`, `./bridge/config:/app/config:ro` bind mount
- `bridge/pyproject.toml` — `pyyaml>=6.0.2` deps
- 28 yeni unit test (test_events.py: 6, test_zones.py: 22 — state transitions, dedup, exit timeout, active_hours, alarm/DB insert ayrımı, re-entry, restore non-first_entry)

**M1 — Docker iskelet**
- `docker-compose.yml` — Frigate, Postgres 16, Mosquitto 2, Grafana 11, Bridge servisi
- `bridge/` Python 3.13 servisi:
  - `bridge/config.py` — pydantic-settings ile env yönetimi
  - `bridge/db.py` — asyncpg connection pool + smoke test (SELECT 1)
  - `bridge/mqtt.py` — aiomqtt Frigate event listener, otomatik reconnect (exp. backoff)
  - `bridge/main.py` — asyncio entry, signal handling, structlog
- `bridge/Dockerfile` — Python 3.13-slim multistage, uv install, non-root user, healthcheck
- `bridge/pyproject.toml` — uv, PEP 735 dependency-groups, ruff + mypy + pytest
- `bridge/tests/` — pytest, unit + integration marker, config + smoke testleri
- `bridge/alembic.ini` + `bridge/alembic/` — migrasyon altyapısı (psycopg sync driver)
- `bridge/alembic/versions/0001_init.py` — baseline (5 tablo: zone_events, door_events, truck_events, llm_usage, camera_status)
- `db/schema.sql` — şema referansı
- `frigate/config.yml` — boş kamera şablonu (M2'de kameralar eklenir)
- `mosquitto/config/mosquitto.conf` — anonymous (M3'te authentication eklenecek)
- `Makefile` — up/down/logs/test/fmt/lint/migrate/build target'ları
- `.env.example` — tüm env değişkenleri, PoC default'ları
- `.github/workflows/ci.yml` — uv setup, ruff lint+format, mypy, pytest, docker build

**M0 — Dokümantasyon**
- Proje dokümantasyon iskeleti (`docs/01..11`)
- `README.md` proje genel bakış
- `ROADMAP.md` PoC → Production milestone planı
- `.gitignore` (Python, uv, Docker, IDE)
- **Kapı olayları (`door.traversal`)** — saniye hassasiyetinde giriş/çıkış logu
- **E-posta bildirim + viewer servisi** — imzalı link ile snapshot + klip izleme
- **Milestone 6.5** — kapı olayları + e-posta bildirimi
- `docs/09-notifications.md`
- `docs/10-why-frigate.md` — saf Haiku neden yapılmaz teknik gerekçeler
- `docs/11-tech-decisions.md` — teknoloji seçim kararları (Frigate, Python, Haiku, Postgres, n8n vs alternatifler)
- **MIT License** — portfolio için açık kaynak
- README portfolio-friendly açılış (badges + lead paragraph + cross-link to tech decisions)

### Changed

**M1 — Pre-build temizlik**
- README başlık ve lead paragrafı Türkçeleştirildi
- README badge `Documentation` → `M1 tamam`
- README durum tablosu güncellendi (11 doküman, M1 ✅, M2 sıradaki)
- README Hızlı Başlangıç bölümü artık çalışır komutlar içerir
- `docs/03-setup.md`: yanlış clone URL düzeltildi (`ibrahimsumbul/ibrahimsumbul.git` → `ibrahimSumbul/ai_nvr.git`)
- `docs/05-dahua-integration.md`: kopya "Sub-stream ayarı" bloğu silindi
- `docs/08-operations.md`: eski branch adı `main` ile değiştirildi, deploy path düzeltildi
- `ai_nvr_initial.zip` silindi

**M0 — Dokümantasyon revizyonu**
- Donanım bütçesi sabit: **maksimum 1× Coral USB ($60)**
- Kamera tahsisi: 15 Coral + 10 Haiku-only motion + 75 NVR-only = 100
- Aylık maliyet revize: ~$5 → **~$18** (Haiku Grup C overhead nedeniyle)
- `02-hardware.md`: Coral kapasite tablosu eklendi
- `04-zone-rules.md`: oda + kapı kuralları ayrıştırıldı
- `07-cost-analysis.md`: Grup C maliyet detayı + duyarlılık tablosu
- **NVR bağlantı stratejisi**: direct vs NVR-channel kıyaslama + yük hesabı
- **NVR yük izleme**: CPU eşikleri (%70 uyarı, %80 Grup C kapatma)
- **NVR'a yük ekleme iptal edildi** — sadece direct kamera bağlantısı kullanılır
- **Sabit bütçeler**: PoC $10/ay Haiku, Production $25/ay Haiku
- Grup C kamera sayısı motion yoğunluğuna göre $25 bütçeye kalibre edilir (10–12)
- **Maks. kapasite analizi**: Coral + $25 birlikte zorlanırsa ~25–47 kamera (konfig bağlı)
- M1 (Local Stack İskeleti) kapsamı netleştirildi: hangi dosyalar dahil/dışında
- Tüm dokümanlar tutarlılık için gözden geçirildi:
  - 01-architecture: mimari diyagram viewer + mailer eklendi, RAM bütçesi PoC/Prod ayrı, network direct-only
  - 03-setup: .env example güncellendi (NVR_HOST sadece alarm, SMTP+Viewer eklendi, bütçe default 10), Frigate config record role kaldırıldı
  - 04-zone-rules: kapsam ifadeleri PoC/Production ayrı
  - 08-operations: NVR CPU alarmları kaldırıldı (NVR pull yok), LLM eşikleri PoC/Production ayrı, RAM alarmı eklendi
- **NVR orijinal panel davranışı**: External Alarm + DSS Pro Custom Event seçenekleri
- **Kamera offline alarm**: 60 sn frame yok → uyarı; kritik kameralar için anlık e-posta
- `10-why-frigate.md` eklendi: saf Haiku neden yapılmaz teknik gerekçeler

### Changed

**M2.5 — Sıkılaştırma (M3 öncesi pre-flight)**
- **Mosquitto auth**: `allow_anonymous false` + `password_file /tmp/passwd`. Container entrypoint env'den (`MQTT_USER`/`MQTT_PASSWORD`) runtime'da passwd üretir, host'a sızmaz. Anonymous istekler `Connection Refused: not authorised`. Healthcheck artık auth ile.
- **Frigate auth sıkılaştırma**: `frigate/config.yml`'e açık `auth: enabled + trusted_proxies: [] + reset_admin_password: true`. Docker network internal istekleri artık anonymous-admin olarak geçmiyor; manuel login zorunlu. Yeni admin parolası her restart'ta log'a basılır.
- **Frigate `/config` persist**: yeni `frigate-config` named volume `/config`'e mount edildi. User DB + JWT secret + history recreate'te kayboluyor değil. `config.yml` ayrı RO bind mount olarak host'tan editlenebilir.
- **mypy strict zorunlu**: `.github/workflows/ci.yml`'de `continue-on-error: true` kaldırıldı. CI'da type hatası artık build'i kırar.
- **`dependency-groups` ile milestone-bazlı install**: `bridge/pyproject.toml`'da `[project].dependencies` sadece core (asyncpg, aiomqtt, pydantic, httpx, structlog, alembic, psycopg, pyyaml). M3+ deps `[dependency-groups]` altında `llm = ["anthropic"]` ve `viewer = ["fastapi", "uvicorn[standard]"]` olarak ayrıldı. Dockerfile build arg `INSTALL_LLM`/`INSTALL_VIEWER` ile aktive (default false → core-only image).
- **`uv.lock` commit edildi**: `.gitignore`'tan `uv.lock` kaldırıldı, lock dosyası repo'ya alındı. CI `uv sync --frozen` ile lock'tan sapmayı engelliyor (reproducible build). Dockerfile da `--frozen` kullanıyor.

### Notes
- M1: Frigate UI dev port'u **5100** (`5100:5000`). macOS'te 5000'i AirPlay Receiver tutuyor; bu seçim **macOS dev için zorunlu**. Linux production'da reverse proxy (443) arkasında host portu önemsiz, gerekirse 5000'e dönülebilir.
- M1: Grafana provisioning boş; M5'te dashboard'lar provision edilecek.
- M2.5: Frigate `reset_admin_password: true` aktif — her restart'ta admin parolası yeniden üretilir (log'a basılır). M3'te kullanıcı admin pass'ını UI'dan değiştirip config'i `false`'a alabilir.
- M0: M1 ile birlikte çalışan kod artık mevcut.
