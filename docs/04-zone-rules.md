# 04 — Alan Kuralları ve State Machine

Bu sistemin en kritik mantığı: **gereksiz alarm üretme, ama gerçek olayı kaçırma.**

## Müşteri Kuralları (özet)

### Oda (alan) kuralları

1. 100 kameradan **10 oda alanı** AI ile aktif izlenir (Production). PoC'de 1–2 pilot oda.
2. Bazı alanlarda: alan içinde **biri varken uyarı verme.**
3. Alan **boşken, ilk gelen kişi** kayda alınır ve alarm üretir.
4. İzleme süresi **1 dakika veya üstüne** çıkabilir (kişi alanda kaldığı sürece).
5. Kişi ayrılıp tekrar girince → yeni "ilk giriş" sayılır.

### Kapı kuralları (oda dışında, giriş noktaları)

1. Kapı kameraları (yaklaşık 5 adet) her geçişte alarm üretir.
2. **Saniye hassasiyetinde** giriş ve çıkış zamanları kaydedilir.
3. Geçiş yönü tahmin edilir (giren / çıkan).
4. Olay **DMSS mobil push** ile bildirilir (Dahua external alarm üzerinden — M6.5 gerçek mekanizma). _E-posta/canlı-link/klip alanları `door_events` şemasında **rezerve** ama **kapsam dışı** (bkz. [`09-notifications.md`](09-notifications.md), karar 2026-05-31)._
5. Oda kuralından farklı olarak: kapı olayı **her geçişte** alarm üretir, "ilk giriş" mantığı uygulanmaz.

## State Machine Tanımı

Her alan üç durumdan birinde olur:

```
                  ┌──────────────────────────────────┐
                  │                                  │
                  ▼                                  │
            ┌──────────┐                       ┌─────┴──────┐
            │  EMPTY   │   person detected     │  OCCUPIED  │
            │          │ ────────────────────► │            │
            │          │                       │            │
            └──────────┘                       └─────┬──────┘
                  ▲                                  │
                  │  no person for                   │
                  │  EXIT_TIMEOUT (60s)              │
                  └──────────────────────────────────┘
```

Ek olarak bir geçici durum: `EXIT_PENDING`

- Frigate bir kareye kadar kişi göstermeyince hemen `EMPTY` denmez.
- 60 sn boyunca kişi görülmezse → `EXIT_PENDING` → `EMPTY`.
- Bu, kişinin kameranın kör noktasına geçmesinden kaynaklı yanlış-pozitif çıkışları engeller.

## Olay (Event) Tipleri

### Oda olayları

| Olay | Tetikleyici | Kaydedilir mi? | Alarm üretir mi? |
|---|---|---|---|
| `room.first_entry` | EMPTY → OCCUPIED | ✅ Evet | ✅ Evet (Dahua) |
| `room.still_present` | OCCUPIED durumda 60 sn'de bir | ✅ Evet (heartbeat) | ❌ Hayır |
| `room.exit` | OCCUPIED → EMPTY | ✅ Evet | ❌ Hayır (opsiyonel) |
| `room.unauthorized` | OCCUPIED ama yetki yok* | ✅ Evet | ✅ Evet |

*Yetki kontrolü ileriki milestone'da, ilk fazda devre dışı.

### Kapı olayları

| Olay | Tetikleyici | Kaydedilir mi? | Alarm (DMSS push)? |
|---|---|---|---|
| `door.entry` | Kişi kapı zone'una girdi | ✅ Saniye hassasiyetinde | ✅ Evet |
| `door.exit` | Kişi kapı zone'undan ayrıldı | ✅ Saniye hassasiyetinde | ✅ Evet (aynı olayla birleşik) |
| `door.traversal` | Tam geçiş (entry + exit eşleşmiş) | ✅ Birleşik kayıt | ✅ Evet |

`door.traversal` olayı = `entry_ts` + `exit_ts` + `duration_ms` + `direction (in|out|unknown)`.

## Konfigürasyon Şeması

`bridge/config/zones.yaml`:

