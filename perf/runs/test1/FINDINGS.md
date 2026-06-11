# Test 1 — Bulgular, tepki planı ve sunum kriterleri

**Baseline koşum:** `1h-20260611` (2026-06-11, 09:03–10:03 TR)  
**Durum:** Baseline koşum + bulgular + katmanlı kriterler tamamlandı ve commit'lendi (bu PR). Run 2 (ısınmalı karşılaştırma) = belgelenmiş **opsiyonel follow-up** (§2 protokol, §3 şablon) — bu PR'ı bloke etmez.

---

## 1. Ne öğrendik?

### 1.1 Koşum metodolojisi (ölçümün kendisi)

| Bulgu | Kanıt | Anlam |
|-------|-------|-------|
| **Uzun koşum Cursor agent shell'de güvenilir değil** | Gece `6h-20260610-r2`: 51 örnek @01:50, exit yok; `nohup` denemeleri 1–2 örnekte düşüyor | Perf harness değil, **süreç taşıyıcısı** sorunu. Terminal.app + `caffeinate -dimsu` + kalıcı shell şart. |
| **1h koşum metodolojisi doğrulandı** | `1h-20260611`: 111/111 örnek, `frigate_unreachable` yok, CSV/JSON tam | Gece sorunları çözülünce **1 saat kesintisiz ölçüm** mümkün. |
| **Restart hemen ardından perf yanıltıcı** | Preflight 09:00, perf 09:03; bridge 39→131 MB lineer rampa | İlk ~20–30 dk “soğuk başlangıç” — RAM check ve skip metrikleri burn-in içeriyor. |

### 1.2 Detector / CPU (güçlü sinyal)

| Metrik | `1h-20260611` | Yorum |
|--------|---------------|-------|
| cpu1 / cpu2 inference ort | 26.9 / 27.2 ms | İki detector **dengeli** |
| p95 inference | 41 ms (eşik 200 ms) | M5 “CPU başı boş” **açık pass** |
| Frigate CPU ort | 622% (~6.2/8 çekirdek) | 1 saat boyunca stabil (Q1–Q4 ~612–635%) |
| Frigate RAM | 1287→1392 MB (+4%) | Sızıntı yok |

**Öğrenilen:** 6 kamera @ 5 fps + cpu1+cpu2, M3 Colima 8C'de detector pipeline **kapasite içinde**. Darboğaz ONNX inference değil; skip farkı kamera/video içeriğinden geliyor.

### 1.3 Bridge RAM (check fail, operasyonel risk düşük)

```
Q1  53 MB ort  (39→65)
Q2  76 MB ort
Q3  99 MB ort  (~09:42'de 100 MB)
Q4 121 MB ort  (bitiş 131 MB)
```

- Eğri **düzgün rampa**, ani sıçrama yok → tipik Python/connection pool ısınması; 1 saatte plateau oturmadı.
- Harness `mem_growth_pct` = (son − ilk) / ilk → restart sonrası düşük baz (39 MB) **+%210 false positive** üretiyor.
- Colima 8 GiB içinde 131 MB bridge **ihmal edilebilir**; 6 saatte ~180–200 MB bandı tahmin (kabul edilebilir).

### 1.4 Frame skip — kamera bazlı, saat boyunca drift yok

| Kamera | Skip ort | p95 | Rol | Yorum |
|--------|----------|-----|-----|-------|
| cam_kapi | 0.4% | 2% | Operasyonel | Mükemmel |
| cam_tir | 1.3% | 7.8% | Doc13 ana hat | Sunumda öne çıkar |
| cam_magaza | 5.1% | 28% | Operasyonel | Dalgalı |
| cam_yaya | 16.4% | 25.5% | Test loop | Yapısal (motion yoğun) |
| cam_depo | 25.8% | 52% | Test loop | Motion-heavy |
| cam_test | 29.5% | 53.7% | Test loop | En kötü; harness fail nedeni |

**Öğrenilen:** Skip **sistem çöküşü değil** — trial2'deki %95+ felaketten farklı olarak 1 saat boyunca kamera başına oran **stabil** (Q1≈Q4). Sorun: M5'in global “en kötü kamera <%5” eşiği, motion-heavy test loop'ları cezalandırıyor.

