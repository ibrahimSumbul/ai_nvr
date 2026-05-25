# Changelog

Bu dosya tüm önemli değişiklikleri kayıt altına alır.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) tarzı.

## [Unreleased]

### Added

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

### Notes
- M1: `uv.lock` şu an commit edilmiyor; ilk `uv sync` çalıştırıldığında üretilir. M2'de lock dosyası repo'ya alınacak (reproducible build).
- M1: Frigate UI host port'u **5100** (`5100:5000`). macOS'te port 5000 AirPlay Receiver tarafından tutulduğu için 5100 seçildi. Linux production'da da aynı port kullanılır.
- M1: Mosquitto anonymous bağlantı kabul ediyor; M3'te user/password authentication eklenecek.
- M1: Grafana provisioning boş; M5'te dashboard'lar provision edilecek.
- M0: M1 ile birlikte çalışan kod artık mevcut.
