# 03 — Kurulum

> ✅ **Çekirdek pipeline çalışıyor** (M1–M4). Docker stack + zone state machine + Ollama tır analizi + Dahua alarm + Grafana dashboard aktif. Kapı olayları M6.5'te eklenecek; bildirim **DMSS mobil push** ile (NVR external alarm üzerinden — ayrı e-posta/viewer altyapısı kapsam dışı, bkz. ROADMAP).

## Önkoşullar

- Linux (Ubuntu 22.04 önerilir) veya macOS (dev — Colima/Docker Desktop)
- Docker 24+ ve Docker Compose v2 (`docker compose version`)
- Sunucu en az 8 GB boş RAM
- Dahua kameraların RTSP URL'leri ve şifresi (veya dev için MediaMTX test stream)
- **[Ollama](https://ollama.com)** — lokal LLM (tır renk analizi). Host'ta çalışır, container ona `host.docker.internal:11434` üzerinden erişir.
- _(Planlı)_ Anthropic bulut hibrit — `LLM_PROVIDER` switch altyapısı hazır ama implementasyon henüz yok; şu an yalnızca `ollama` destekleniyor

## Adım 1: Docker kurulumu (zaten varsa atla)

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
docker --version
```

## Adım 2: Repo clone

```bash
cd /opt
sudo git clone https://github.com/ibrahimSumbul/ai_nvr.git
sudo chown -R $USER:$USER ai_nvr
cd ai_nvr
```

## Adım 3: `.env` hazırlığı

```bash
cp .env.example .env
nano .env
```

Doldurulacak alanlar:

```ini
# LLM — lokal Ollama (şu an tek desteklenen provider, $0)
LLM_PROVIDER=ollama
LLM_OLLAMA_URL=http://host.docker.internal:11434
LLM_OLLAMA_MODEL=qwen2.5vl:7b
# Bulut hibrit planlı (henüz yok): ANTHROPIC_API_KEY=sk-ant-xxx

# Postgres
POSTGRES_USER=ainvr
POSTGRES_PASSWORD=<güçlü-şifre>
POSTGRES_DB=ainvr

# Mosquitto
MQTT_USER=ainvr
MQTT_PASSWORD=<güçlü-şifre>

# Dahua NVR external alarm (M4) — RTSP değil, sadece alarm push!
# Dev'de false bırak (gerçek NVR yoksa); production'da true.
DAHUA_ALARM_ENABLED=false
DAHUA_NVR_HOST=192.168.10.10
DAHUA_NVR_USER=admin
DAHUA_NVR_PASSWORD=<NVR-şifresi>

# Grafana
GRAFANA_ADMIN_PASSWORD=<güçlü-şifre>

# Frigate RTSP şifresi (kameralar için)
FRIGATE_RTSP_PASSWORD=<frigate-restream-için>
```

> SMTP / viewer (e-posta + imzalı izleme linki) **kapsam dışı** — bildirim DMSS mobil push ile yapılır (bkz. [`docs/05`](05-dahua-integration.md#dmss-mobil-push-bildirimi)). `.env.example` bu opsiyonel değişkenleri referans olarak içerebilir; aktif kullanılmaz.

## Adım 4: Kameraları + zone'ları ekle (M2+)

Detay → [`docs/05-dahua-integration.md`](05-dahua-integration.md#rtsp-urlleri)

Her kamera için **sadece sub-stream** çekilir (main-stream NVR'da kalır):

```yaml
cameras:
  cam_giris:
    ffmpeg:
      inputs:
        # Direct kamera IP — NVR'a yük binmez
        - path: rtsp://admin:PWD@192.168.10.21:554/cam/realmonitor?channel=1&subtype=1
          roles: [detect]
        # NOT: 'record' role yok — kayıt zaten NVR yapıyor.
        # Viewer için clip lazımsa Frigate kendi geri tampondan üretir.
    detect:
      width: 640
      height: 480
      fps: 5
    zones:
      arac_giris:
        coordinates: 0,480,640,480,640,200,0,200
```

### Bridge zone tanımı

Her aktif izlenen alan için `bridge/config/zones.yaml`'a tanım ekle (bind mount ile bridge container'a yansır, image rebuild gerek değil):

```yaml
zones:
  - name: depo_giris              # bridge için unique adres
    camera: cam_giris              # frigate/config.yml'deki kamera adı
    frigate_zone: arac_giris       # frigate/config.yml içindeki zone adı
    rules:
      enabled: true
      type: room                   # 'room' (state machine) | 'door' (M6.5'te traversal)
      first_entry_alarm: true
      exit_timeout_seconds: 60
      min_person_score: 0.6
      active_hours: "00:00-23:59"  # çapraz gece (18:00-08:00) destekli
      alert_on_empty_arrival: true
```

Davranış (bkz. [`docs/04-zone-rules.md`](04-zone-rules.md)):
- **DB insert her zaman** yapılır (event log).
- **Alarm** sadece `first_entry_alarm AND active_hour AND alert_on_empty_arrival` üçlüsünde tetiklenir; metadata'da `alarm_emitted` flag'i ile işaretlenir.
- `active_hours` örn. "18:00-08:00" mesai-dışı izleme için kullanılır; mesai-içi girişler kayda alınır ama alarm üretmez.

Değişiklik sonrası: `docker compose restart bridge` (zones.yaml bind mount, image rebuild gerek değil).

### M2 pilot için kısayol (MediaMTX test stream)

Gerçek kamera yoksa MediaMTX gibi bir RTSP sunucusu ile test stream'i kullan:

```bash
# MediaMTX'i host makinede çalıştır (örn. rtsp://localhost:8554/cam_test)
# Container içinden erişim: rtsp://host.docker.internal:8554/cam_test
```

`frigate/config.yml`'de `cam_test` örneği bu URL'yi kullanır.

## Adım 4.5: Ollama modeli (lokal LLM)

Tır renk analizi host'taki Ollama'da koşar. Modeli indir:

```bash
# Ollama kurulu değilse: https://ollama.com (Linux: curl -fsSL https://ollama.com/install.sh | sh)
ollama serve          # servis çalışmıyorsa (Linux'ta systemd ile otomatik)
ollama pull qwen2.5vl:7b   # ~5.6 GB vision model
ollama list                # indirildiğini doğrula
```

Container Ollama'ya `host.docker.internal:11434` üzerinden erişir (Linux'ta bu host adı Docker 20.10+ ile `--add-host` olmadan da çalışır; sorun olursa `LLM_OLLAMA_URL`'i host IP'siyle ayarla).

## Adım 5: Stack'i başlat

```bash
docker compose up -d
docker compose ps
```

Beklenen çıktı (örnek):

```
NAME              STATUS         PORTS
ainvr-frigate     Up (healthy)   0.0.0.0:5100->5000/tcp
ainvr-postgres    Up (healthy)   5432/tcp
ainvr-mqtt        Up (healthy)   1883/tcp
ainvr-bridge      Up (healthy)
ainvr-grafana     Up (healthy)   0.0.0.0:3000->3000/tcp
```

### Veritabanı şeması (ilk kurulumda zorunlu)

Tablolar Alembic migrasyonu ile oluşturulur. **Bu adım atlanırsa** bridge
`relation "zone_events" does not exist` hatasıyla restart döngüsüne girer:

```bash
docker compose run --rm --entrypoint "" bridge alembic upgrade head
docker compose restart bridge
```

Beklenen: `Running upgrade -> 0001, Init: zone_events, door_events, truck_events, llm_usage, camera_status`.

### Frigate config mount mode

`docker-compose.yml`'de `./frigate/config.yml` bind mount mode `FRIGATE_CONFIG_MODE` env var ile kontrol edilir:

- **Dev (`rw`, default)** — Frigate UI Zone Editor'dan polygon/zone değişiklikleri host dosyasına persist eder, `git diff` ile görüp commit'leyebilirsin.
- **Production (`ro`)** — Mount read-only. Config sadece git üzerinden değişir; UI'dan yapılan save başarısız olur. CI/CD ile config değişiklikleri kontrollü hale gelir.

`.env`'de:
```bash
FRIGATE_CONFIG_MODE=rw   # dev (default)
# FRIGATE_CONFIG_MODE=ro # production
```

Mode değişiklikten sonra `docker compose up -d frigate` ile frigate container'ı recreate gerekir (mount değişikliği için).

## Adım 6: Doğrulama

### Frigate UI
- Tarayıcıdan: `http://<server-ip>:5100` (macOS AirPlay Receiver port 5000'i kullanır)
- Her kamera için canlı görüntü, person/truck detection kutuları görünmeli.

### MQTT akışı
```bash
docker exec ainvr-mqtt mosquitto_sub -u $MQTT_USER -P $MQTT_PASSWORD -t 'frigate/#' -v
```
Kameraya el sallayın → event gelir.

### Bridge log
```bash
docker compose logs -f bridge
```
Şu log satırlarını görmelisiniz:

```
bridge.starting        version=0.2.0
db.connecting          host=postgres port=5432
db.connected
bridge.ready           cameras=5 zones=5 llm_provider=ollama llm_model=qwen2.5vl:7b
mqtt.connecting        host=mqtt port=1883 topic=frigate/events
mqtt.connected
```

Bir kamerada hareket olunca `zone.first_entry` + `zone_event.inserted`, bir kamyon görülünce `truck.analyzed` satırları akar.

### DB'yi kontrol
```bash
docker exec -it ainvr-postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c \
  "SELECT * FROM zone_events ORDER BY ts DESC LIMIT 10;"
```

### Grafana
- `http://<server-ip>:3000`
- Username: `admin`, şifre `.env` `GRAFANA_ADMIN_PASSWORD`
- **AI NVR — Genel Bakış** dashboard otomatik provision edilir (datasource + paneller hazır).

## Adım 7: Dahua external alarm testi (M4)

`.env`'de `DAHUA_ALARM_ENABLED=true` + `DAHUA_NVR_*` doldurup `docker compose up -d bridge`.

Bir izlenen alana giriş tetikle (gerçek kişi veya test stream). Bridge log:

```bash
docker compose logs -f bridge | grep dahua
# Başarılı:   dahua.alarm_sent     zone=... channel=...
# Erişilemez: dahua.alarm_pending  (retry worker tekrar dener)
```

Başarılı tetiklemede DSS/SmartPSS panelinde **"External Alarm"** belirir (mobil push DMSS açıksa). NVR'ın `alarm.cgi` virtual input desteği için: Setup → Event → Alarm → Local Alarm. Yöntem/uyumluluk: [`docs/05-dahua-integration.md`](05-dahua-integration.md#http-alarm-gönderme).

> Gerçek NVR yoksa `DAHUA_ALARM_ENABLED=false` bırak — olaylar yine Postgres'e + Grafana'ya yazılır, sadece NVR push atlanır.

## Adım 8: PoC olarak çalıştır

İlk 7 gün:
- Sadece 2–3 pilot kamera açık tutun
- `docs/04-zone-rules.md`'ye göre zone tanımlarını kalibre edin
- Yanlış pozitifleri Frigate `min_score` ve `threshold` ile düzeltin
- Frigate Zone Editor ile polygon'ları gerçek alana göre daraltın
- Ollama tır analizinin gecikme/başarı oranını **AI NVR — Genel Bakış** dashboard'undan takip edin

## Sorun Giderme

→ [`docs/08-operations.md#sorun-giderme`](08-operations.md#sorun-giderme)
