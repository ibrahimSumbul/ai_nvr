# 08 — İşletim (Operasyon Runbook)

Sistem unutulup ayda birkaç dakika bakılacak şekilde tasarlanır. Bu doküman onu mümkün kılan rutinleri, izleme ve sorun giderme adımlarını gerçek stack'e göre yazar.

## Servisler

| Servis | Container | Rol |
|---|---|---|
| Frigate | `ainvr-frigate` | RTSP detect (CPU/Coral), MQTT event + snapshot |
| Bridge | `ainvr-bridge` | zone/door state machine, Ollama tır analizi, Dahua alarm, kamera izleme |
| PostgreSQL | `ainvr-postgres` | olay + log (`zone_events`, `door_events`, `truck_events`, `llm_usage`, `camera_status`) |
| Mosquitto | `ainvr-mqtt` | MQTT broker (Frigate → Bridge) |
| Grafana | `ainvr-grafana` | dashboard (`AI NVR — Genel Bakış`) |
| Ollama | **host** (container değil) | lokal vision LLM (`qwen2.5vl:7b`), bridge `host.docker.internal:11434`'e erişir |

Sağlık: `docker compose ps` → 5 container `healthy`. Ollama: `curl -s http://localhost:11434/api/tags`.

## Rutin

**Günlük** — bakılması gereken bir şey yok. Grafana'da "Çevrimdışı Kamera" stat'ı kırmızıysa ([İzleme](#izleme)) bak.

**Haftalık**
- [ ] Grafana **AI NVR — Genel Bakış**: alan giriş trendi normal mi, LLM başarı oranı yüksek mi, bekleyen Dahua alarm 0 mı, çevrimdışı kamera var mı
- [ ] Disk: `df -h /var/lib/docker`
- [ ] Snapshot disk: `du -sh /var/lib/ainvr/snapshots`

**Aylık**
- [ ] Frigate kalibrasyonu (gerekirse `min_score`/`threshold`)
- [ ] DB backup doğrulaması (restore testi)
- [ ] Image güncellemeleri: `docker compose pull && docker compose up -d`

> **LLM maliyeti** izlenmez — Ollama lokal, marjinal maliyet $0. İzlenen metrik LLM **gecikme/başarı oranı** (Grafana). Donanım yetmiyorsa Coral USB (M6).

## İzleme

### Grafana — AI NVR — Genel Bakış

`http://<sunucu>:3000` (admin / `GRAFANA_ADMIN_PASSWORD`). Dashboard otomatik provision edilir (datasource + paneller). Paneller:

| Panel | Anlam |
|---|---|
| İlk Giriş (24s) | Son 24 saatteki zone `first_entry` sayısı |
| Kamyon Olayı | Toplam `truck_events` |
| LLM Başarı Oranı | Ollama çağrı başarı % |
| Dahua Alarm — Bekleyen | Gönderilememiş (pending) alarm sayısı (0 olmalı) |
| Alan Başına İlk Giriş | Saatlik bar, zone bazında |
| Kamyon Çekici Rengi | Renk dağılımı (donut) |
| LLM Gecikme | Ortalama saatlik inference süresi (ms) |
| Son Zone Olayları | Son 20 olay tablosu |
| **Çevrimdışı Kamera** | `is_online=false` kamera sayısı (1+ kırmızı) |
| **Kamera Durumu** | Kamera / online / son görülme / uyarıldı |

### Bridge log

```bash
docker compose logs -f bridge
```
Önemli satırlar: `zone.first_entry`, `door.entry`/`door.exit`, `truck.analyzed`, `camera.offline`/`camera.recovered`, `dahua.alarm_sent`/`zone.dahua_alarm_pending`.

## Bildirim & Uyarı

**Olay bildirimi DMSS mobil push ile** — bridge olayı Dahua NVR'a external alarm gönderir, NVR kendi push kuralıyla DMSS app'e iletir (bkz. [`05-dahua-integration.md`](05-dahua-integration.md#dmss-mobil-push-bildirimi)). Ayrı e-posta/SMS/Telegram **yok** (kapsam dışı).

| Olay | Mekanizma |
|---|---|
| Zone ilk giriş (alarm_emitted) | Dahua external alarm → DMSS |
| Kapı geçişi (giriş/çıkış) | Dahua external alarm → DMSS |
| **Kamera offline** | Dahua external alarm (`camera_offline`) → DMSS + Grafana paneli |
| **Disk doluluk** | `DiskMonitor` eşik (`disk_warn_threshold_pct`, default %85) → Dahua external alarm (`disk_full`) → DMSS + Grafana "Disk Doluluk" paneli |
| RAM | Grafana panel (opsiyonel) — perf harness ayrıca raporlar |

> NVR'a RTSP pull yapılmaz → NVR CPU izlenmez. NVR'ın kendi sağlığı orijinal Dahua panelinden takip edilir.

### Kamera Offline (gerçek davranış)

`CameraMonitor` (`bridge/cameras.py`) Frigate `/api/stats`'ı `camera_check_interval_s` (default 30s) periyodunda çeker. Her kameranın `camera_fps`'i izlenir:

- `camera_fps > 0` → canlı: `camera_status.last_seen_at` güncellenir, `is_online=true`
- `camera_fps == 0` ve son görülmeden bu yana `camera_offline_threshold_s` (60s) geçti → **offline**: `is_online=false`, bir kez uyarılır (`offline_alert_sent`), Dahua client varsa external alarm (`camera_channels` → NVR channel)
- Tekrar `camera_fps>0` → recovery: online, alert flag reset
- Frigate erişilemezse kameralar offline **işaretlenmez** (Frigate down ≠ kamera down)

Durum sorgusu:
```bash
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB \
  -c "SELECT camera_id, is_online, last_seen_at FROM camera_status ORDER BY is_online, camera_id;"
```

### Disk Doluluk + Snapshot Retention (gerçek davranış)

`DiskMonitor` (`bridge/disk.py`) `disk_check_interval_s` (default 300s) periyodunda çalışır. **Enterprise model** — "disk dolunca en eskiyi sil" baskı-altı FIFO **değil**; disk hiç dolmasın diye sürekli zaman-tabanlı budama + eşikte erken alarm:

- **Snapshot budama** (`snapshot_prune_interval_s`, default saatlik): bridge snapshot store'da (`/var/lib/ainvr/snapshots`) mtime'ı `snapshot_retention_days`'ten (default 90g) eski dosyalar silinir → snapshot dizini unbounded büyümez. Uygulama-içi garanti (harici cron'a bağlı değil).
- **Doluluk eşiği**: snapshot dizininin dosya sistemi (`shutil.disk_usage`) izlenir; doluluk `disk_warn_threshold_pct` (default %85) aşılınca **bir kez** Dahua external alarm (`disk_full`) → DMSS. Histerezis: flag ancak doluluk (eşik − `disk_recover_margin_pct`) altına düşünce resetlenir (eşik etrafında flapping → tekrar tekrar alarm önlenir).
- Ölçümler `disk_status` tablosuna upsert edilir (mount başına tek satır); Grafana "Disk Doluluk" + "Snapshot Disk" + "Disk Durumu" panelleri buradan okur.

> **Ham video FIFO kapsam dışı**: sürekli/olay kaydı Dahua NVR'da; NVR kendi ring-buffer'ını (en eskiyi üzerine yazma) native yönetir. Bu AI stack video tutmaz (`frigate record.enabled=false`), sadece kendi snapshot'larını budar.

Durum sorgusu:
```bash
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB \
  -c "SELECT mount, used_pct, snapshot_files, last_pruned_at, alert_sent FROM disk_status;"
```

## Performans Testi (M5)

`bridge/perf.py` — stack ayaktayken CPU/RAM/gecikme örnekleyip M5 kabul kriterlerine göre pass/fail raporu üreten harness. **Host'ta** çalışır (`docker stats` için), Frigate'e `/api/stats` ile erişir (default `http://localhost:5100`).

```bash
make perf                                                   # 60s duman testi (5s aralık)
make perf ARGS="--duration 86400 --interval 30 --out perf-24h"   # gerçek 24 saat koşum
```

Üç check (M5 doğrulama kriterlerine birebir):

| Check | Metrik | Default eşik |
|---|---|---|
| **RAM stabil** | container bellek büyümesi (ilk→son %10 pencere) | ≤ %20 |
| **CPU başı boş** | detector p95 inference süresi | ≤ 200 ms |
| **Kaçan olay <%5** | kamera `skipped_fps / camera_fps` p95 | ≤ %5 |

Eşik aşımı ilgili çekirdek kaynağının dolduğunu gösterir; özellikle inference süresi fırlıyorsa **Coral USB** (M6) zamanı gelmiştir. Eşikler CLI ile override edilir (`--max-mem-growth`, `--max-inference`, `--max-skipped`).

Çıktı:
- `<out>.csv` — long-format zaman serisi (`timestamp,kind,name,metric,value`), Grafana/plot dostu
- `<out>.json` — özet (per-container/kamera/detector istatistik + checks + pass/fail)
- stdout tablo + exit code (0 geçti / 1 kaldı → CI/cron uyumlu)

**Notlar**:
- macOS'te host `:5000` AirPlay Receiver'da; compose Frigate'i `5100:5000` yayınlar → harness default'u `:5100`.
- Frigate `/api/stats` erişilemezse Frigate'e dayalı check'ler **"veri yok" ile başarısız** olur (eksik koşum yanlışlıkla GEÇTİ/exit 0 dönmez); `docker stats` (RAM) yine toplanıp ayrı raporlanır.
- Dev ortamında: `colima start` + `make up`, stream'ler akarken çalıştır (docs/03-setup.md).

## Backup

### Postgres
```bash
# Günlük yedek (cron, örn 03:00)
0 3 * * * docker exec ainvr-postgres pg_dump -U ainvr ainvr | \
  gzip > /backup/ainvr_$(date +\%Y\%m\%d).sql.gz
```
- 30 gün local retention + haftalık off-site (rsync / B2 vb.)
- Restore: `gunzip -c yedek.sql.gz | docker exec -i ainvr-postgres psql -U ainvr -d ainvr`

### Named volume'lar
`postgres-data` (DB), `frigate-config` (Frigate user DB + JWT — kaybı login sıfırlar), `grafana-data`, `ainvr-media` (snapshot). `docker run --rm -v <volume>:/v -v $PWD:/b alpine tar czf /b/<volume>.tgz -C /v .` ile arşivlenebilir.

### Snapshot dosyaları
`/var/lib/ainvr/snapshots` budama artık **uygulama-içi** (`DiskMonitor`, `SNAPSHOT_RETENTION_DAYS` default 90g) — ayrı cron gerekmez (bkz. "Disk Doluluk + Snapshot Retention" yukarıda). Bridge çalışmıyorken manuel eşdeğer:
```bash
find /var/lib/ainvr/snapshots -type f -mtime +90 -delete
```

### Restore testi
3 ayda bir yedekten temiz bir test instance restore edip çalıştır, doğrula.

## Logging

Tüm container'lar Docker `json-file` driver'a log atar; rotation `docker-compose.yml`'de zaten tanımlı (`max-size`, `max-file`) — ek log rotation gerekmez:
```yaml
logging:
  driver: json-file
  options: { max-size: "100m", max-file: "5" }
```

## Restart & Recovery

```bash
docker compose restart bridge          # tek servis
docker compose up -d                   # tümü (config değişikliği sonrası)
```

**İlk kurulum / yeni volume** — şema migrasyonu zorunlu (yoksa bridge `relation "zone_events" does not exist` ile crash):
```bash
docker compose run --rm --entrypoint "" bridge alembic upgrade head
```

**Restart sonrası durum (recovery):**
- **Zone** state machine son `first_entry`'den DB ile geri yüklenir (`restore_from_db`) — in-flight oda olayı kaçmaz.
- **Door** açık oturum bellektedir → restart'ta sıfırlanır; sonraki geçiş "giriş" sayılır (kabul edilen basitleştirme).
- **Camera status** DB'de kalıcıdır; CameraMonitor bir sonraki turda yeniden değerlendirir.

## Sorun Giderme

### Colima / Docker ayağa kalkmıyor (dev — macOS)
`docker` "Cannot connect to daemon" → Colima uyku/restart ile kapanmış:
```bash
colima start          # son config'i (8 CPU) hatırlar
docker compose up -d
```
Yeni shell'de context `default`'a dönerse: `docker context use colima`.

### Bridge crash: "relation ... does not exist"
Migrasyon atlanmış → `docker compose run --rm --entrypoint "" bridge alembic upgrade head`.

### "Frigate kamerayı göremiyor"
```bash
docker compose logs ainvr-frigate 2>&1 | grep <cam>
ffmpeg -rtsp_transport tcp -i "<rtsp_url>" -t 5 -c copy /tmp/test.mp4   # elle test
```
Nedenler: şifre/URL-encode (`@`→`%40`), network/VLAN erişimi, H.265 yavaş (H.264'e geç).

### "Çok yanlış-pozitif alarm"
1. Frigate UI → cam → Debug → obje score'larını izle
2. `frigate/config.yml` `min_score` artır (0.6 → 0.75)
3. Zone polygon'u daralt (Frigate UI Zone Editor; `FRIGATE_CONFIG_MODE=rw` ise host dosyasına yansır)

### "Ollama / LLM cevap vermiyor"
```bash
docker compose logs ainvr-bridge | grep -iE "llm|truck|ollama"
docker compose exec bridge python -c "import httpx; print(httpx.get('http://host.docker.internal:11434/api/tags').json())"
```
Nedenler: host'ta `ollama serve` çalışmıyor, model indirilmemiş (`ollama pull qwen2.5vl:7b`), büyük snapshot → timeout (latency Grafana'dan izlenir).

### "Dahua alarm gitmedi"
```bash
docker compose logs ainvr-bridge | grep dahua
```
`zone.dahua_alarm_pending` → NVR erişilemez (retry worker tekrar dener). `dahua.disabled` → `DAHUA_ALARM_ENABLED=false` (dev). Gerçek NVR + push kuralı: [`05-dahua-integration.md`](05-dahua-integration.md).

### "Sunucu RAM doldu"
```bash
docker stats --no-stream
```
Genelde Frigate. Çözüm: kamera `fps` 5→3, sub-stream çözünürlük düşür, Coral USB (M6). Ollama modeli ~6 GB RAM ister — host'ta yer olduğundan emin ol.

### "Postgres connection refused"
```bash
docker compose ps && docker compose logs ainvr-postgres --tail 50
```
Genelde disk dolu veya `max_connections`.

## Yeni Kamera Ekleme
1. `frigate/config.yml` → RTSP girişi + detect + zone polygon
2. `bridge/config/zones.yaml` → zone kuralı (`type: room` veya `door`, `dahua_channel`)
3. `docker compose restart frigate bridge` (ikisi de RW bind mount — rebuild gerekmez)
4. Frigate UI'dan canlı görüntüyü + Grafana'dan olayları doğrula

## Yeni Alan / Kapı Kuralı
1. `bridge/config/zones.yaml` → yeni zone (`room`/`door`)
2. `frigate/config.yml` → ilgili kamerada zone koordinatları
3. `docker compose restart bridge frigate`
4. Test: alana gir → `zone.first_entry` / kapıdan geç → `door.entry`

## Geliştirme & Deploy

Tüm değişiklikler git üzerinden (her PR subagent review + post-merge doğrulama — bkz. proje workflow):
```bash
git checkout -b feat/...      # branch
# edit + test (uv run --group dev pytest / ruff / mypy)
git commit && git push
gh pr create                  # subagent review → squash merge
# production: cd /opt/ai_nvr && git pull && docker compose up -d
```

## Kapanış

Sistem **olayları kaçırmamak** ve **operatörü gece aramamak** üzerine kurulur. 3'ten fazla "boşa alarm" → kalibrasyon; 1 hafta hiç olay yok → bir şey kırılmış olabilir, test et.