```yaml
zones:
  - name: zone_depo_1
    camera: cam_01
    frigate_zone: zone_depo
    rules:
      enabled: true
      first_entry_alarm: true
      exit_alarm: false
      exit_timeout_seconds: 60
      min_person_score: 0.6
      # Bir nevi mesai saati filtresi
      active_hours: "00:00-23:59"   # 7/24
      # Bu alanda kimse yokken alarm üret
      alert_on_empty_arrival: true

  - name: zone_yukleme
    camera: cam_02
    frigate_zone: zone_loading
    rules:
      enabled: true
      first_entry_alarm: true
      exit_timeout_seconds: 120     # Yükleme alanı daha uzun
      min_person_score: 0.6
      active_hours: "18:00-08:00"   # Sadece mesai dışı alarm

  - name: zone_kamyon_giris
    camera: cam_giris
    frigate_zone: arac_giris
    rules:
      enabled: true
      track_objects: [truck, car]
      first_entry_alarm: true
      # NOT: tır renk analizi bir zone kuralı DEĞİL — Frigate 'truck' etiketi
      # otomatik olarak trucks.py → Ollama akışını tetikler (zone'dan bağımsız;
      # eşik = LLM_TRUCK_MIN_SCORE). 'truck_color_analysis' alanı şemada YOK
      # (ZoneRules extra='forbid' → böyle bir anahtar config'i reddeder).

  # Kapı: oda mantığından farklı, her geçişte alarm
  - name: door_ana_giris
    camera: cam_kapi_01
    frigate_zone: kapi_alani
    rules:
      type: door                    # "room" yerine "door"
      enabled: true
      track_objects: [person]
      log_precision: second         # ms hassasiyet
      direction_detection: true     # giriş/çıkış yönü (alternating in/out)
      email_notification: false     # KAPSAM DIŞI (şemada rezerve) — bildirim DMSS push ile
      include_short_clip: false     # KAPSAM DIŞI (rezerve) — klip üretimi implemente değil
      cooldown_seconds: 3           # aynı kişi 3 sn içinde yeniden tetiklemez
      active_hours: "00:00-23:59"

  - name: door_arka
    camera: cam_kapi_02
    frigate_zone: arka_kapi
    rules:
      type: door
      enabled: true
      track_objects: [person]
      log_precision: second
      direction_detection: true
      email_notification: false     # DMSS push (yukarı); e-posta kapsam dışı
      cooldown_seconds: 3
      active_hours: "00:00-23:59"
```

## Bridge State Tutma

State **bellekte** tutulur (Python dict), ama her durum değişikliği DB'ye yazılır. Servis restart olunca son durum DB'den geri yüklenir.

```python
# Pseudocode
class ZoneStateMachine:
    def __init__(self, zone_config, db, llm, dahua):
        self.cfg = zone_config
        self.state = "EMPTY"
        self.since = utcnow()
        self.last_seen = None
        self.db = db
        self.llm = llm
        self.dahua = dahua

    async def on_person_event(self, event):
        if event.score < self.cfg.min_person_score:
            return

        now = utcnow()
        if self.state == "EMPTY":
            await self._handle_first_entry(event, now)
        else:
            self.last_seen = now  # heartbeat

    async def _handle_first_entry(self, event, now):
        self.state = "OCCUPIED"
        self.since = now
        self.last_seen = now

        snapshot = await fetch_snapshot(event.camera, event.frigate_event_id)
        await self.db.insert_zone_event(
            zone=self.cfg.name,
            event_type="first_entry",
            ts=now,
            snapshot_path=snapshot,
            metadata={"score": event.score, "frigate_id": event.frigate_event_id},
        )
        if self.cfg.first_entry_alarm and self._is_active_hour(now):
            await self.dahua.trigger_external_alarm(self.cfg.camera, "person_entered")

    async def tick(self):
        """Her 10 saniyede bir çağırılır."""
        if self.state != "OCCUPIED":
            return
        if (utcnow() - self.last_seen).total_seconds() > self.cfg.exit_timeout_seconds:
            self.state = "EMPTY"
            await self.db.insert_zone_event(
                zone=self.cfg.name,
                event_type="exit",
                ts=utcnow(),
            )
```

## Race Condition Tehlikeleri ve Çözüm

| Tehlike | Çözüm |
|---|---|
| Frigate aynı kişi için 100 event basar | `frigate_event_id` ile dedupe |
| Kişi 5 sn kameradan kayboldu, geri geldi | `exit_timeout` (60 sn) tampon olur |
| İki bridge instance | Tek instance kuralı, `Singleton` lock dosyası |
| Servis restart sırasında alan dolu | DB'den son state'i yükle |

## Yetki Kontrolü (M8'de eklenir)

İleride yüz tanıma eklendiğinde:

```yaml
zones:
  - name: zone_kasa
    rules:
      authorization_required: true
      authorized_persons: [muhasebe_1, muhasebe_2, mudur]
```

Yetkisiz kişi tespit edilirse `unauthorized` event ve özel alarm.

## Kapı Olayı State Machine

Oda state machine'inden ayrı, paralel çalışır.

```
                  ┌────────────────────────────────────┐
                  │                                    │
                  │     Frigate kişi takibi başlar     │
                  │     (tracking_id var)              │
                  ▼                                    │
            ┌──────────┐                               │
            │  IN_ZONE │                               │
            │ entry_ts │                               │
            └────┬─────┘                               │
                 │                                     │
                 │  Frigate kişiyi kapı zone'undan     │
                 │  çıkış olarak işaretler             │
                 ▼                                     │
          ┌─────────────┐                              │
          │ TRAVERSED   │                              │
          │ exit_ts var │ ── Dahua alarm + DB ───────►│
          └─────────────┘
```

Pseudocode:

