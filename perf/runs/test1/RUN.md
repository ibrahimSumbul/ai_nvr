# Test 1 — Altyapı (CPU / RAM / detect stabilitesi)

**Amaç:** Gerçek dev stack’te (M3 host, Colima Docker) 6 kamera @ 5 fps sürekli detect
yükü altında Frigate + bridge + stack’in **6 saat** stabil kalıp kalmadığını ölçmek.
Doc 13 operasyonel pulse değil — **video/detector altyapısı**.

**Sunum cümlesi:** *“6 RTSP stream, cpu1+cpu2, Ollama açık (yalnız olay-tetikli LLM);
M5 kriterleri: RAM stabil, detector inference, frame skip <%5.”*

**Bulgular / tepki planı / sunum kriterleri:** [`FINDINGS.md`](FINDINGS.md)  
**Baseline:** `1h-20260611` (111 örnek; harness 1/3, Katman B/C analizi `FINDINGS.md`) · **Run 2:** ısınmalı karşılaştırma = opsiyonel follow-up

---

## Ortam (her koşumda doldur)

| Alan | Değer |
|------|--------|
| `run_id` | `1h-20260611` (baseline) → `1h-*` (run 2) |
| Git commit | `git rev-parse --short HEAD` |
| Host | Apple M3, 8 logical CPU *(sysctl hw.ncpu)* |
| Colima | `colima list` — CPU/RAM *(simülasyon yok, default profil)* |
| Frigate detectors | cpu1 + cpu2, `num_threads` each *(config.yml)* |
| Kameralar | 6 detect: cam_test, cam_depo, cam_kapi, cam_magaza, cam_yaya, cam_tir |
| Stream kaynağı | MediaMTX `rtsp://host.docker.internal:8554/...` |
| Ollama | Açık — `qwen2.5vl:7b` *(LLM perf’i bozmaz; cam_tir olay-tetikli)* |
| Dahua alarm | `.env` `DAHUA_ALARM_ENABLED` *(dev: genelde false)* |

---

## Komut

```bash
# Hazırlık
./scripts/test1-prepare.sh

# Deneme (10 dk)
./scripts/test1-run.sh trial 600

# Asıl koşum (6 saat)
./scripts/test1-run.sh 6h 21600
```

Harness:

```bash
make perf ARGS="--duration 21600 --interval 30 --out perf/runs/test1/<run_id>"
```

---

## Çıktılar (repo’ya commit)

| Dosya | İçerik |
|-------|--------|
| `<run_id>.csv` | Zaman serisi: container cpu/mem, kamera skip_ratio, detector inference_ms |
| `<run_id>.json` | Özet istatistik + 3 check pass/fail |
| `<run_id>.stdout.log` | Harness tablo çıktısı |
| `preflight.txt` | Koşum öncesi `docker compose ps`, Frigate stats özeti |
| `RUN.md` | Bu dosya — ortam tablosu dolu |

---

## Pass kriterleri (M5 default)

| Check | Eşik |
|-------|------|
| RAM stabil | Container bellek büyümesi ≤ **%20** |
| CPU başı boş | Detector p95 inference ≤ **200 ms** |
| Kaçan olay <%5 | Kamera p95 `skipped_ratio` ≤ **%5** |

JSON `passed: true` + stdout **GEÇTİ ✅** → Test 1 başarılı.

---

## Ne iddia etmiyoruz

- 50 kamera decode/load simülasyonu **değil** (6 stream).
- Doc 13’ün 5 senaryo kamerasının tamamı **değil** (olay yoğunluğu Test 2).
- Production i5 4C/8GB bare-metal birebir **değil** (M3 + Colima VM).

---

## Koşum sonrası kontrol listesi

- [ ] JSON `samples` ≈ `duration / 30` (6h → ~720)
- [ ] CSV’de `cpu1` ve `cpu2` `inference_ms` satırları var
- [ ] Hiçbir check “veri yok” değil
- [ ] `docker compose logs` — `camera.offline` yok
- [ ] Grafana: Çevrimdışı Kamera = 0
