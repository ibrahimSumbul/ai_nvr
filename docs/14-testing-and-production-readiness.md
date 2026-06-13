# 14 — Test Stratejisi ve Üretime Hazırlık

Bu doküman projenin **"ne kadar gerçek?"** sorusunu dürüstçe yanıtlar: hangi katmanlar
kanıtlandı, hangileri planlı, ve gerçek bir Dahua NVR + canlı kameralarla **sahaya
çıkmadan önce** ne yapılması gerekiyor.

Hedef, bunu *herkesin klonlayıp kurabileceği, çalışan açık-kaynak bir referans sistem*
haline getirmek. Dolayısıyla bu sayfa hem portföy okuyucusu için "ne kanıtlandı"
karnesi, hem de kendi tesisinde kuracak biri için "neye dikkat et" rehberidir.

> **İlke — kanıtlanan ≠ varsayılan.** Projenin manşeti olan *ölçülen ≠ çıkarsanan*
> ([`12-forensic-behavioral-intelligence.md`](12-forensic-behavioral-intelligence.md))
> ayrımının test tarafındaki karşılığı budur. Her satır hangisi olduğunu açıkça taşır:
> dev-stack'te doğrulanan bir şey, gerçek sahada doğrulanmış sayılmaz.

---

## 1. Test merdiveni (kanıt katmanları)

Aşağıdan yukarı her basamak bir öncekini varsayar. Şu an **5. basamaktayız**; 6–7
gerçek donanım/saha gerektirir.

