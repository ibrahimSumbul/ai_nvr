# 08 — İşletim

Sistem unutulup ayda 5 dakika bakılacak şekilde tasarlanır. Bu doküman onu mümkün kılan rutinleri yazar.

## Günlük

- Bakılması gereken bir şey yok. Grafana'da kırmızı çubuk varsa açıp bak.

## Haftalık

- [ ] Grafana "AI NVR Overview" dashboard kontrol
  - Alan giriş trend'i normal mi?
  - LLM çağrı sayısı bütçe içinde mi?
  - Yanlış pozitif şüphesi var mı?
- [ ] Disk doluluk: `df -h /var/lib/docker`
- [ ] Postgres `zone_events` boyutu

## Aylık

- [ ] LLM toplam maliyetini gözden geçir
- [ ] Frigate kalibrasyonu (gerekirse `min_score` ayarı)
- [ ] DB backup doğrulaması
- [ ] Docker image güncellemeleri:
  ```bash
  docker compose pull
  docker compose up -d
  ```

## İzleme

### Grafana Dashboard'ları

| Dashboard | İçerik |
|---|---|
| AI NVR Overview | Olay sayısı, alan başına aktivite, LLM maliyet |
| Frigate Performance | CPU/RAM, FPS, detection latency |
| LLM Usage | Çağrı tipleri, başarı oranı, cache hit, günlük maliyet |
| Errors | Bridge hata logları, Dahua alarm fail, retry kuyruk |

### Alert Kuralları (Grafana → Telegram veya email)

| Kural | Eşik | Aksiyon |
|---|---|---|
| LLM aylık maliyet (PoC bütçe $10) | > $8 (%80) | Uyarı |
| LLM aylık maliyet (PoC) | > $10 | LLM disable + acil uyarı |
| LLM aylık maliyet (Production bütçe $25) | > $20 (%80) | Uyarı |
| LLM aylık maliyet (Production) | > $25 | LLM disable + acil uyarı |
| **Kamera offline** | > 60 sn frame yok | **Uyarı + e-posta** |
| Kamera offline (kritik kapı/oda) | > 60 sn | **Acil + telefon push** |
| Postgres bağlantı kopuk | herhangi | Acil |
| Disk doluluk | > %80 | Uyarı |
| Disk doluluk | > %95 | Acil + auto-cleanup |
| Bridge container restart | > 3/saat | Uyarı |
| Dahua alarm fail | > %20 | Uyarı |
| SMTP fail | > 5 ardışık | Uyarı (e-posta gitmiyor) |
| Sunucu RAM | > %85 | Uyarı (SnipeIT etkilenebilir) |

> NVR'a RTSP pull yapmıyoruz, NVR CPU izlemeye gerek yok. NVR'ın kendi sağlık göstergesi orijinal Dahua paneliyle takip edilir.

### Kamera Offline Detayı

Frigate her kamera için `frigate/<cam>/available` MQTT topic'inde durumu yayar. Bridge bunu dinler:

- `available=False` → bridge başlangıçta 30 sn bekler (ağ glitchi olabilir)
- 60 sn devam ederse → DB'ye `camera_offline` event yazılır
- Kritik kameralar (kapı, kasa, ana giriş) için → derhal e-posta gönderilir
- Online'a dönünce → "Kamera tekrar online" log + opsiyonel e-posta

Konfigürasyonda kritik kameralar belirtilir:

```yaml
# bridge/config/cameras.yaml
cameras:
  ana_kapi:
    critical: true
    offline_alert_email: ["guvenlik@example.com", "mudur@example.com"]
  depo_giris:
    critical: true
  arka_park:
    critical: false   # sadece log
```

## Backup

### Postgres

```bash
# Otomatik günlük yedek (cron)
0 3 * * * docker exec ainvr-postgres pg_dump -U ainvr ainvr | \
  gzip > /backup/ainvr_$(date +\%Y\%m\%d).sql.gz
```

- 30 gün local retention
- Haftada bir off-site (rsync to remote, BackBlaze B2 vs.)

