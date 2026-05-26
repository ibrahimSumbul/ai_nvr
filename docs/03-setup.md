# 03 — Kurulum

> ✅ **M1 aktif.** Adım 1-6 (Docker iskelet + bridge + Postgres + MQTT) çalışır. Adım 7 (Dahua alarm) M4'te, Grafana dashboard'ları M5'te, kapı + e-posta + viewer M6.5'te aktive olur.

## Önkoşullar

- Ubuntu 22.04 (kontrol: `lsb_release -a`)
- Docker 24+ ve Docker Compose v2 (`docker compose version`)
- Sunucu en az 8 GB boş RAM
- Dahua kameraların RTSP URL'leri ve şifresi
- Anthropic API key (`sk-ant-...`)

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
# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxx
ANTHROPIC_MODEL=claude-haiku-4-5-20251001

# Postgres
POSTGRES_USER=ainvr
POSTGRES_PASSWORD=<güçlü-şifre>
POSTGRES_DB=ainvr

# Mosquitto
MQTT_USER=ainvr
MQTT_PASSWORD=<güçlü-şifre>

# Dahua NVR (sadece alarm push için, RTSP değil!)
DAHUA_NVR_HOST=192.168.10.10
DAHUA_NVR_USER=admin
DAHUA_NVR_PASSWORD=<NVR-şifresi>

# Frigate restream (opsiyonel — viewer için)
FRIGATE_RTSP_PASSWORD=<frigate-restream-için>

# Bütçe (PoC: 10, Production: 25)
LLM_MONTHLY_BUDGET_USD=10

# SMTP (Milestone 6.5 sonrası)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=ainvr@example.com
SMTP_PASSWORD=<gmail-app-password>
SMTP_FROM="AI NVR <ainvr@example.com>"
SMTP_TO_DEFAULT=guvenlik@example.com

# Viewer (Milestone 6.5 sonrası)
PORTAL_URL=https://ainvr.example.com
VIEW_TOKEN_SECRET=<32-char-random>
VIEW_TOKEN_TTL_DAYS=7
```

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

`frigate/config.yml`'de `pilot_kamera` örneği bu URL'yi kullanır.

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
M1'de şu log satırlarını görmelisiniz:

```
bridge.starting        version=0.1.0
db.connecting          host=postgres port=5432
db.connected
bridge.ready           msg='Bridge ready, waiting for events'
mqtt.connecting        host=mqtt port=1883 topic=frigate/#
mqtt.connected
```

`Zone state machine initialized` mesajı M2'de aktif olacak (zone state machine M2 kapsamı).

### DB'yi kontrol
```bash
docker exec -it ainvr-postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c \
  "SELECT * FROM zone_events ORDER BY ts DESC LIMIT 10;"
```

### Grafana
- `http://<server-ip>:3000`
- Username: `admin`, ilk açılışta şifre değiştirin
- "AI NVR Overview" dashboard yüklü olmalı

## Adım 7: Dahua entegrasyon testi

```bash
docker exec ainvr-bridge python -m bridge.dahua test-alarm
```

DSS/SmartPSS'te "External Alarm" beklemeli.

## Adım 8: PoC olarak çalıştır

İlk 7 gün:
- Sadece 2–3 pilot kamera açık tutun
- `docs/04-zone-rules.md`'ye göre zone tanımlarını kalibre edin
- Yanlış pozitifleri Frigate `min_score` ve `threshold` ile düzeltin
- Haiku maliyetini Grafana'dan günlük takip edin

## Sorun Giderme

→ [`docs/08-operations.md#sorun-giderme`](08-operations.md#sorun-giderme)