| # | Katman | Ne doğrular | Durum | Kanıt |
|---|--------|-------------|-------|-------|
| 1 | **Unit** (~140 test) | Saf mantık: state machine, dedup, retry, eşik, histerezis, parse | ✅ CI'da zorunlu | `bridge/tests/`, mypy strict + ruff |
| 2 | **Gerçek-bağımlılık E2E** | Canlı Postgres + Frigate ile insert/close/poll | ✅ manuel | M2/M6.5 gerçek-Postgres, M7 gerçek-Frigate `/api/stats` (5 kamera online) |
| 3 | **Gerçek video E2E** | YouTube tır videosu → Frigate detect → Ollama → `truck_events` | ✅ | 4 `truck_events` (PR #20) |
| 4 | **Perf soak — altyapı** | 6 RTSP @5fps yük altında RAM/CPU/detector/skip stabilitesi | 🟡 1h ✅ · 6h/24h planlı | [`perf/runs/test1/FINDINGS.md`](../perf/runs/test1/FINDINGS.md) |
| 5 | **Demo senaryosu** (doc13) | 5-kamera forensic akış (grounded rapor + handoff) | ⬜ M8.1 tasarım | [`13-portfolio-demo-vision.md`](13-portfolio-demo-vision.md) |
| 6 | **Gerçek saha pilotu** | Canlı Dahua NVR + gerçek kameralar | ⬜ | [§4 checklist](#4-gerçek-testlere-hazırlık-sahaya-çıkmadan-önce) |
| 7 | **Production olgunluk** | 1 hafta dokunmadan stabil, operatör güveni | ⬜ | M7 kabul kriteri |

**Dürüst sınır:** Bugüne kadar her şey **lokal Colima + MediaMTX sentetik RTSP
stream'lerinde** koştu. Gerçek bir Dahua NVR'a veya gerçek kameralara **henüz
dokunulmadı** — M4 Dahua alarm kodu `httpx` mock ile path-doğrulandı, canlı panel
doğrulaması (basamak 6) bekliyor.

---

## 2. Perf soak testleri (1h / 6h / 24h)

**Amaç:** Doc 13'ün senaryo yükü değil — saf **video/detector altyapısının** uzun
süre stabil kalıp kalmadığı. Harness: [`bridge/bridge/perf.py`](../bridge/bridge/perf.py)
(`make perf`), stack ayaktayken Frigate `/api/stats` + `docker stats` örnekler.

**Harness kriterleri (M5 default):**

| Check | Eşik | Aşımı ne demek |
|-------|------|----------------|
| RAM stabil | container bellek büyümesi ≤ %20 (lineer regresyon eğimi) | bellek sızıntısı |
| CPU başı boş | detector p95 inference ≤ 200 ms | Coral USB sinyali (M6) |
| Kaçan olay | kamera skip p95 ≤ %5 | decode/CPU darboğazı |

**1h baseline sonucu (`1h-20260611`, 111 örnek):** detector p95 **41 ms** ✓ (cpu1+cpu2
dengeli), Frigate CPU ~622% (1 saat stabil), RAM sızıntısı yok. Harness 3 kriterden
2'sini "fail" işaretler — ama [`FINDINGS.md`](../perf/runs/test1/FINDINGS.md) dürüst
analizle nedenini gösterir:

- **Bridge RAM check fail = false-positive** — `(son−ilk)/ilk` metriği restart sonrası
  düşük baza (39 MB) karşı +%210 üretiyor; gerçek bitiş 131 MB (Colima 8 GiB içinde
  ihmal edilebilir).
- **Skip fail = kamera içeriği artefaktı** — sentetik **motion-heavy** test loop'ları
  (cam_test %29, cam_depo %26) eşiği şişiriyor; **operasyonel kameralar mükemmel**
  (cam_kapi %0.4, cam_tir %1.3). Gerçek statik ofis/depo sahneleri bundan çok daha
  düşük skip yapar.

Bu yüzden FINDINGS **katmanlı kriter** kullanır: *Katman A* (ham harness), *Katman B*
(operasyonel alt küme — kapi/tir/magaza), *Katman C* (dürüst sunum iddiaları). Tek bir
GEÇTİ/KALDI yerine, neyin kanıtlandığını neyin kanıtlanmadığını ayırır.

**Metodoloji dersi (R1):** Uzun soak, ajan/arka-plan shell'de güvenilir değil (gece 6h
denemeleri 28–51 örnekte düştü). Doğru koşum: **Terminal.app + `caffeinate -dimsu`** +
30 dk ısınma. Protokol FINDINGS §2'de.

**Sıradaki soak adımları:**
1. **Run 2** — ısınmalı 1h, baseline ile karşılaştırma (FINDINGS §3 şablonu).
2. **6h gündüz** — Katman B operasyonel pass doğrulanırsa Terminal protokolüyle.
3. **24h** — production-temsili sürekli koşum (M5 kabul: kaçan olay <%5, RAM stabil).

---

## 3. doc13 demo tamamlandığında (M8.1+)

[`docs/13`](13-portfolio-demo-vision.md) 5-kameralı forensic demoyu somutlaştırır. O
hat (M8.1 grounded rapor → M8.2 handoff) **kodlanıp** demo videolarıyla doğrulandığında,
test merdiveninin 5. basamağı kapanır. O noktada eklenecek test katmanları:

- **Grounding doğruluğu** (`bridge/eval.py`, `make eval`) — rapor alanlarının
  ÖLÇÜLEN/TÜRETİLMİŞ/ÇIKARSANAN etiketleri doğru mu (hedef ≥%98).
- **Confabulation ≈ 0** — VLM, sahnede olmayan şeyi rapora yazmıyor (içerik-farkında audit).
- **Handoff precision/recall** — aynı varlık iki kamerada doğru eşleşiyor mu (≥0.90 / ≥0.80).
- **Token/olay eğrisi** — dismissal-learning loop ile çağrı başına maliyet düşüşü (≥%30).

Bunlar **demo videolarıyla** ölçülür; gerçek kamera gerektirmez. Demo geçtikten sonra
sıra **gerçek saha pilotuna** (basamak 6) gelir → §4.

---

## 4. Gerçek testlere hazırlık (sahaya çıkmadan önce)

doc13 demosu hazır olduktan sonra, gerçek bir tesiste (canlı Dahua NVR + gerçek
kameralar) pilota başlamadan önce tamamlanması gerekenler. Aynı liste, sistemi kendi
tesisine kuracak açık-kaynak kullanıcısı için de geçerli.

### 4.1 Donanım & ağ
- [ ] Gerçek kameralardan **direct RTSP sub-stream** erişimi — NVR'a yük bindirmeden
      (karar: NVR %50 yükte, üzerine pull yok; bkz. ROADMAP karar kaydı).
- [ ] AI sunucusu kameralarla aynı ağda ve kamera IP'lerine erişebiliyor.
- [ ] 8 GB+ RAM host, CPU detection yeterli; ölçek büyükse Coral USB değerlendir (M6).
- [ ] Disk: snapshot retention + ham-video FIFO ayrımı net (ham video NVR'ın işi).

### 4.2 Dahua NVR entegrasyonu (M4'ün gerçek doğrulaması — basamak 6)
- [ ] `.env`: `DAHUA_ALARM_ENABLED=true` + gerçek `DAHUA_NVR_*` kimlik bilgileri.
- [ ] External alarm → **DSS/SmartPSS panelinde görünüyor** (mobil push dahil) —
      ilk hafta API uyum testi ([`docs/05`](05-dahua-integration.md)).
- [ ] DMSS push kuralı NVR'da kuruldu; abonelik test edildi.
- [ ] Digest auth + port + `dahua_channel` eşlemesi gerçek NVR'da doğrulandı.
- [ ] Retry kuyruğu gerçek kesinti senaryosunda çalışıyor (NVR erişilemez → pending → recover).

### 4.3 Güvenlik & gizlilik (KVKK)
- [ ] `.env`: güçlü Postgres/MQTT/Grafana şifreleri (default yok).
- [ ] Frigate auth aktif, admin parolası ilk login'de değiştirildi.
- [ ] Görüntüler tesisten çıkmıyor doğrulandı (Ollama lokal, dış çağrı yok).
- [ ] Snapshot retention günü + disk doluluk eşiği tesise göre ayarlandı.
- [ ] Loglarda PII yok (plaka/yüz okunmuyor; tır akışı yalnız renk/tip).

### 4.4 Operasyonel olgunluk (M7)
- [ ] Grafana panelleri canlı veriyle render (10 panel).
- [ ] Kamera / Frigate-down / disk offline alarmları gerçek NVR channel'ına gidiyor.
- [ ] Backup kuruldu: Postgres `pg_dump` cron + named volume arşivleme ([`docs/08`](08-operations.md)).
- [ ] Restart recovery doğrulandı: `alembic upgrade head` + zone/door/camera state geri yükleniyor.
- [ ] **1 hafta dokunmadan stabil** (M7 kabul kriteri) — operatör gece aranmıyor.

### 4.5 Perf doğrulama (gerçek yük altında — basamak 4'ün saha tekrarı)
- [ ] Gerçek kameralarla soak: skip p95 < %5 (gerçek statik sahneler sentetikten düşük beklenir).
- [ ] Detector p95 < 200 ms; aşımı → Coral USB tetikle (M6).
- [ ] 24h sürekli koşum: RAM stabil, kaçan olay < %5, `camera.offline` yok.

---

## Özet

| Soru | Cevap |
|------|-------|
| Çalışıyor mu? | ✅ Dev-stack'te uçtan uca; ⬜ gerçek NVR'da değil. |
| Ölçülebilir kanıt var mı? | ✅ 1h baseline (p95 41 ms) + ~140 test; uzun soak + saha kaldı. |
| Manşet özellik (forensic) hazır mı? | 🔬 Tasarım + build kontratları ✅; kod ⬜ (M8.1). |
| Üretime ne kadar uzak? | doc13 demo → §4 saha checklist → pilot. Adımlar net, sırada. |

Detaylı milestone planı: [`ROADMAP.md`](../ROADMAP.md) · Operasyon: [`docs/08`](08-operations.md).
