# 09 — Bildirim ve İzleme Linkleri

Kapı geçişi ve kritik oda olaylarında **e-posta** gönderilir. E-posta içinde:

- Tetikleyen kamera, alan, zaman damgası
- Snapshot (inline + ek)
- **Web portalında olayı izleyecek imzalı bir link** (snapshot + opsiyonel 5 sn klip)

## Bileşenler

```
┌─────────────────────────────────────────────────────────────┐
│                          Bridge                              │
│                                                              │
│  Olay → Mailer.send_event_email(event_id)                    │
│           │                                                  │
│           ▼                                                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 1. View token üret (UUID + HMAC, 7 gün ömür)        │    │
│  │ 2. DB'ye token + expiry yaz                          │    │
│  │ 3. Snapshot/clip dosyasını snapshot store'a kaydet  │    │
│  │ 4. SMTP üzerinden HTML e-posta gönder               │    │
│  │ 5. E-posta linki: {PORTAL_URL}/v/{event_id}?t={token}│   │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │  Snapshot/Clip Store   │
              │  /var/lib/ainvr/media  │
              └────────────────────────┘
                          ▲
                          │ HTTPS (token ile)
                          │
              ┌────────────────────────┐
              │  Viewer (FastAPI)      │
              │  GET /v/{event_id}     │
              │  ?t={signed_token}     │
              └────────────────────────┘
```

## SMTP Konfigürasyonu

`.env`:

```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=ainvr@example.com
SMTP_PASSWORD=<app-password>
SMTP_TLS=starttls
SMTP_FROM="AI NVR <ainvr@example.com>"
SMTP_TO_DEFAULT=ibrahim@example.com,guvenlik@example.com

# Viewer
PORTAL_URL=https://ainvr.example.com
VIEW_TOKEN_SECRET=<32-char-random>
VIEW_TOKEN_TTL_DAYS=7
```

> Gmail kullanılıyorsa **App Password** üretilmeli (normal şifre kabul etmez).

## E-posta Şablonu

```
Konu: [AI NVR] Kapı geçişi — Ana Giriş — 2026-05-25 14:32:18

Merhaba,

Aşağıdaki olay tespit edildi:

  Kamera:    cam_kapi_01 (Ana Giriş)
  Alan:      door_ana_giris
  Yön:       İçeri (in)
  Giriş:     2026-05-25 14:32:18.345
  Çıkış:     2026-05-25 14:32:20.918
  Süre:      2.573 saniye

[Snapshot inline]

İncelemek için: https://ainvr.example.com/v/12345?t=eyJhbGc...

Bu link 7 gün geçerlidir.
```

HTML versiyonu opsiyonel (basit MIME multipart).

## View Token Şeması

Token = signed JWT-like string:

```
header:    base64({"alg":"HS256","typ":"AINVR"})
payload:   base64({"event_id":12345, "exp":1748524800, "type":"door"})
signature: HMAC-SHA256(header + "." + payload, VIEW_TOKEN_SECRET)
```

Viewer:
1. Token'ı doğrula
2. `exp` kontrolü
3. `event_id` ile DB'den olay metadatasını çek
4. Olayın `view_token` alanı eşleşiyor mu? (revoke desteği)
5. Snapshot ve clip dosyalarını oku, HTML sayfada göster

## Viewer (FastAPI Servisi)

`bridge/viewer/` mini servisi:

```python
@app.get("/v/{event_id}")
async def view_event(event_id: int, t: str):
    payload = verify_token(t)
    if payload["event_id"] != event_id:
        raise HTTPException(403)
    if payload["exp"] < utcnow().timestamp():
        raise HTTPException(410, "Link süresi doldu")

    event = await db.get_door_event(event_id)
    return templates.TemplateResponse("event.html", {
        "event": event,
        "snapshot_url": f"/media/{event.entry_snapshot_path}?t={t}",
        "clip_url": f"/media/{event.clip_path}?t={t}" if event.clip_path else None,
    })

@app.get("/media/{path:path}")
async def get_media(path: str, t: str):
    verify_token(t)
    return FileResponse(MEDIA_ROOT / path)
```

## Hizmete Açma

Viewer port 8080'de çalışır. Production'da reverse proxy (Nginx + Let's Encrypt) arkasına alınır.

```yaml
# docker-compose.yml içinde
viewer:
  build: ./bridge
  command: uvicorn viewer.main:app --host 0.0.0.0 --port 8080
  ports:
    - "8080:8080"
  volumes:
    - /var/lib/ainvr/media:/media:ro
  environment:
    - VIEW_TOKEN_SECRET=${VIEW_TOKEN_SECRET}
    - DATABASE_URL=${DATABASE_URL}
```

Reverse proxy:

```nginx
server {
    listen 443 ssl http2;
    server_name ainvr.example.com;
    ssl_certificate /etc/letsencrypt/live/ainvr/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ainvr/privkey.pem;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

## E-posta Gönderim Politikası

| Olay tipi | E-posta? | Alıcı |
|---|---|---|
| `door.traversal` | ✅ Evet | `SMTP_TO_DEFAULT` |
| `room.first_entry` (mesai dışı) | ✅ Evet | `SMTP_TO_DEFAULT` |
| `room.first_entry` (mesai içi) | ❌ Sessiz log | – |
| `room.unauthorized` | ✅ Evet | Yöneticiler |
| `truck.entered` | Opsiyonel | Lojistik ekip |
| `anomaly` | ✅ Evet | Güvenlik |

Alıcılar zone konfigürasyonunda override edilebilir:

```yaml
zones:
  - name: door_ana_giris
    rules:
      type: door
      email_notification: true
      email_to: ["guvenlik@example.com", "mudur@example.com"]
```

## Rate Limit (Spam Engelleme)

| Senaryo | Önlem |
|---|---|
| Bir kapıdan 100 kişi peşpeşe geçer | Per-zone rate limit: 30 e-posta/saat max |
| Frigate yanlış tetikledi 50 kez | `cooldown_seconds` ile filtrelenir |
| SMTP başarısız | DB'de `email_sent=false`, 5 dk'da bir retry, 6 deneme sonrası dead-letter |

## Sorun Giderme

### "E-posta gelmiyor"

```bash
docker exec ainvr-bridge python -m bridge.mailer test-email
```

Olası nedenler:
- SMTP authentication (Gmail App Password lazım)
- 587 portu kapalı (firewall)
- DNS / SPF / DKIM (kurumsal SMTP)

### "Link açılmıyor, 410"

Token süresi dolmuş. `VIEW_TOKEN_TTL_DAYS` değerini arttır veya event'i yeniden gönder.

### "Link 404"

Snapshot dosyası silinmiş olabilir (cleanup job). Retention süresini gözden geçir.

## Güvenlik Notları

- View token'lar **link bilen herkes erişebilir** (capability URL). E-posta'yı paylaşma.
- Daha sıkı yetki gerekirse: SSO / OIDC entegrasyonu (M8+)
- Snapshot dosyaları KVKK kapsamında kişisel veri sayılabilir. Retention politikası net olmalı.
