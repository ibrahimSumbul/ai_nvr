# AI NVR — Dahua + Frigate + Claude Haiku Hybrid Camera Analytics

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Status: Documentation Phase](https://img.shields.io/badge/Status-Documentation-orange.svg)](ROADMAP.md)
[![Stack: Python · Frigate · Postgres · Claude Haiku](https://img.shields.io/badge/Stack-Python%20·%20Frigate%20·%20Postgres%20·%20Claude-534AB7.svg)](docs/11-tech-decisions.md)

A lightweight hybrid AI layer that adds zone authorization, first-entry alarms, second-precision door traversal logging, and truck/trailer color recording on top of an existing Dahua NVR — **without disturbing the original recording system**.

Designed for a typical 100-IP-camera industrial deployment where the NVR is at ~50% load. Local detection runs on Frigate (CPU → Coral USB upgrade), semantic analysis (color, anomaly description) runs on Claude Haiku, and events flow back into the original DSS/SmartPSS panel as external alarms.

> Portfolio project — open-source reference architecture and documentation for hybrid local + cloud AI on existing CCTV infrastructure.

## Durum

> **Dokümantasyon tamamlandı.** Kod henüz scaffold edilmedi — Milestone 1 ile başlıyor.

| Aşama | Durum |
|---|---|
| Mimari kararları | ✅ Tamam |
| Dokümantasyon (10 doküman) | ✅ Tamam |
| Docker iskelet (M1) | ⬜ Sıradaki PR |
| Tek kamera pilot (M2) | ⬜ Bekliyor |
| LLM + Dahua alarm + e-posta (M3–M6.5) | ⬜ Bekliyor |
| Üretim (~25 AI kamera) | ⬜ Bekliyor |
| Coral USB upgrade | ⬜ Türkiye tedarik bekliyor |

## Ne Yapar?

1. **Dahua NVR kayda devam eder** — bu sistem ona dokunmaz, sadece RTSP sub-stream'leri paralel okur.
2. **15 kamera Coral USB'de** Frigate ile lokal kişi/araç tespiti (10 oda + 5 kapı).
3. **Coral'a sığmayan kameralar Haiku ile desteklenir** (motion-triggered snapshot analizi). Donanım bütçesi maksimum $60'da sabit.
4. **Oda state machine'i**: alan boşken ilk giren kişiyi kaydeder, dolu alanda spam uyarısı vermez. İzleme süresi 1+ dakika.
5. **Kapı olayları**: her geçişte alarm, **saniye hassasiyetinde** giriş ve çıkış zamanı kaydedilir. E-posta ile **canlı izleme linki** gönderilir.
6. **Kamyon girişinde** Claude Haiku ile **çekici (tır) ve dorse rengini** ayrı kaydeder. Plaka okumaz.
7. **Olayları Dahua NVR'a alarm olarak** geri besler — orijinal DSS/SmartPSS panelinde "External Alarm" tipinde görünür.
8. **Kamera offline tespit** — herhangi bir kamera 60 sn'den fazla frame göndermezse uyarı/e-posta.
9. **NVR yük izleme** — NVR CPU %70'i geçince uyarı, %80'de Grup C otomatik devre dışı (kayıt güvenliği önce).

## İki Fazlı Plan

| Faz | Donanım | Haiku bütçe | Kamera AI kapsamında |
|---|---|---|---|
| **PoC** | Mevcut 8 GB RAM sunucu (Coral yok) | **$10/ay** | 2–3 pilot |
| **Production** | + 1× Coral USB ($60) | **$25/ay** | ~25 (15 Coral + 10 Haiku) |

**NVR'a yük binmez** — tüm bağlantılar doğrudan kameralara (direct IP). NVR sadece kendi kaydını yapmaya devam eder.

### Production Grup Tahsisi (100 kamera için)

| Grup | Kamera | Mekanizma | Aylık $ |
|---|---|---|---|
| **A**: Aktif izlenen alanlar (oda) | 10 | Frigate + Coral | (Coral içinde) |
| **B**: Kapılar (alarm + log + e-posta) | 5 | Frigate + Coral | (Coral içinde) |
| **C**: Düşük öncelik (motion) | 10–12 | Motion + Haiku snapshot | ~$11–13 |
| **D**: Sadece NVR kaydı | 73–75 | NVR kayıt, AI yok | $0 |

Grup C boyutu motion yoğunluğuna ve $25 bütçeye göre kalibre edilir.

## Maliyet Özeti

| | İlk yatırım | Haiku/ay | Toplam aylık |
|---|---|---|---|
| **PoC** | $0 | $10 | ~$11 |
| **Production** | $60 | $25 | ~$28 |

Daha fazla kamera eklenirse → maliyet sadece Haiku tarafında artar (donanım yok).

## Hızlı Başlangıç

> 🚧 Henüz aktif değil. `docs/03-setup.md` yazıldıktan sonra burası canlanır.

```bash
# Planlanan
cp .env.example .env
# .env içine: ANTHROPIC_API_KEY, DAHUA_*, RTSP URL'leri
docker compose up -d
```

## Dokümantasyon

| Dosya | İçerik |
|---|---|
| [`docs/01-architecture.md`](docs/01-architecture.md) | Sistem mimarisi, veri akışı |
| [`docs/02-hardware.md`](docs/02-hardware.md) | Donanım gereksinimleri, Coral yükseltme yolu |
| [`docs/03-setup.md`](docs/03-setup.md) | Adım adım kurulum |
| [`docs/04-zone-rules.md`](docs/04-zone-rules.md) | Alan kuralları, state machine, ilk-giriş tetikleyici |
| [`docs/05-dahua-integration.md`](docs/05-dahua-integration.md) | Dahua RTSP, HTTP alarm, ONVIF entegrasyonu |
| [`docs/06-llm-strategy.md`](docs/06-llm-strategy.md) | Claude Haiku promptları, tır/dorse renk analizi |
| [`docs/07-cost-analysis.md`](docs/07-cost-analysis.md) | Maliyet analizi, kıyaslamalar |
| [`docs/08-operations.md`](docs/08-operations.md) | İşletim, izleme, yedekleme, sorun giderme |
| [`docs/09-notifications.md`](docs/09-notifications.md) | E-posta bildirimleri + imzalı izleme linki + viewer servisi |
| [`docs/10-why-frigate.md`](docs/10-why-frigate.md) | Frigate neden gerekli? Saf Haiku ile yapılamaz mı? |
| [`docs/11-tech-decisions.md`](docs/11-tech-decisions.md) | Teknoloji seçim kararları — Frigate, Python, Haiku, Postgres, n8n vs |
| [`ROADMAP.md`](ROADMAP.md) | PoC → Production milestone'ları |

## Mimari Özet

```
  ┌──────────────────────────────────────────────────────────────┐
  │                  Mevcut Sunucu (12 GB RAM)                   │
  │                                                              │
  │   [ Ubuntu 22.04 + SnipeIT ]  ────  ~4 GB                    │
  │                                                              │
  │   ┌──────────────  AI Stack  (~6 GB)  ─────────────────┐    │
  │   │                                                     │    │
  │   │   Frigate (CPU, sonra Coral USB) ───── 2.5 GB      │    │
  │   │   PostgreSQL (olay + renk log)  ───── 0.5 GB       │    │
  │   │   Bridge (zone state + LLM)     ───── 0.3 GB       │    │
  │   │   Mosquitto (MQTT)              ───── 0.05 GB      │    │
  │   │   Grafana (dashboard)           ───── 0.3 GB       │    │
  │   │   Viewer (FastAPI, e-posta linki) ─── 0.2 GB       │    │
  │   │                                                     │    │
  │   └─────────────────────────────────────────────────────┘    │
  └──────────────────────────────────────────────────────────────┘
              ▲                                ▲
              │ RTSP sub-stream (direct)       │ HTTP alarm
              │ kameralardan                   ▼
       Dahua IP kameralar              Dahua NVR (orijinal kayıt)
       (15 Coral + 10 Haiku motion     (DSS/SmartPSS panel görür)
        + 75 sadece NVR kaydı)
```

Detay için → [`docs/01-architecture.md`](docs/01-architecture.md).

## Lisans

[MIT](LICENSE) — özgür kullanım, atıf yeterli.

## İletişim

İbrahim Sümbül · [ibrahimsumbulll@gmail.com](mailto:ibrahimsumbulll@gmail.com) · [GitHub](https://github.com/ibrahimSumbul)
