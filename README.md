# AI NVR — Dahua + Frigate + Ollama Hibrit Kamera Analitiği

[![Lisans: MIT](https://img.shields.io/badge/Lisans-MIT-blue.svg)](LICENSE)
[![Faz: M4 tamam · M5 sürüyor](https://img.shields.io/badge/Faz-M4%20tamam%20·%20M5%20sürüyor-green.svg)](ROADMAP.md)
[![Stack: Python · Frigate · Postgres · Ollama · Grafana](https://img.shields.io/badge/Stack-Python%20·%20Frigate%20·%20Postgres%20·%20Ollama%20·%20Grafana-534AB7.svg)](docs/11-tech-decisions.md)
[![Test: 60 unit · ruff · mypy strict](https://img.shields.io/badge/Test-60%20unit%20·%20ruff%20·%20mypy%20strict-success.svg)](bridge/tests)

Mevcut bir Dahua NVR'ın üzerine **orijinal kayıt sistemini bozmadan** alan yetkisi, ilk-giriş alarmı, kapı geçişi logu ve tır/dorse renk kaydı ekleyen hafif bir hibrit AI katmanı.

Tipik 100 IP-kameralı, NVR'ı ~%50 yükte olan bir endüstriyel kurulum için tasarlandı. Lokal nesne tespiti **Frigate**'te koşar (CPU → opsiyonel Coral USB), semantik analiz (tır/dorse rengi) **lokal Ollama vision modeli**nde koşar — **görüntüler tesisten çıkmaz, aylık LLM maliyeti $0**. Olaylar orijinal DSS/SmartPSS paneline **external alarm** olarak geri akar.

> Portföy projesi — mevcut CCTV altyapısı üzerinde gizlilik-öncelikli lokal AI için açık kaynak referans mimari, çalışır kod ve dokümantasyon.

## Durum

> **Çekirdek pipeline çalışıyor.** 5 servis healthy; kamera → Frigate tespit → bridge zone state machine → Postgres + Dahua alarm + Ollama tır analizi → Grafana dashboard uçtan uca doğrulandı (lokal Colima + MediaMTX test stream).

| Milestone | Durum | Özet |
|---|---|---|
| M0 — Mimari & dokümantasyon | ✅ | 11 doküman, kararlar |
| M1 — Docker stack iskeleti | ✅ | 5 servis, Alembic, CI |
| M2 — Tek kamera pilot | ✅ | Zone state machine, ilk-giriş alarmı, snapshot |
| M2.5 — Güvenlik sıkılaştırma | ✅ | MQTT/Frigate auth, mypy strict, persist |
| M3 — Lokal LLM (Ollama) | ✅ | Tır/dorse renk analizi, `truck_events` + maliyet log |
| M4 — Dahua alarm köprüsü | ✅ (kod) | NVR'a external alarm push + retry queue |
| M5 — Çoklu kamera + Grafana | 🚧 | 5 kamera aktif, dashboard ✅; 10 kamera + perf testi production |
| M6 — Coral USB upgrade | ⬜ | Donanım tedariki bekliyor |
| M6.5 — Kapı olayları + e-posta | ⬜ | Door state machine + SMTP + viewer |
| M7 — Operasyonel olgunluk | ⬜ | Backup, alerting, runbook |

Ayrıntılı plan: [`ROADMAP.md`](ROADMAP.md).

## Ne Yapar?

1. **Dahua NVR kayda devam eder** — bu sistem ona dokunmaz, sadece RTSP sub-stream'leri **doğrudan kameralardan** paralel okur (NVR'a yük binmez).
2. **Frigate lokal tespiti** — kişi/araç/kamyon, CPU detector (opsiyonel Coral USB ile hızlanır).
3. **Oda state machine** — alan boşken ilk giren kişiyi `first_entry` olarak kaydeder, dolu alanda spam üretmez; `exit_timeout` sonrası `exit`. Mesai saatleri (`active_hours`) ve alarm tetikleme ayrı kararlar.
4. **Kısıtlı bölge alarmı** — polygon zone'a (örn. sarı çizginin üstü) giriş anında alarm.
5. **Kamyon girişinde lokal Ollama** ile **çekici ve dorse rengini** + dorse tipini ayrı kaydeder (`qwen2.5vl`). Plaka okumaz. Her çağrının gecikme/başarı kaydı `llm_usage`'a yazılır.
6. **Olayları Dahua NVR'a external alarm** olarak geri besler — orijinal DSS/SmartPSS panelinde görünür (mobil push dahil). Erişilemezse retry kuyruğu.
7. **Grafana dashboard** — alan başına giriş, kamyon renk dağılımı, LLM gecikme/başarı, bekleyen alarm.
8. **Kapı olayları + e-posta** (M6.5 planlı) — saniye hassasiyetinde giriş/çıkış + imzalı izleme linki.

## Mimari Özet

```
        Dahua IP kameralar                         Dahua NVR (orijinal kayıt)
        (RTSP sub-stream, direct)                  (DSS/SmartPSS panel görür)
                 │                                          ▲
                 │ RTSP                            External │ alarm (HTTP digest)
                 ▼                                          │
  ┌──────────────────────────────  AI Stack (Docker)  ─────┴───────────────┐
  │                                                                         │
  │   Frigate ──MQTT(events)──▶  Bridge (Python/asyncio)  ──▶  PostgreSQL   │
  │   (CPU/Coral detect)          • zone state machine         (olay + log) │
  │                               • truck → Ollama analizi          │       │
  │   Ollama (host) ◀──HTTP───────• Dahua alarm + retry             │       │
  │   (qwen2.5vl, lokal)          • snapshot fetch            Grafana ◀──────┤
  │                                                          (dashboard)    │
  │   Mosquitto (MQTT broker)                                               │
  └─────────────────────────────────────────────────────────────────────────┘
```

Detay: [`docs/01-architecture.md`](docs/01-architecture.md).

## Hızlı Başlangıç

**Gereksinimler**: Docker + Docker Compose, [Ollama](https://ollama.com) (lokal LLM için, host'ta çalışır).

```bash
# 1. Klonla
git clone https://github.com/ibrahimSumbul/ai_nvr.git
cd ai_nvr

# 2. Ortam değişkenleri — güçlü şifreler gir
cp .env.example .env
#   POSTGRES_PASSWORD, MQTT_PASSWORD, GRAFANA_ADMIN_PASSWORD zorunlu.
#   Dahua alarm için: DAHUA_ALARM_ENABLED=true + DAHUA_NVR_* (opsiyonel, default kapalı).

# 3. Ollama vision modeli (host'ta)
ollama pull qwen2.5vl:7b      # ~5.6 GB; .env LLM_OLLAMA_MODEL ile değiştirilebilir

# 4. Stack'i başlat
docker compose up -d

# 5. Veritabanı şeması (ilk kurulumda zorunlu)
docker compose run --rm --entrypoint "" bridge alembic upgrade head

# 6. Doğrula
docker compose ps             # 5 servis 'healthy'
docker compose logs bridge    # "bridge.ready ... cameras=N zones=N"
```

| Servis | Adres | Not |
|---|---|---|
| Frigate UI | http://localhost:5100 | macOS'te 5000'i AirPlay tutar → 5100 |
| Grafana | http://localhost:3000 | "AI NVR — Genel Bakış" dashboard otomatik yüklü |

**Kamera ekleme**: [`frigate/config.yml`](frigate/config.yml)'e RTSP girişi + [`bridge/config/zones.yaml`](bridge/config/zones.yaml)'a zone eşlemesi. İkisi de RW bind mount — restart yeter, rebuild gerekmez. Dahua RTSP/zone detayları: [`docs/05-dahua-integration.md`](docs/05-dahua-integration.md), [`docs/04-zone-rules.md`](docs/04-zone-rules.md).

> **Dev'de gerçek kamera yoksa**: [MediaMTX](https://github.com/bluenviron/mediamtx) ile test RTSP stream'leri yayınlanabilir (`rtsp://host.docker.internal:8554/<isim>`).

### Geliştirme

```bash
cd bridge
uv sync --group dev                     # bağımlılıklar
uv run --group dev pytest -m "not integration"   # 60 unit test
uv run --group dev ruff check . && uv run --group dev mypy bridge
```

Adım adım kurulum + sorun giderme: [`docs/03-setup.md`](docs/03-setup.md).

## Maliyet

| Kalem | Tutar | Not |
|---|---|---|
| **Aylık LLM** | **$0** | Ollama lokal — görüntüler tesisten çıkmaz |
| Donanım (PoC) | $0 | Mevcut sunucu (CPU detection) |
| Donanım (Production) | ~$60 (bir kere) | 1× Coral USB — detection hızlanır |
| Opsiyonel bulut hibrit | kullanım bazlı | `LLM_PROVIDER=anthropic` (gizlilik/maliyet trade-off) |

Lokal Ollama tercihinin gerekçesi (gizlilik + sıfır marjinal maliyet vs bulut gecikme/kota): [`docs/06-llm-strategy.md`](docs/06-llm-strategy.md), [`docs/07-cost-analysis.md`](docs/07-cost-analysis.md).

## Teknoloji & Dokümantasyon

| Dosya | İçerik |
|---|---|
| [`docs/01-architecture.md`](docs/01-architecture.md) | Sistem mimarisi, veri akışı |
| [`docs/02-hardware.md`](docs/02-hardware.md) | Donanım gereksinimleri, Coral yükseltme |
| [`docs/03-setup.md`](docs/03-setup.md) | Adım adım kurulum, sorun giderme |
| [`docs/04-zone-rules.md`](docs/04-zone-rules.md) | Zone kuralları, state machine, ilk-giriş tetikleyici |
| [`docs/05-dahua-integration.md`](docs/05-dahua-integration.md) | Dahua RTSP, external alarm (CGI/ONVIF/DSS), digest auth |
| [`docs/06-llm-strategy.md`](docs/06-llm-strategy.md) | LLM stratejisi, tır/dorse renk promptu |
| [`docs/07-cost-analysis.md`](docs/07-cost-analysis.md) | Maliyet analizi, kıyaslamalar |
| [`docs/08-operations.md`](docs/08-operations.md) | İşletim, izleme, yedekleme |
| [`docs/09-notifications.md`](docs/09-notifications.md) | E-posta bildirimi + imzalı izleme linki (M6.5) |
| [`docs/10-why-frigate.md`](docs/10-why-frigate.md) | Frigate neden gerekli? Saf LLM ile yapılamaz mı? |
| [`docs/11-tech-decisions.md`](docs/11-tech-decisions.md) | Teknoloji seçim kararları |
| [`ROADMAP.md`](ROADMAP.md) · [`CHANGELOG.md`](CHANGELOG.md) | Milestone planı · değişiklik kaydı |

## Lisans

[MIT](LICENSE) — özgür kullanım, atıf yeterli.

## İletişim

İbrahim Sümbül · [ibrahimsumbulll@gmail.com](mailto:ibrahimsumbulll@gmail.com) · [GitHub](https://github.com/ibrahimSumbul)
