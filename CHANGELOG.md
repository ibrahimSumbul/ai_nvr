# Changelog

Bu dosya tüm önemli değişiklikleri kayıt altına alır.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) tarzı.

## [v1.0-public] — 2026-06-24

**Public referans dondurma.** Repo'nun public yaşam döngüsünün son sürümü. Çekirdek pipeline (M0–M7) dev-stack'te uçtan uca çalışır; M8 adli-davranış-zekası **tasarım kontratları** tamam (`docs/12` + Appendix A + `docs/15`–`16`), kod ⬜. Bundan sonrası gerçek bir kurumsal **lojistik/depo** ortamından sağlanan **gerçek saha görüntüleriyle değerlendirme** aşamasında ve **özel repoda** sürüyor (gizli görüntü → public repo dondu). Commit kimliği 3. geçmiş-yeniden-yazımıyla standartlaştırıldı (tek author/committer `96423728+ibrahimSumbul@users.noreply.github.com` + `Co-Authored-By`). Ayrıntı: [`ROADMAP.md`](ROADMAP.md) → "Public yaşam döngüsü: dondurma".

### Fixed / Changed

**Snapshot yaşam döngüsü sağlamlaştırma**
- `bridge/trucks.py` — **snapshot-gated dedup**: Frigate snapshot'ı bir tracking session'ın ilk truck event'inde hazır değilse (`has_snapshot=false` veya fetch None) olay artık dedup'a (`_processed`) eklenmez → sonraki event'te (snapshot hazır olunca) tekrar denenir. Önceki sırada (önce dedup, sonra snapshot) ilk event snapshot'sız gelirse tır **kalıcı kayboluyordu**. Dedup yalnız snapshot başarısından sonra konur (analiz tam bir kez).
- `bridge/zones.py` + `bridge/doors.py` — best-effort snapshot gözlemlenebilirliği: snapshot None olsa da olay yine yazılır (kanıt opsiyonel), ama `metadata.snapshot_available=false` + uyarı/debug log ile görünür kılınır.
- `docs/06-llm-strategy.md` — "Snapshot Seçimi ve Yaşam Döngüsü" bölümü: tek best-frame seçimi, `?height=480`, **kritik (trucks) vs best-effort (zones/doors)** politikası, snapshot-gated dedup gerekçesi.
- 5 yeni/güncellenmiş unit test (snapshot None → dedup'a eklenmez, has_snapshot=false → fetch yok, snapshot-not-ready → retry → işlenir).
- `bridge/alembic/versions/0002_truck_dedup_index.py` + `db/schema.sql` — `truck_events ((metadata->>'frigate_event_id'))` expression index. Dedup sorgusu (`truck_event_exists`) snapshot-pending window'da her event'te çalışabildiğinden seq scan'i önler (kod review). Migration 0001→0002 canlı uygulandı.

### Added

**M8 — QR giriş-kimliği tasarım ekleri** (PR #35) — _tasarım/doküman; kod YOK_
- `docs/15-adaptive-capture.md` — ortam-duyarlı (kapalı-döngü) görüntü yakalama: göreve-özel QR-okunabilirlik optimizasyonu. Tüm ayar kararları (shutter/gain/IR/profil) **ÖLÇÜLEN** deterministik sinyaller üzerinde (decode başarı oranı geri-besleme); VLM döngüde **yok**. Grounding kontratına (ölçülen≠çıkarsanan) bağlanış + "AE foton yaratamaz" fizik sınırı + QR veri kararı (kısa opak token `F0100…`, anlam sunucu-tarafı değişebilir eşlemede lookup).
- `docs/16-qr-entrance-camera.md` — QR giriş kamerası boyutlandırma & lens analizi: FOV = D·sensör_w/f, lens × mesafe × min QR-placard tablosu, motion-blur/shutter, DoF/ışık takasları, F0100 placard + e-İrsaliye 4-yönlü uzlaştırma (QR-token / fiziksel-tır / e-İrsaliye / kamera). M8.1 grounded rapor tasarımına bağlı.

**M3 — VLM doğruluk eval harness** (PR #32)
- `bridge/bridge/eval.py` — `analyze_truck` (qwen2.5vl) çıkarımını etiketli gold sete karşı **doğruluk** olarak ölçer (`bridge/tests/test_llm.py` yalnız Pydantic şema/parse'ı doğrular: geçerli JSON → tipli alan, geçersiz renk → `ValidationError`, unicode → ASCII; ama çıkarımın *doğru* olduğunu değil). Saf scorer'lar: per-alan exact-match accuracy (çekici/dorse renk, dorse tipi, yön; cevapsız tahmin = yanlış), presence P/R/F1 + confusion (tır/dorse var-mı), renk confusion matrix, çekici renk Cohen κ (şans-düzeltmeli uyum), güven kalibrasyonu ECE (güven bantlarına göre kovalanan doğruluk), latency. `perf.py`'nin `Stat`/`CheckResult`/`Verdict` iskeletini reuse eder; çıktı CSV (görüntü başına audit — gold vs tahmin) + JSON özet + stdout tablo + exit 0/1.
- İki çalışma modu: **replay** (Ollama'sız — CI/regresyon; kayıtlı ham yanıtı üretimdeki `model_validate_json` unicode-normalize yolundan birebir geçirir) + **canlı** (host'ta, gerçek etiketli görüntülerle asıl ölçüm, perf.py gibi). `Makefile` `eval` hedefi (`make eval ARGS="..."`).
- `bridge/tests/fixtures/eval/sample_gold.jsonl` — 10 sentetik, gizlilik-güvenli vaka (doğru/yanlış/unicode/bozuk-yanıt/geçersiz-renk). `bridge/tests/test_eval.py` — **25 unit test** (elle-hesaplı metrik assert'leri + uçtan-uca fixture replay + enjekte-fake-client live) → toplam **167** (eval öncesi gerçek baz 142 + 25; README rozeti 140→167'ye güncellendi — eski rozet 2 geriydi). `eval/README.md` protokol + gold format + provizyonel eşikler + gizlilik notu (gerçek kameralar **commit'lenmez**).
- **Eşikler PROVİZYONEL** (çekici renk ≥%80 / dorse-var F1 ≥0.80 / ECE ≤0.15 / κ ≥0.50) — ilk canlı baseline kalibre eder (perf.py'nin "1h baseline → kriter kalibrasyonu" yolunun aynısı). Subagent review (matematik-doğruluk + entegrasyon) → 2 fix: ECE paydası = total değil **kovalanan-nokta** (+ regresyon testi); `_write_outputs` `mkdir(parents=True)`.

**M3 — İlk canlı VLM doğruluk baseline (`cam_tir`)** (PR #33)
- `eval/runs/cam_tir-20260615/` — ilk **canlı** doğruluk koşumu (qwen2.5vl:7b, host Ollama, üretimdeki `analyze_truck` prompt + parse yolu). Sonuç (N=7, tek baskın-tır kare): çekici renk doğruluğu **%85.7 (6/7)** / Cohen κ **0.82** ✓; tır/dorse presence F1 **1.00** ✓; ama **dorse tipi 0/7** (model tamamen `bilinmeyen` döndürür — yanlış değil, **çekimser**), **dorse renk %16.7** ("gri" default bias'ı), **ECE 0.257** (aşırı-güvenli) ✗ → harness bunları gate'ler, koşum **kasıtlı geçemez** (exit 1). Yalnız türetilmiş metrikler commit'lendi (`eval.json` / `eval.csv` / `gold.jsonl` / `FINDINGS.md`); **gerçek kareler commit'lenmez** (telif/KVKK).
- `FINDINGS.md` dürüst çerçeve ("ölçülen ≠ abartılan" projenin kendine uygulandı): N=7 + tek video kaynağı + tek (AI-destekli) annotator + tam-kare girdi (üretimdeki bbox-crop'tan zor) → sayılar muhtemelen **alt sınır**. Eval'in işaret ettiği iş: dorse_tipi 0/7 kök-neden (prompt vurgusu mu, bbox-crop mu), eşik kalibrasyonu (ECE 0.15 bu modelde gerçekçi değil), daha büyük çok-kaynaklı 2-annotatör gold set.

**M5 — Test 1 altyapı baseline (1h soak)** (PR #28)
- `perf/runs/test1/` — ilk 1 saatlik kesintisiz soak (`1h-20260611`, 111 örnek): detector p95 **41 ms** ✓ (cpu1+cpu2 dengeli), Frigate CPU ~622% (1 saat stabil), RAM sızıntısı yok. cpu2 ikinci detector + `scripts/test1-{prepare,run}.sh` + `Makefile` hedefleri.
- `FINDINGS.md` — **katmanlı dürüst başarı kriterleri** (Katman A ham harness / B operasyonel alt küme / C sunum iddiaları) + R1–R6 tepki planı. Harness 3 kriterden 2'sini "fail" eder ama analiz nedenini ayırır: bridge RAM check = restart-baz false-positive (gerçek 131 MB ihmal edilebilir); skip = sentetik motion-heavy test loop artefaktı (operasyonel cam_kapi %0.4 / cam_tir %1.3 mükemmel). Metodoloji dersi (R1): uzun soak Terminal.app + `caffeinate -dimsu` ister.
- `bridge/bridge/llm.py` — `fix(M3)`: Ollama Türkçe unicode renk çıktısı (`sarı`→`sari`) ASCII literal normalize (field_validator) + test. Literal validation patlayıp event'leri `truck.llm_failed`'e düşürüyordu.
- Yeni `docs/14-testing-and-production-readiness.md` — test merdiveni + perf soak metodolojisi + gerçek sahaya-çıkış checklist'i.

**M7 — Frigate-down alert (servis LWT)**
- `bridge/bridge/frigate_monitor.py` — `FrigateMonitor`: Frigate'in MQTT availability topic'i (`frigate/available`, retained + LWT, `online`/`offline`) dinlenir. `offline` (Frigate çöker → broker LWT yayınlar) → **bir kez** Dahua external alarm (`frigate_offline`) → DMSS; tek-uyarı + recovery (kamera offline deseni). Kapatılan boşluk: `CameraMonitor` Frigate down iken kameraları **kasıtlı** offline işaretlemez (Frigate down ≠ kamera down), dolayısıyla Frigate çökünce sistem şimdiye dek sessizdi.
- `bridge/bridge/mqtt.py` — `listen()` çoklu-topic abonelik (tek bağlantı/identifier üzerinden `frigate/events` + `frigate/available`); `main.py` `_listen_loop` topic'e göre yönlendirir (`message.topic.matches`).
- `bridge/alembic/versions/0004_service_status.py` + `db/schema.sql` + `db.py` — `service_status` tablosu (servis başına satır, restart-safe `offline_alert_sent`) + `get/mark_service_online/offline`.
- `grafana/dashboards/ainvr-overview.json` — "Frigate Servisi" stat paneli (ÇEVRİMİÇİ/ÇEVRİMDIŞI value-mapping, panel 14).
- `config.py` + `.env.example` — `frigate_monitor_enabled` switch. **10 unit test** (online/offline/tek-uyarı/recovery/realarm/channel/alarm-hatası/no-dahua/case-whitespace/bilinmeyen-payload/last_change_at-transition), toplam 140.
- Adversarial review (3 boyut × doğrulama) → 3 nit giderildi: `last_change_at` yalnız gerçek durum geçişinde güncellenir (retained redelivery / reconnect'te kaymaz, DB `CASE WHEN`); Grafana paneli `noValue` ("BİLİNMİYOR") ile ilk mesaj öncesi "No data" yerine anlamlı gösterir.

**M7 — Disk doluluk alarmı + snapshot retention**
- `bridge/bridge/disk.py` — `DiskMonitor`: enterprise model (baskı-altı "dolunca en eskiyi sil" FIFO **değil**). (1) **Zaman-tabanlı budama** — bridge snapshot store'da `snapshot_retention_days`'ten (default 90g) eski dosyalar `snapshot_prune_interval_s` (default saatlik) periyodunda silinir → disk bizden hiç dolmaz; (2) **Doluluk eşiği** — `shutil.disk_usage` ile snapshot dizininin fs'i izlenir, `disk_warn_threshold_pct` (default %85) aşılınca **bir kez** Dahua external alarm (`disk_full`) → DMSS; histerezis (`disk_recover_margin_pct`) ile eşik etrafında flapping önlenir, doluluk (eşik−margin) altına düşünce flag resetlenir (kamera offline ile aynı tek-uyarı/recovery deseni).
- `bridge/alembic/versions/0003_disk_status.py` + `db/schema.sql` — `disk_status` tablosu (mount başına tek satır, restart-safe `alert_sent`).
- `bridge/bridge/db.py` — `get_disk_status` / `upsert_disk_status` (alert_sent çakışmada korunur) / `set_disk_alert_sent`.
- `bridge/bridge/main.py` — `_disk_monitor_loop` worker (`disk_monitor_enabled` switch); `bridge/snapshots.py` — `SnapshotStore.base_dir` property (tek doğruluk kaynağı).
- `grafana/dashboards/ainvr-overview.json` — "Disk Doluluk (%)" (eşik renkli) + "Snapshot Disk" + "Disk Durumu" panelleri (panel 11-13).
- Doluluk yüzdesi **`df Use%` ile aynı tabanda** (`used/(used+free)`, fiziksel `total` değil) — ext4 %5 root-rezerve bloğu nedeniyle operatörün df/Grafana'da gördüğü değerle tutarlı (review bulgusu).
- Blocking fs ops (`os.walk` budama + boyut, `shutil.disk_usage`) `asyncio.to_thread` ile event loop dışında; `usage_fn` enjekte edilebilir → **17 unit test** (eşik/tam-sınır/histerezis/recovery/margin-override/byte-arg-sırası/alarm-hatası/budama/throttle/eksik-dizin/boş-dizin-temizleme/gerçek-disk_usage-fallback), toplam 130. Snapshot budama boşalan tarih dizinlerini de kaldırır (boş dizin/inode birikmez). Adversarial review (4 boyut × doğrulama) → 5 bulgu giderildi.
- Ham video FIFO **kapsam dışı**: kayıt Dahua NVR'da (`frigate record.enabled=false`), NVR ring-buffer'ı native yönetir. Docs: `docs/08-operations.md > Disk Doluluk + Snapshot Retention`, `.env.example`, ROADMAP M7.

**M5 — Performans test harness**
- `bridge/bridge/perf.py` — stack ayaktayken Frigate `/api/stats` + `docker stats` periyodik örnekler; M5 kriterlerine göre pass/fail: **RAM stabil** (container bellek büyümesi ≤%20), **CPU başı boş** (detector p95 inference ≤200ms → aşımı Coral USB sinyali), **kaçan olay <%5** (kamera skipped/decode ≤%5). Çıktı: CSV (long-format zaman serisi) + JSON (özet) + stdout tablo + exit code (CI/cron uyumlu). Eşikler CLI ile override.
- `Makefile` `perf` hedefi (`make perf ARGS="..."`); default Frigate URL `localhost:5100` (compose `5100:5000` — host 5000 macOS AirPlay'de çakışır).
- **Kod review sertleştirmeleri**: (1) büyüme metriği ilk/son-pencere-ort yerine **doğrusal regresyon eğimi** — lineer bellek sızıntısını tam yakalar (eski hali eşiğin altında "stabil" gösterebiliyordu); (2) eksik veri (Frigate `/api/stats` veya docker erişilemedi) → ilgili check **"veri yok" ile başarısız**, yanıltıcı GEÇTİ/exit 0 yok.
- Saf parse/özet/değerlendirme fonksiyonları IO'dan ayrıldı; **28 unit test** (enjekte-deps IO döngüsü dahil — canlı stack gerekmez), toplam 113. Dokümantasyon: `docs/08-operations.md > Performans Testi (M5)`.

**M3 — Truck gerçek E2E + Frigate truck detection fix**
- `frigate/config.yml`:
  - **`model.labelmap: 7: truck`** override — Frigate default SSD MobileNet modeli COCO label 7'yi (truck) varsayılan olarak "car"a remap ediyordu (tüm büyük araçlar "car"). Override ile truck/car ayrımı geri kazanıldı. **Production değeri** (YOLO upgrade gerekmedi — model truck'ı zaten algılıyordu).
  - `cam_tir` test kamerası — YouTube tır videosu (MediaMTX cam_tir.mp4) ile gerçek truck E2E fixture. cam_tir zone'suz iken detection başlamadı, zone ekleyince çalıştı (ampirik bulgu; kesin neden — zone mu motion baseline mı — doğrulanmadı). Config yorumunda reproduce talimatı.
- Doğrulama: gerçek video → Frigate truck detect → bridge → Ollama → **4 `truck_events`** (beyaz çekici, gri/metalik dorse — videodaki tırlarla uyumlu), 5 `llm_usage` (~46s ort).

**M7 — Operasyon Runbook**
- `docs/08-operations.md` gerçek stack'e göre yeniden yazıldı: servis tablosu (5 container + host Ollama), rutin (günlük/haftalık/aylık), Grafana panel açıklamaları, **DMSS bildirim** (e-posta/Telegram/LLM-bütçe alarmı kaldırıldı), kamera offline gerçek davranışı (CameraMonitor HTTP-poll), backup (Postgres pg_dump + named volume arşivleme + snapshot retention), restart & recovery (migrate zorunluluğu + zone/door/camera state), sorun giderme (Colima/Ollama/Dahua/Postgres + var-olmayan CLI'ler kaldırıldı). Kod değişmedi.

**M7 — Kamera Offline Alarm + Grafana Paneli**
- `bridge/cameras.py` — `CameraMonitor` offline tespitinde **Dahua external alarm** (`camera_offline` event → DMSS push, best-effort). Kamera→NVR channel `camera_channels` map'i ile (zones.yaml `dahua_channel`'dan türetilir); yoksa global `dahua_alarm_channel`. `_emit_offline_alarm` tek-uyarı (offline_alert_sent ile).
- `bridge/main.py` — `camera_channels` map (zones_cfg'den) + `CameraMonitor`'a `dahua` + map enjekte.
- `grafana/dashboards/ainvr-overview.json` — 2 yeni panel: "Çevrimdışı Kamera" stat (background renkli) + "Kamera Durumu" tablosu (camera_id/online/son görülme/uyarıldı).
- 3 yeni unit test (offline→alarm camera channel, default channel fallback, alarm-failure best-effort). Canlı: 10 panel render, 5 kamera online.

**M7 — Kamera Offline Tespit (kısmi)**
- `bridge/cameras.py` — `CameraMonitor`: Frigate `/api/stats` HTTP poll, her kameranın `camera_fps`'ini izler. `camera_fps>0` → online (`last_seen_at` güncelle); `camera_offline_threshold_s` (60s) frame yoksa offline + tek uyarı (`offline_alert_sent`); recovery'de tekrar online. `cameras` wrapper (0.14+) + top-level (eski) ikisini destekler; Frigate erişilemezse kameraları offline işaretlemez (Frigate down ≠ kamera down).
- `bridge/db.py` — `get_camera_status` + `mark_camera_online` (upsert) + `mark_camera_offline` (`camera_status` tablosu, M1'de hazır)
- `bridge/main.py` — `_camera_monitor_loop` periyodik task (`camera_check_interval_s`, default 30s)
- `bridge/config.py` — `camera_check_interval_s`, `camera_offline_threshold_s`
- 8 yeni unit test (`test_cameras.py`: online/offline-threshold/before-threshold/once/recovery/no-baseline/Frigate-down/top-level-fallback) + gerçek-Frigate+Postgres E2E (5 kamera online)
- Not: offline → DMSS/Dahua alarm + Grafana paneli sonraki adım (kamera→NVR channel eşlemesi gerekir)

**M6.5 — Kapı Olayları (DMSS push)**
- `bridge/doors.py` — `DoorStateMachine`: kapı geçişi (traversal) detektörü. **Alternating yön** modeli (1. geçiş "in"/giriş → oturum açar, 2. geçiş "out"/çıkış → kapatır + `duration_ms`). ms hassasiyetli `entry_ts`/`exit_ts`. Heartbeat dedup (tracking_id) + `cooldown_seconds` debounce. Her geçişte Dahua external alarm → DMSS push (best-effort). ⚠️ Yön varsayımı genel geçer değil — kamera açısı/kuruluma göre değerlendirilmeli (kod docstring).
- `bridge/db.py` — `insert_door_event` (ms hassasiyetli entry, direction, tracking_id) + `close_door_event` (exit_ts + duration_ms hesabı)
- `bridge/main.py` — tip-bazlı state machine routing: `type=room` → `ZoneStateMachine`, `type=door` → `DoorStateMachine` (ortak `StateMachine` union)
- `bridge/config/zones.yaml` — `cam_kapi_zone` `type: door`'a alındı (cooldown + dahua_channel)
- 9 yeni unit test (`test_doors.py`: alternating in/out/in, heartbeat dedup, cooldown, not-in-zone, low-score, dahua none/failure) + gerçek-Postgres E2E doğrulaması

**Dokümantasyon — Ollama hizalama + DMSS push**
- `README.md` + `docs/03-setup.md`: "Claude Haiku/bulut $10-25/ay" → lokal Ollama ($0, gizlilik); badge M1→M4; **çalışır kurulum** (ollama pull + `alembic upgrade head` migrate adımı + servis adresleri)
- `docs/05-dahua-integration.md`: **DMSS mobil push konfigürasyon rehberi** (NVR external alarm→push kuralı + DMSS app abonelik adımları). Retry/test bölümleri gerçek M4 implementasyonuna hizalandı (`dahua_alarm_sent`/retry worker/claim guard; var olmayan `test-alarm` CLI kaldırıldı)
- `docs/03-setup.md` + `docs/09-notifications.md`: e-posta/SMTP/viewer kapsam-dışı (DMSS push tercih edildi; referans tasarım olarak korundu)
- `ROADMAP.md`: M6.5 "Kapı olayları + e-posta" → "Kapı olayları (DMSS push)"; karar kayıtları (Haiku→Ollama, e-posta/viewer kapsam dışı)

**M5 — Grafana Dashboard (kısmi)**
- `grafana/provisioning/datasources/postgres.yml` — AINVR Postgres datasource (otomatik, `$VAR` expansion ile credentials)
- `grafana/provisioning/dashboards/provider.yml` — dosya tabanlı dashboard provider
- `grafana/dashboards/ainvr-overview.json` — "AI NVR — Genel Bakış" dashboard: ilk giriş (24s) / kamyon / LLM başarı / Dahua bekleyen stat'ları, alan başına ilk giriş (saatlik bar), kamyon çekici rengi (donut), LLM gecikme (timeseries), son zone olayları (table)
- `docker-compose.yml` — grafana servisine provisioning + dashboards mount (RO) + Postgres env (datasource expansion)
- Doğrulama: datasource health `Database Connection OK`, dashboard provisioned, panel SQL'leri canlı veriyle çalışıyor

**M4 — Dahua Alarm Köprüsü**
- `bridge/dahua.py` — `DahuaClient` (Virtual Input CGI `/cgi-bin/alarm.cgi` + httpx DigestAuth):
  - `trigger_external_alarm(channel, event_type, description)` — inline retry + exponential backoff (2s/4s/8s)
  - `health_check()` — `magicBox.cgi getDeviceType` ile NVR yoklama
  - `DahuaAlarmClient` Protocol (provider-agnostic — onvif/dss_custom ileride), `DahuaAlarmError`
  - `build_dahua_client` factory — `DAHUA_ALARM_ENABLED=false` → None (dev'de push atlanır)
- `bridge/zones.py` — `ZoneStateMachine` Dahua entegrasyonu: `alarm_emitted` + client varsa external alarm tetiklenir; başarısızlıkta event DB'de pending kalır (`dahua_alarm_sent=false` + retry sayacı)
- `bridge/db.py` — `mark_dahua_alarm_sent`, `increment_dahua_retry`, `get_pending_dahua_alarms` (retry queue)
- `bridge/main.py` — `_dahua_retry_loop` worker: pending alarm'ları `DAHUA_RETRY_INTERVAL_S` periyodunda tekrar dener
- `bridge/zone_config.py` — `ZoneRules.dahua_channel` (zone→NVR channel eşlemesi)
- `bridge/config.py` — Dahua alarm ayarları (enabled, method, port, channel, timeout, max_retries, retry_interval)
- 13 yeni unit test (test_dahua.py: 9 — trigger/retry/fail/health/build; test_zones.py: 4 — alarm tetik/fail-retry/emitted-değil/none-client)

**M3 — LLM kalite tuning** (smoke test sonrası)
- Renk prompt fix: model rengi görse de "bilinmeyen" döndürüyordu → enum'a commit (siyah/gri doğru çıkıyor)
- Snapshot downscale: `llm_snapshot_max_height=480` + Frigate `?height=N` → latency %73↓ (800px 121s → 480px 33s)
- `num_predict` 512→256, `llm_timeout_s` 60→90

**M3 — LLM Entegrasyonu (Ollama)**
- `bridge/llm.py` — Provider-agnostic `LLMClient` Protocol + `OllamaClient` implementation:
  - `httpx.AsyncClient` ile `/api/generate` (Ollama vision endpoint)
  - `format=json` structured output, Pydantic schema parse
  - Retry (max_retries default 2) + timeout (default 60s)
  - `TruckAnalysis` Pydantic: Color enum (16 renk), TrailerType enum, Direction enum, guven (0.0-1.0)
  - `LLMResult` wrapper: parsed + raw + model + latency_ms + tokens + cost (Ollama'da 0)
  - `LLMError` exception — tüm retry'lar başarısız olunca yükselir
- `bridge/trucks.py` — `TruckEventHandler`:
  - Filter: `label == "truck"` + `score >= LLM_TRUCK_MIN_SCORE` (default 0.6)
  - Snapshot fetch (mevcut SnapshotStore)
  - LLM analyze → `llm_usage` + `truck_events` insert
  - Dedup: memory cache + DB sorgu (`truck_event_exists`)
  - LLM hata durumunda `llm_usage.success=false` + `error` yazılır, `truck_events` boş bırakılır
- `bridge/db.py` — `insert_llm_usage` + `insert_truck_event` + `truck_event_exists` fonksiyonları
- `bridge/config.py` — yeni LLM env vars:
  - `LLM_PROVIDER` (default `ollama`; `anthropic` hibrit fallback için kayıtlı)
  - `LLM_OLLAMA_URL` (default `http://host.docker.internal:11434` — mac host'taki native ollama)
  - `LLM_OLLAMA_MODEL` (default `qwen2.5vl:7b`, `.env` ile override)
  - `LLM_TIMEOUT_S` (60s), `LLM_MAX_RETRIES` (2), `LLM_TRUCK_MIN_SCORE` (0.6)
- `bridge/main.py` refactor: `build_llm_client` + `build_truck_handler` + `_listen_loop`'a truck handler bağlandı (zone'lara paralel akış)
- `.env.example` — LLM env değişkenleri eklendi, Anthropic ayrı tutuldu (hibrit gelecek)
- 14 yeni unit test:
  - `test_llm.py` (7): TruckAnalysis Pydantic parsing, invalid color/trailer_type/guven, extra field tolerance, JSON string parse
  - `test_trucks.py` (7): success path, non-truck label, low score, dedup (memory + DB), no_snapshot, LLM failure

**M3 prereq commit** (frigate/config.yml + docker-compose.yml):
- `frigate/config.yml`: `reset_admin_password: true → false` (admin parolası artık sabit, ilk login sonrası UI'dan değiştirilir)
- `docker-compose.yml`: bridge `INSTALL_LLM: "false"` olarak kaldı — M3 Ollama HTTP-only, anthropic SDK image'a girmiyor (httpx core'da)

**M2 — Tek kamera pilot**
- `bridge/events.py` — Pydantic `FrigateEvent` / `FrigateObject` (extra=allow ile Frigate sürüm toleransı)
- `bridge/zone_config.py` — `ZoneRules` / `ZoneConfig` / `ZonesConfig` Pydantic + YAML loader (room + door şeması, M6.5 için door alanları şimdiden tanımlı)
- `bridge/zones.py` — `ZoneStateMachine` (EMPTY/OCCUPIED + restore_from_db + active_hours overnight + clock injection). **DB insert HER ZAMAN, alarm tetikleme ayrı karar** (`first_entry_alarm AND active_hour AND alert_on_empty_arrival` → `alarm_emitted` metadata)
- `bridge/snapshots.py` — Frigate `/api/events/<id>/snapshot.jpg` async fetcher (httpx)
- `bridge/db.py` — `insert_zone_event` + `get_zone_last_event` eklendi
- `bridge/main.py` — listener refactor: FrigateEvent parse + cameras_to_zones routing + 10s tick loop + zone başına exception izolasyonu
- `bridge/config/zones.yaml` — pilot_zone tanımı
- `frigate/config.yml` — pilot_kamera (RTSP: `host.docker.internal:8554/cam_test`) + zone_pilot polygon
- `docker-compose.yml` — bridge image `0.2.0`, `./bridge/config:/app/config:ro` bind mount
- `bridge/pyproject.toml` — `pyyaml>=6.0.2` deps
- 28 yeni unit test (test_events.py: 6, test_zones.py: 22 — state transitions, dedup, exit timeout, active_hours, alarm/DB insert ayrımı, re-entry, restore non-first_entry)

**M1 — Docker iskelet**
- `docker-compose.yml` — Frigate, Postgres 16, Mosquitto 2, Grafana 11, Bridge servisi
- `bridge/` Python 3.13 servisi:
  - `bridge/config.py` — pydantic-settings ile env yönetimi
  - `bridge/db.py` — asyncpg connection pool + smoke test (SELECT 1)
  - `bridge/mqtt.py` — aiomqtt Frigate event listener, otomatik reconnect (exp. backoff)
  - `bridge/main.py` — asyncio entry, signal handling, structlog
- `bridge/Dockerfile` — Python 3.13-slim multistage, uv install, non-root user, healthcheck
- `bridge/pyproject.toml` — uv, PEP 735 dependency-groups, ruff + mypy + pytest
- `bridge/tests/` — pytest, unit + integration marker, config + smoke testleri
- `bridge/alembic.ini` + `bridge/alembic/` — migrasyon altyapısı (psycopg sync driver)
- `bridge/alembic/versions/0001_init.py` — baseline (5 tablo: zone_events, door_events, truck_events, llm_usage, camera_status)
- `db/schema.sql` — şema referansı
- `frigate/config.yml` — boş kamera şablonu (M2'de kameralar eklenir)
- `mosquitto/config/mosquitto.conf` — anonymous (M3'te authentication eklenecek)
- `Makefile` — up/down/logs/test/fmt/lint/migrate/build target'ları
- `.env.example` — tüm env değişkenleri, PoC default'ları
- `.github/workflows/ci.yml` — uv setup, ruff lint+format, mypy, pytest, docker build

**M0 — Dokümantasyon**
- Proje dokümantasyon iskeleti (`docs/01..11`)
- `README.md` proje genel bakış
- `ROADMAP.md` PoC → Production milestone planı
- `.gitignore` (Python, uv, Docker, IDE)
- **Kapı olayları (`door.traversal`)** — saniye hassasiyetinde giriş/çıkış logu
- **E-posta bildirim + viewer servisi** — imzalı link ile snapshot + klip izleme
- **Milestone 6.5** — kapı olayları + e-posta bildirimi
- `docs/09-notifications.md`
- `docs/10-why-frigate.md` — saf Haiku neden yapılmaz teknik gerekçeler
- `docs/11-tech-decisions.md` — teknoloji seçim kararları (Frigate, Python, Haiku, Postgres, n8n vs alternatifler)
- **MIT License** — portfolio için açık kaynak
- README portfolio-friendly açılış (badges + lead paragraph + cross-link to tech decisions)

### Changed

**M1 — Pre-build temizlik**
- README başlık ve lead paragrafı Türkçeleştirildi
- README badge `Documentation` → `M1 tamam`
- README durum tablosu güncellendi (11 doküman, M1 ✅, M2 sıradaki)
- README Hızlı Başlangıç bölümü artık çalışır komutlar içerir
- `docs/03-setup.md`: yanlış clone URL düzeltildi (`ibrahimsumbul/ibrahimsumbul.git` → `ibrahimSumbul/ai_nvr.git`)
- `docs/05-dahua-integration.md`: kopya "Sub-stream ayarı" bloğu silindi
- `docs/08-operations.md`: eski branch adı `main` ile değiştirildi, deploy path düzeltildi
- `ai_nvr_initial.zip` silindi

**M0 — Dokümantasyon revizyonu**
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

### Changed

**M2.5 — Sıkılaştırma (M3 öncesi pre-flight)**
- **Mosquitto auth**: `allow_anonymous false` + `password_file /tmp/passwd`. Container entrypoint env'den (`MQTT_USER`/`MQTT_PASSWORD`) runtime'da passwd üretir, host'a sızmaz. Anonymous istekler `Connection Refused: not authorised`. Healthcheck artık auth ile.
- **Frigate auth sıkılaştırma**: `frigate/config.yml`'e açık `auth: enabled + trusted_proxies: [] + reset_admin_password: true`. Docker network internal istekleri artık anonymous-admin olarak geçmiyor; manuel login zorunlu. Yeni admin parolası her restart'ta log'a basılır.
- **Frigate `/config` persist**: yeni `frigate-config` named volume `/config`'e mount edildi. User DB + JWT secret + history recreate'te kayboluyor değil. `config.yml` ayrı RO bind mount olarak host'tan editlenebilir.
- **mypy strict zorunlu**: `.github/workflows/ci.yml`'de `continue-on-error: true` kaldırıldı. CI'da type hatası artık build'i kırar.
- **`dependency-groups` ile milestone-bazlı install**: `bridge/pyproject.toml`'da `[project].dependencies` sadece core (asyncpg, aiomqtt, pydantic, httpx, structlog, alembic, psycopg, pyyaml). M3+ deps `[dependency-groups]` altında `llm = ["anthropic"]` ve `viewer = ["fastapi", "uvicorn[standard]"]` olarak ayrıldı. Dockerfile build arg `INSTALL_LLM`/`INSTALL_VIEWER` ile aktive (default false → core-only image).
- **`uv.lock` commit edildi**: `.gitignore`'tan `uv.lock` kaldırıldı, lock dosyası repo'ya alındı. CI `uv sync --frozen` ile lock'tan sapmayı engelliyor (reproducible build). Dockerfile da `--frozen` kullanıyor.

### Notes
- M1: Frigate UI dev port'u **5100** (`5100:5000`). macOS'te 5000'i AirPlay Receiver tutuyor; bu seçim **macOS dev için zorunlu**. Linux production'da reverse proxy (443) arkasında host portu önemsiz, gerekirse 5000'e dönülebilir.
- M1: Grafana provisioning boş; M5'te dashboard'lar provision edilecek.
- M2.5: Frigate `reset_admin_password: true` aktif — her restart'ta admin parolası yeniden üretilir (log'a basılır). M3'te kullanıcı admin pass'ını UI'dan değiştirip config'i `false`'a alabilir.
- M0: M1 ile birlikte çalışan kod artık mevcut.
