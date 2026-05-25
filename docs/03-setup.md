# 03 — Kurulum

> 🚧 **Henüz aktif değil.** Bu doküman planlanan kurulum akışını anlatır. Milestone 1 tamamlanınca komutlar canlı olacak.

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
sudo git clone https://github.com/ibrahimsumbul/ibrahimsumbul.git ai-nvr-deploy
sudo chown -R $USER:$USER ai-nvr-deploy
cd ai-nvr-deploy/ai-nvr
git checkout claude/ai-camera-nvr-integration-QaKPd
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

## Adım 4: Kameraları `frigate/config.yml`'ye ekle

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

## Adım 5: Stack'i başlat

```bash
docker compose up -d
docker compose ps
```

Beklenen çıktı (örnek):

```
NAME              STATUS         PORTS
ainvr-frigate     Up (healthy)   0.0.0.0:5000->5000/tcp
ainvr-postgres    Up (healthy)   5432/tcp
ainvr-mqtt        Up (healthy)   1883/tcp
ainvr-bridge      Up (healthy)
ainvr-grafana     Up (healthy)   0.0.0.0:3000->3000/tcp
```

## Adım 6: Doğrulama

### Frigate UI
- Tarayıcıdan: `http://<server-ip>:5000`
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
"Connected to MQTT", "Connected to Postgres", "Zone state machine initialized" görmelisiniz.

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
