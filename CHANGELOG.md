# Changelog

Bu dosya tüm önemli değişiklikleri kayıt altına alır.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) tarzı.

## [Unreleased] — PoC çalışması

### Added
- Proje dokümantasyon iskeleti (`docs/01..11`)
- `README.md` proje genel bakış
- `ROADMAP.md` PoC → Production milestone planı
- `.gitignore` (Python, Docker, Node, IDE)
- **Kapı olayları (`door.traversal`)** — saniye hassasiyetinde giriş/çıkış logu
- **E-posta bildirim + viewer servisi** — imzalı link ile snapshot + klip izleme
- **Milestone 6.5** — kapı olayları + e-posta bildirimi
- `docs/09-notifications.md`
- `docs/10-why-frigate.md` — saf Haiku neden yapılmaz teknik gerekçeler
- `docs/11-tech-decisions.md` — teknoloji seçim kararları (Frigate, Python, Haiku, Postgres, n8n vs alternatifler)
- **MIT License** — portfolio için açık kaynak
- README portfolio-friendly açılış (badges + lead paragraph + cross-link to tech decisions)

### Changed
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
- Henüz çalışan kod yok, sadece tasarım dokümanları.
- Branch: `claude/ai-camera-nvr-integration-QaKPd`