### Snapshot dosyaları

- Frigate kendi rotation yapar (config'de `retain` günü).
- Olay snapshot'ları (`/var/lib/ainvr/snapshots`) → 90 gün retain.
- Cron job ile temizlik:
  ```bash
  find /var/lib/ainvr/snapshots -type f -mtime +90 -delete
  ```

### Restore Testi

3 ayda bir backup'tan yepyeni bir test instance restore et, çalıştır, doğrula.

## Logging

Tüm container'lar Docker JSON file driver'a log atar. Log rotation:

```yaml
# docker-compose.yml içinde her service için
logging:
  driver: json-file
  options:
    max-size: 100m
    max-file: 5
```

## Sorun Giderme

### "Frigate kamerayı göremiyor"

```bash
docker logs ainvr-frigate 2>&1 | grep <cam_name>
ffmpeg -i <rtsp_url> -t 5 -c copy /tmp/test.mp4  # elle test
```

Olası nedenler:
- Şifre yanlış (özel karakterleri URL-encode etmeyi unutma: `@` → `%40`)
- Network: AI sunucu kamera VLAN'ına erişemiyor
- H.265 yavaş: kamerayı H.264'e geç

### "Çok yanlış-pozitif alarm geliyor"

1. Frigate UI → Settings → Debug → her objenin score'unu izle
2. `frigate/config.yml`'de `min_score` arttır (0.6 → 0.75)
3. Zone'u daralt — koridorun tamamı yerine sadece geçiş noktası

### "LLM cevap vermiyor"

```bash
docker logs ainvr-bridge | grep -i "anthropic\|llm"
# Manuel test
docker exec ainvr-bridge python -m bridge.llm test-truck-color sample.jpg
```

### "Dahua alarm gitmedi"

```bash
docker exec ainvr-bridge python -m bridge.dahua diagnose
```

Çıktıda hangi API'lerin destek geldiği listelenir.

### "Sunucu RAM doldu, SnipeIT yavaşladı"

```bash
docker stats --no-stream
```

En çok yiyen container'ı bul. Genelde Frigate. Çözüm:
- Kamera FPS'i 5 → 3'e düşür
- Sub-stream çözünürlüğünü 640×480 → 480×360
- Coral USB ekle (bekleyen iş)

### "Postgres connection refused"

```bash
docker compose ps
docker logs ainvr-postgres --tail 50
```

Genelde disk dolu veya max_connections aşılmış.

## Yeni Kamera Ekleme

1. `frigate/config.yml`'ye ekle (RTSP URL, zones, detect ayarları)
2. `bridge/config/zones.yaml`'ye state machine kuralı ekle (eğer aktif izlenecekse)
3. `docker compose restart frigate bridge`
4. Frigate UI'dan yeni kamerayı doğrula
5. Grafana dashboard'a değişken ekle

## Yeni Bir Alan Kuralı Ekleme

Aktif izlenen alanı 11'e çıkarmak:

1. `bridge/config/zones.yaml` → yeni zone tanımı
2. `frigate/config.yml` → ilgili kamerada zone koordinatları
3. `docker compose restart bridge frigate`
4. Test: o alana gir, ilk-giriş alarmı geldiğini doğrula

## Sistemin Üzerine Yapılan Geliştirmeler

Tüm değişiklikler git üzerinden:

1. `git checkout claude/ai-camera-nvr-integration-QaKPd`
2. `git pull`
3. Edit → test (local Docker)
4. `git commit -m "..."`
5. `git push`
6. Production sunucuya: `cd /opt/ai-nvr-deploy && git pull && docker compose up -d`

## Kapanış Notu

Sistem **olayları kaçırmamak** ve **operatörü gece aramamak** üzerine kurulmuştur. Eğer:

- Operatör 3'ten fazla "boşa alarm" görüyorsa → kalibrasyon gerekli
- 1 hafta hiç alarm gelmediyse → bir şey kırılmış olabilir, test et

Bu denge tutturulduğu sürece sistem işini yapıyor demektir.