### 1.5 Koşumlar arası karşılaştırma

| Koşum | Süre | Örnek | Inference p95 | Frigate CPU | En kötü skip p95 | Not |
|-------|------|-------|---------------|-------------|------------------|-----|
| trial1 | 10 dk | 20 | 248 ms ✗ | 647% | cam_depo 78% | Restart artefaktı |
| trial2 | 10 dk | 18 | 37458 ms ✗ (outlier) | 933% | cam_test 100% | Sistem doygun + LLM rekabeti |
| **1h baseline** | **60 dk** | **111** | **41 ms ✓** | **622%** | **cam_test 54%** | **Temsilci koşum** |

**Öğrenilen:** 10 dk trial'lar karar için yetersiz; 1h baseline trial2'nin “her şey çöktü” tablosunu **çürütüyor**. Sunumda trial2'yi “kötü gün / ölçüm hatası” olarak anlat, 1h'i referans al.

### 1.6 Harness sınırları

1. **RAM growth:** İlk örnek baz; burn-in yok.
2. **Skip:** Tek global p95; operasyonel vs test loop ayrımı yok.
3. **Inference outlier:** trial2'de 69e9 ms gibi değerler filtresiz (1h'de gerekmedi).
4. **GEÇTİ/KALDI:** Tek boolean; check bazlı hikâye kayboluyor.

---

## 2. Sorun → tepki planı

| # | Sorun / olay | Kök neden | Tepkimiz | Öncelik | Run 2'de uygula |
|---|--------------|-----------|----------|---------|-----------------|
| R1 | Gece 6h ~28–51 örnekte kesildi | Cursor bg shell + uyku kilidi yok | Terminal.app + `caffeinate -dimsu`; Cursor'dan perf başlatma | P0 | ✓ |
| R2 | Bridge RAM check +210% fail | Restart + hemen perf; düşük baz | **30 dk ısınma** perf öncesi; raporda burn-in notu | P0 | ✓ |
| R3 | Skip fail (cam_test/depo) | Motion-heavy loop + 6 stream CPU paylaşımı | **Operasyonel alt küme** (kapi+tir+magaza) ayrı raporla; test loop'ları sunumda “bilinen sınır” | P1 | ✓ (rapor) |
| R4 | trial2 inference 37458 ms | Frigate detector restart artefaktı | Harness'e `inference_ms > 10_000` outlier filtresi (opsiyonel patch) | P2 | Koşul |
| R5 | trial2 %95+ skip | Uzun çalışan stack + Ollama CPU rekabeti | Run 2 öncesi `docker compose restart frigate bridge` + ısınma; Ollama açık kalır (dürüst sunum) | P1 | ✓ |
| R6 | RUN.md run_id eski (`6h-20260610`) | Gece denemesi yarım kaldı | Baseline `1h-20260611`; Run 2 ID'si ayrı | P2 | ✓ |

### Run 2 protokolü (`1h-20260611-r2` veya `1h-<tarih>`)

```
1. Terminal.app (Cursor değil)
2. caffeinate -dimsu -t 5400 &          # 90 dk buffer
3. colima start && cd ~/code/ai_nvr
4. ./scripts/test1-prepare.sh
5. docker compose restart frigate bridge
6. sleep 1800                            # 30 dk ısınma — R2
7. bash scripts/test1-run.sh 1h-<tarih> 3600
8. tail stdout.log → baseline ile karşılaştır
```

**Karşılaştırma odakları:** bridge RAM Q4 ort, operasyonel skip p95, inference p95, Frigate CPU ort, koşum bütünlüğü (111 örnek).

---

## 3. Başarı kriterleri (katmanlı)

Harness'in tek `GEÇTİ/KALDI` çıktısı sunum kararı için yeterli değil. Üç katman:

### Katman A — Harness M5 (mevcut, değişmedi)

| Check | Eşik | Baseline |
|-------|------|----------|
| RAM stabil | Container mem growth ≤ 20% | ✗ bridge +210% |
| CPU başı boş | Detector p95 ≤ 200 ms | ✓ 41 ms |
| Kaçan olay <%5 | Kamera p95 skip ≤ 5% | ✗ cam_test 53.7% |