```python
# Gerçek implementasyon: bridge/doors.py — DoorStateMachine.
# Model: "alternating in/out" — açık oturum yoksa geçiş GİRİŞ (entry_ts),
# varsa ÇIKIŞ (exit_ts + duration_ms). Bildirim = Dahua external alarm → DMSS push.
class DoorStateMachine:
    def __init__(self, cfg, db, snapshots, clock=utcnow, dahua=None):
        self._cfg = cfg
        self._db = db
        self._snapshots = snapshots
        self._clock = clock
        self._dahua = dahua
        self._open_event_id = None       # None → sıradaki geçiş "in"
        self._open_entry_ts = None
        self._processed_ids = set()      # heartbeat dedup (zone içi tekrar)
        self._last_traversal_ts = None

    async def on_event(self, event):
        # Filtre: enabled, event.label ∈ track_objects, score ≥ min_person_score.
        # event.type == "end" → tracking bitti, _processed_ids'ten temizle
        #   (yoksa 7/24 bellek sızıntısı; aynı kişi tekrar girince yeni geçiş).
        # Zone içinde + tracking_id yeni + cooldown geçmiş → bir geçiş:
        await self._handle_traversal(event, self._clock())

    async def _handle_traversal(self, event, now):
        # Snapshot best-effort (kanıt) — None olsa da geçiş loglanır.
        snapshot = await self._snapshots.fetch_event_snapshot(event.event_id)
        if self._open_event_id is None:
            # GİRİŞ — yeni oturum aç
            event_id = await self._db.insert_door_event(
                zone=self._cfg.name, camera_id=event.camera, entry_ts=now,
                direction="in", tracking_id=event.event_id,
                entry_snapshot_path=snapshot,
            )
            self._open_event_id = event_id
            self._open_entry_ts = now
            await self._emit_dahua_alarm("door_entry")     # → DMSS push
        else:
            # ÇIKIŞ — açık oturumu kapat (duration_ms hesapla)
            duration_ms = int((now - self._open_entry_ts).total_seconds() * 1000)
            await self._db.close_door_event(
                self._open_event_id, exit_ts=now, duration_ms=duration_ms,
                exit_snapshot_path=snapshot,
            )
            self._open_event_id = None
            self._open_entry_ts = None
            await self._emit_dahua_alarm("door_exit")      # → DMSS push
```

DB şeması ek:

```sql
CREATE TABLE door_events (
  id BIGSERIAL PRIMARY KEY,
  zone TEXT NOT NULL,
  camera_id TEXT NOT NULL,
  entry_ts TIMESTAMPTZ(3) NOT NULL,    -- ms hassasiyet
  exit_ts  TIMESTAMPTZ(3),
  duration_ms INT,
  direction TEXT,                       -- 'in' | 'out' | 'unknown'
  entry_snapshot_path TEXT,
  exit_snapshot_path TEXT,
  clip_path TEXT,                       -- REZERVE / kullanılmıyor (klip üretimi kapsam dışı)
  email_sent BOOLEAN DEFAULT FALSE,     -- REZERVE / kullanılmıyor (e-posta kapsam dışı)
  view_token TEXT UNIQUE,               -- REZERVE / kullanılmıyor (HMAC izleme linki kapsam dışı)
  view_token_expires_at TIMESTAMPTZ     -- REZERVE / kullanılmıyor
);

CREATE INDEX ON door_events (zone, entry_ts DESC);
CREATE INDEX ON door_events (view_token);
```

Bildirim akışı = **Dahua external alarm → DMSS push** (gerçek mekanizma, M6.5). `email_sent`/`view_token`/`view_token_expires_at`/`clip_path` kolonları şemada **rezerve ama kullanılmıyor** — e-posta/viewer/HMAC-link **kapsam dışı** (karar 2026-05-31): bkz. [`09-notifications.md`](09-notifications.md).

## Test Senaryoları

### Oda senaryoları

| Test | Beklenen sonuç |
|---|---|
| Boş alana 1 kişi girer | 1 `room.first_entry`, 1 Dahua alarm |
| 30 sn boyunca alanda durur | Sadece `room.still_present` heartbeat, ek alarm yok |
| Alan içinde 2. kişi girer | Ek alarm yok (zaten OCCUPIED) |
| Tüm kişiler çıkar | 60 sn sonra `room.exit` event |
| Çıkıştan 30 sn sonra geri gelir | Yeni `first_entry` (ama state hala EMPTY değildi → fix: 60 sn'lik exit_timeout dolmadan tekrar geldi → state hala OCCUPIED, alarm yok) |
| Çıkıştan 90 sn sonra geri gelir | Yeni `room.first_entry` ve yeni alarm |

### Kapı senaryoları

| Test | Beklenen sonuç |
|---|---|
| Kişi kapıdan içeri geçer | 1 `door.traversal` (`direction=in`), entry_ts + exit_ts ms, DMSS push |
| Kişi kapıda 2 sn durur, döner | 1 `door.traversal` (`direction=unknown`), kısa duration |
| 2 kişi arka arkaya geçer | 2 ayrı `door.traversal` (Frigate `tracking_id` ayırır) |
| Aynı kişi 1 saniye sonra tekrar geçer | Cooldown (3 sn) → tek olay, çift alarm yok |
| Kapı kameraları offline | Olay üretilmez, Frigate log alarmı düşer |

Son satırdaki ince noktayı doğru anlamak için: **alarm sadece EMPTY → OCCUPIED geçişinde üretilir.**