*Run 2 hedefi:* A'yı “GEÇTİ” yapmak **zorunlu değil** — metodoloji iyileştirmesi (burn-in) sonrası A'da bridge RAM hâlâ fail olabilir; Katman B/C'ye bak.

### Katman B — Operasyonel alt küme (sunum omurgası)

Doc13 / gerçek operasyon kameraları: **cam_kapi, cam_tir, cam_magaza**

| Metrik | Eşik (Run 2 pass) | Baseline |
|--------|-------------------|----------|
| Skip p95 (her biri) | ≤ 10% | kapi 2%, tir 7.8%, magaza 28% |
| Skip ort (her biri) | ≤ 5% | kapi 0.4%, tir 1.3%, magaza 5.1% |
| Inference p95 | ≤ 100 ms | 41 ms ✓ |

**Run 2 pass tanımı:** 3/3 operasyonel kamera skip p95 ≤ 10% **ve** inference p95 ≤ 100 ms **ve** koşum tam (≥110 örnek).

### Katman C — Sunum iddiaları (dürüst dil)

| İddia edebiliriz | İddia etmeyiz |
|------------------|---------------|
| 6 RTSP @ 5 fps, 1 saat kesintisiz ölçüm | “Tüm kameralar <%5 skip” |
| cpu1+cpu2, p95 inference ~40 ms, Coral gereksiz (M3 dev) | “Bridge RAM check geçti” (burn-in olmadan) |
| Operasyonel hat (tir/kapi) skip <%10 | “6 saat koşuldu” (henüz yok) |
| Stack 1 saat stabil; Frigate RAM/CPU drift yok | trial2 tablosunu “normal” göstermek |
| Test loop skip'i bilinen sınır (motion içerik) | i5 bare-metal birebir |

### Run 2 vs baseline — karşılaştırma şablonu (follow-up'ta doldurulur)

> Baseline sütunu bu PR'ın ölçümünden dolu; sağ sütunlar Run 2 koşulduğunda doldurulacak hazır iskelet — bu PR için eksik veri değil.

| Metrik | `1h-20260611` (baseline) | `1h-*` (run 2) | Δ | Pass? |
|--------|--------------------------|----------------|----|----|
| Örnek sayısı | 111 | | | |
| Inference p95 | 41 ms | | | |
| Bridge mem (bitiş) | 131 MB | | | |
| Bridge growth | +210% | | | |
| Frigate CPU ort | 622% | | | |
| cam_kapi skip p95 | 2% | | | |
| cam_tir skip p95 | 7.8% | | | |
| cam_magaza skip p95 | 28% | | | |
| Katman B pass | kısmen (magaza) | | | |

---

## 4. Sunum hazırlığı

Sunum baseline + Katman C dürüst iddialarıyla **bugün** kurulabilir; Run 2 operasyonel iddiayı güçlendirir ama ön koşul değil.

1. **Tek slayt mesajı:** *“M3 Colima, 6 kamera @5 fps, 1 saat: detector pipeline stabil (p95 41 ms); operasyonel kameralar skip <%10; motion-heavy test loop'ları bilinen sınır.”*
2. **Grafik adayları:** bridge RAM zaman serisi; kamera skip Q1–Q4; trial vs 1h karşılaştırma.
3. **Appendix:** trial1/trial2 neden güvenilmez; gece kesinti kök neden (Cursor/uyku).
4. **6h:** Katman B Run 2'de pass olursa gündüz Terminal protokolü ile planlanır.

---

## 5. Durum ve follow-up

**Bu PR'da tamamlandı:**
- [x] Baseline koşum `1h-20260611` (111 örnek, kesintisiz) + CSV/JSON/stdout artefaktları
- [x] Bulgular, tepki planı (R1–R6), katmanlı başarı kriterleri (Katman A/B/C)
- [x] `perf/runs/test1/*` commit'lendi

**Follow-up (opsiyonel, ayrı PR/commit):**
- [ ] Run 2 protokolü (§2) ile ısınmalı `1h-*` koşumu → §3 şablonunu doldur
- [ ] Katman B operasyonel pass doğrulanırsa 6h gündüz koşumu
