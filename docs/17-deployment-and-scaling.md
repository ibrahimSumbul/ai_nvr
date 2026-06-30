# 17 — Dağıtım & Ölçekleme: Backend (bu repo) + On-Prod İzleme Katmanı

> **Durum etiketi — VİZYON + DAĞITIM MİMARİSİ (kod değil).** Bu doküman *nasıl
> kurulup ölçekleneceğini* ve *operatör izleme katmanının nereye oturacağını* anlatır.
> İçindeki tek **çalışan** parça bu reponun backend pipeline'ıdır (M0–M7, dev-stack);
> izleme duvarı, on-prod arayüz ve GPU ölçekleme **henüz yoktur** — tasarımdır.
> Mevcut dokümanlar bu sayfayla değişmez; burada yalnız **referans** verilir
> (bkz. [§11](#11-ilişkili-dokümanlar)).
>
> **İlke — ölçülen ≠ çıkarsanan, bu sayfaya da uygulanır.** Projenin manşeti olan
> ayrım ([`12 · Adli Davranış Zekası`](12-forensic-behavioral-intelligence.md)) burada
> da geçerli: aşağıda **ÇALIŞAN** ile **VİZYON/HENÜZ YOK** her yerde açıkça işaretlidir.
> Bir dağıtım planı "ölçülmüş" değildir.

---

## 1. Amaç & Kapsam

**Ne:** Bu reponun sahaya nasıl konuşlandırılacağı (deployable AI backend), izleme
arayüzünün backend'den nasıl ayrıldığı (sorumluluk sınırı), ve kamera sayısının CPU →
GPU ile nasıl büyütüleceği (ölçekleme yolu).

**Ne DEĞİL:** Bu doküman kod, API spec'i veya tek-tık kurulum vaadi değil. İzleme
duvarı yazılımı bu repoda yoktur. GPU ölçekleme **test edilmemiştir** — config
soyutlamasına dayanan bir plandır.

| | Durum |
|---|---|
| Backend pipeline (Frigate + bridge + Postgres + MQTT + Grafana, host'ta Ollama) | ✅ Çalışıyor — dev-stack (M0–M7) |
| WebRTC izleme duvarı (go2rtc/MediaMTX grid) | ⬜ Vizyon — repoda yok, on-prod gelişir |
| On-prod operatör arayüzü (zengin izleme) | ⬜ Vizyon — saha tarafının işi |
| GPU ölçekleme (TensorRT/OpenVINO/ROCm detector) | 🟡 Tasarım — config soyutlaması var, **denenmedi** |
| Custom detector (sözleşme arkasında) | ⬜ Vizyon — gerekirse, henüz gereksiz |

---

## 2. Dağıtım Modeli — Backend (bu repo) + On-Prod İzleme Arayüzü

İki sorumluluk, iki sahip:

- **Backend (bu repo, kuruluma hazır).** Docker stack: Frigate + bridge + Postgres +
  MQTT + Grafana, host'ta Ollama. Klonlanır, yapılandırılır, ayağa kalkar; AI
  pipeline'ı (detection → tracking → semantik zenginleştirme → alarm/log) burada koşar.
  Repo ayrıca izleme katmanının oturacağı **temel iskeleti** taşır — somut olarak:
  dev-stack'in MediaMTX RTSP kaynakları (`~/code/mediamtx`) ve Frigate'in dahili go2rtc'si
  ([`frigate/config.yml`](../frigate/config.yml)) — ama zengin izleme duvarı **kendisi
  değildir** (⬜ vizyon).

- **On-prod izleme arayüzü (saha/müşteri gelişir).** Operatörün 7/24 baktığı
  WebRTC canlı izleme duvarı **bu repoda yoktur**; her tesisin kamera düzeni / operatör
  alışkanlığı / ekran sayısı farklı olduğu için saha tarafında geliştirilir. Repo
  backend'i ve iskeleti verir; izleme duvarı entegrasyon adımı **sonraya** bırakılmıştır.

**Neden bu ayrım:** AI backend tekrar-kullanılabilir ve test edilebilir bir çekirdektir;
izleme UI'ı saha-bağımlıdır. İkisini tek depoya tıkıştırmak çekirdeği saha varyasyonuna
esir eder.

---

## 3. Katmanlar & Sorumluluk Ayrımı

Tek ürüne her şeyi yüklememek için dört katman, dört net iş. **İzleme ≠ AI.**

| Katman | Görev | Sahip / Durum | Yük |
|---|---|---|---|
| **NVR (Dahua)** | 100 kameranın 7/24 **kaydı** + matris izleme | Mevcut NVR — dokunulmaz | NVR donanımı |
| **WebRTC izleme duvarı** | Operatörün **canlı izleme** grid'i | ⬜ Vizyon — on-prod gelişir | H.264 passthrough → ucuz |
| **Frigate (AI subset)** | Yalnız **detection/tracking** (kamera alt kümesi) | ✅ Çalışıyor (bu repo) | ~1 çekirdek/kamera (CPU) |
| **Grafana + DMSS push** | **Alarm / analiz / dashboard** = asıl ürün çıktısı | ✅ Çalışıyor (bu repo) | düşük |

Kritik nokta: **NVR kaydı yapar, Frigate yalnız AI subset'ini görür.** 100 kameranın
hepsi AI'a girmez. İki ayrı sayıyı karıştırmamak gerekir:

- **Bugünkü tek-makine CPU stack'i ≈ 3–4 detect kamerası** taşır (**ÖLÇÜLDÜ** —
  ~1 çekirdek/kamera, bkz. [§6.1](#61-bugün-cpu--✅-ölçüldü)).
- [`02 · Donanım`](02-hardware.md)'daki "100 kameranın **~%30–40'ı** AI kapsamında"
  hedefi (≈ 30–40 kamera) **yeterli detection donanımı / GPU varsayar**
  (**ÇIKARSANMIŞ** — bkz. [§6.2](#62-gpu-gelince--tek-satır-config-modül-çıkarma-değil)).

İzleme duvarı (canlı bakış) ile Frigate (AI) ayrı işlerdir; operatörün gözü duvarda,
AI yalnız seçili kameralarda koşar.

---

## 4. İzleme Katmanı (WebRTC) — ⬜ Vizyon

> **Durum:** Bu katman **repoda yok**, on-prod gelişir. Aşağısı tasarım gerekçesidir.

**Yaklaşım:** İzleme duvarı kendi **go2rtc / MediaMTX WebRTC** grid'ini sunar.
Kameraların **H.264 substream**'i tarayıcıya WebRTC ile **passthrough** edilir —
decode/transcode YOK. Bu yüzden duvar 4 çekirdekte ucuzdur: CPU video çözmez, sadece
paket taşır.

> ⚠ **H.265/HEVC tuzağı.** Tarayıcı WebRTC HEVC'yi yaygın desteklemez → HEVC akışı
> için transcode gerekir → CPU patlar. **Duvar için kameraların H.264 substream'i
> şarttır.** (Frigate'in detect girişi için de H.264 substream zaten tercih edilir.)
> *Kayıt:* sınır mutlak değil — bazı yeni tarayıcılar (Chrome 136+) donanım decoder
> varlığında H.265 destekleyebilir, ama bu tarayıcı + donanım decoder + WebRTC
> negotiation'a bağlıdır ve saha genelinde garanti edilemez. Bu yüzden H.264 substream
> güvenli tercihtir.

**Neden Frigate'in kendi duvarı değil:** Frigate UI bir **AI debug/review** yüzüdür
(zone çizimi, tespit doğrulama, klip inceleme) — 7/24 operatör izleme duvarı değildir
(bkz. [§7](#7-operasyon-yüzeyleri)). Operatörün canlı grid'i ayrı bir yüzeydir.

> **"Kendi WebRTC'n israf mı?"** Hayır. Frigate'in WebRTC'si zaten go2rtc'dir; izleme
> duvarının da go2rtc/MediaMTX kullanması aynı olgun teknolojiyi farklı bir rol için
> kullanmaktır (AI review yüzü ≠ 7/24 operatör duvarı), tekrar değil.

---

## 5. Swappable Detector & İnsülasyon Sözleşmesi — ✅ (sözleşme çalışıyor)

Bridge ile Frigate arasındaki bağ kod değil, bir **sözleşmedir**: MQTT event şeması +
HTTP snapshot/stats API. Bu sözleşme sabit kaldıkça Frigate'in *içi* değiştirilebilir.
**Frigate, sözleşme arkasında değiştirilebilir (swappable) bir kutudur.**

> **Anti-pattern:** Frigate'ten "modül söküp alıp" kendi koduna gömmek. Bu fork bakımı,
> upstream güncelleme kaybı ve teknik borç demektir. Doğru yol: kutuyu olduğu gibi
> kullan, yalnız sözleşmeye konuş.

### 5.1 Sözleşme yüzeyi (repo'dan teyitli)

**MQTT (bridge SUBSCRIBE):**

| Topic | Amaç |
|---|---|
| `frigate/events` | Detection olayları (`new`/`update`/`end`) + nesne metadata'sı (person/car/truck…, zone, score, bbox). Her olay `new→update→end` boyunca **stabil bir tracking session ID** taşır ([`events.py:48-49`](../bridge/bridge/events.py) `event_id`). |
| `frigate/available` | Frigate servis sağlığı, LWT (Last-Will) ile. Payload `online`/`offline`; Frigate çökerse servis-offline alarmı (kamera-offline'dan ayrı). |

Bridge varsayılan abonelik `frigate/#`
([`bridge/bridge/mqtt.py:23`](../bridge/bridge/mqtt.py)); olay modelleri
[`bridge/bridge/events.py`](../bridge/bridge/events.py) (`FrigateEvent`, `FrigateObject`);
servis sağlığı [`bridge/bridge/frigate_monitor.py`](../bridge/bridge/frigate_monitor.py);
yönlendirme [`bridge/bridge/main.py`](../bridge/bridge/main.py) (`_listen_loop`:
`frigate/events`→state machine, `frigate/available`→FrigateMonitor).

**HTTP API:**

| Endpoint | Kullanım |
|---|---|
| `/api/stats` | Periyodik kamera sağlığı (CameraMonitor) — `camera_fps` çekilir; eşik üstü `0` ise kamera-offline alarmı. Poll ~30 sn. ([`bridge/bridge/cameras.py:61-72`](../bridge/bridge/cameras.py)) |
| `/api/events/{event_id}/snapshot.jpg` | Tespit edilen nesnenin tek kare snapshot'ı; `?height=N` ile sunucu-taraflı resize (LLM gecikmesi azaltma). M2 zone first_entry + M3 tır renk analizi. ([`bridge/bridge/snapshots.py:39-70`](../bridge/bridge/snapshots.py)) |
| `/api/{camera}/latest.jpg` | Olaydan bağımsız son canlı kare (event-agnostic snapshot). |

### 5.2 Sözleşmenin değeri

Bu yüzey sabit olduğu için detection backend'i **CPU Frigate → GPU Frigate →
(gerekirse) custom detector** yolunda değiştirilebilir; bridge'in MQTT/API sözleşmesi
**değişmez**. Bridge detector-agnostiktir: hangi inference backend'i koşarsa koşsun,
olaylar aynı `frigate/events` topic'inden, aynı şemayla akar.

---

## 6. Ölçekleme Yolu — 🟡 Tasarım

> **Durum:** CPU baseline **ölçüldü**; GPU geçişi **config soyutlamasına dayanan
> plandır, denenmedi.**

### 6.1 Bugün (CPU) — ✅ ölçüldü

Üretim detector bloğu ([`frigate/config.yml:24-30`](../frigate/config.yml)):

```yaml
detectors:
  cpu1:
    type: cpu
    num_threads: 3
  cpu2:
    type: cpu
    num_threads: 3
```

**Perf baseline (`1h-20260611`, 2026-06-11, 1 saat, 111/111 örnek)** — yük: 6 kamera
@5fps, 640×480, 2 CPU detector (cpu1+cpu2), macOS Colima 8 çekirdek:

- Detector inference **p95 = 41 ms** (eşik 200 ms) ✓
- Frigate CPU ortalama **~622%** (~6.2/8 çekirdek; saat boyu 612–635% bandında stabil)
- Frigate RAM 1287→1392 MB (+%4, sızıntı yok)
- Frame-skip p95 (operasyonel kameralar): cam_kapi %2, cam_tir %7.8, cam_magaza %28

**Pratik kural:** ~1 çekirdek/kamera → 4 çekirdek ≈ **3–4 detect kamerası**. Bu kural
yük **operasyonel-kanıt katmanında** doğrulandı (docs/14 terminolojisiyle *Katman B* =
3/3 operasyonel kamera skip p95 ≤ %10); harness'in *Katman A* (ham, strict) "fail"i
bridge RAM büyüme metodolojisidir (restart sonrası düşük baz, warm-up önerisi). Detay:
[`perf/runs/test1/FINDINGS.md`](../perf/runs/test1/FINDINGS.md); örnekleme
[`bridge/bridge/perf.py`](../bridge/bridge/perf.py); kanıt-katman çerçevesi
[`14 · Test Stratejisi §1-2`](14-testing-and-production-readiness.md).

> **Taşıma sınırı (ölçülen ≠ çıkarsanan):** Bu rakamlar **macOS Colima 8 çekirdek**
> üzerinde ölçüldü. "~1 çekirdek/kamera → 3–4 kamera" kuralı donanım-bağımsız bir sabit
> **değildir**; i5 bare-metal veya gerçek saha donanımına taşınınca değişir (FINDINGS
> *Katman C* "i5 bare-metal birebir" iddia etmemeyi söyler). Saha sayısı yeniden
> ölçülmelidir.

### 6.2 GPU gelince — tek satır config, modül çıkarma DEĞİL

Frigate'in detector soyutlaması zaten GPU backend'lerini destekler. CPU'dan GPU'ya
geçmek **bridge kodunu değil, Frigate'in detector backend bloğunu** (`type` + `device`)
değiştirmektir. Intel iGPU için (OpenVINO) örnek:

```yaml
detectors:
  ov:
    type: openvino
    device: GPU      # OpenVINO: CPU / GPU / NPU
```

> ⚠ **`device` semantiği backend'e göre değişir** — "tek satır" basitleştirmesi yanıltıcı
> olmasın: `device: GPU` string'i **yalnız OpenVINO** içindir. TensorRT'de `device` bir
> **tamsayı GPU indeksidir** (`device: 0`), string `GPU` değil. AMD'de ise `type: rocm`
> diye bir detector **yoktur**; AMD GPU `type: onnx` + `-rocm` ekli Frigate Docker imajı
> ile çalışır. Değişmeyen şey **bridge sözleşmesidir** ([§5](#5-swappable-detector--insülasyon-sözleşmesi--✅-sözleşme-çalışıyor)),
> detector bloğunun kendisi değil.

| Backend | `type` | `device` | Gereksinim |
|---|---|---|---|
| CPU (bugün) | `cpu` | — (`num_threads`) | herhangi |
| Intel | `openvino` | `GPU` (string; CPU/GPU/NPU) | Intel iGPU/dGPU |
| NVIDIA | `tensorrt` | `0` (tamsayı GPU indeksi) | NVIDIA GPU + TensorRT imajı/kurulumu |
| AMD | `onnx` | — | AMD GPU + `-rocm` ekli Frigate imajı |

Beklenen sonuç: **detection GPU'ya geçer; UI / tracking / MQTT / record / snapshot
değişmez** — sözleşme aynı kaldığı için artık onlarca kameraya çıkılabilir. Ancak bu
"hiçbir yan etki yok" davranışı da **mantıken çıkarsanmıştır, ölçülmemiştir**: detector
tipini değiştirmenin yan etkisizliği bu projede test edilmedi.

> **Dürüst sınır:** Bu GPU yollarının hiçbiri bu projede **çalıştırılmadı**. Frigate
> bunları belgeler; bizim ölçtüğümüz tek konfigürasyon CPU'dur. GPU kamera kapasitesi
> rakamı **çıkarsanmış**, ölçülmemiştir. Ayrıca GPU yalnız **detection** darboğazını
> kaldırır; gerçek kamera tavanı ayrıca decode (ffmpeg) yükü, RAM ve olay-tetikli Ollama
> inference kuyruğuyla sınırlıdır (bkz. [`02 · Donanım`](02-hardware.md) Darboğaz 1/2/3) —
> tek darboğaz GPU detector değildir.

---

## 7. Operasyon Yüzeyleri — Rol Ayrımı (rakip değil)

İki/üç UI birbirinin rakibi değil; farklı rollerdir.

| Yüzey | Rol | Kim / Ne zaman | Durum |
|---|---|---|---|
| **WebRTC izleme duvarı** | Operatörün ANA canlı izleme ekranı (SmartPSS yerine geçmesi *hedeflenir*; akıcı WebRTC grid hedefi) | Operatör, 7/24 | ⬜ Vizyon (on-prod) |
| **Frigate UI** | AI subset'in **kurulum/debug/review** yüzü (zone çizimi, tespit doğrulama, klip inceleme) | Admin, ara sıra | ✅ Çalışıyor |
| **Grafana + DMSS push** | **Asıl ürün çıktısı** — alarm / analiz / dashboard | Yönetim + operatör bildirimi | ✅ Çalışıyor |

> **İleride opsiyonel:** WebRTC grid + Frigate API event'leri tek bir custom panelde
> birleştirilebilir — **şart değil**, rol ayrımı tek başına çalışır.

---

## 8. Güvenlik & KVKK

- **Tam self-host, bulut bağımlılığı yok.** LLM lokal Ollama'da koşar, görüntüler
  tesisten çıkmaz (bkz. [`06 · LLM stratejisi`](06-llm-strategy.md)). Bu mimaride
  bulut token/kota/PII-dışarı-çıkma riski yapısal olarak yoktur.
- **Ağ:** izole VLAN + internete kapalı segment + reverse-proxy/auth. Frigate auth
  açık, anonymous bypass kapalı ([`frigate/config.yml`](../frigate/config.yml) `auth`).
- **Asıl risk ürün değil, ağ segmentasyonudur:** kamera/NVR segmentinin internetten ve
  ofis LAN'ından ayrılması. Bu bir konuşlandırma disiplinidir, kod değil.
- **Repo hijyeni:** gerçek kamera görüntüsü / PII bu repoya **girmez** — dev-stack
  sentetik MediaMTX RTSP stream'leriyle çalışır.
- **Repo PII'siz ≠ ürün PII'siz.** Self-host olması yalnız *bulut-sızması* vektörünü
  kapatır; PII riskini ortadan kaldırmaz. Saha tarafı (on-prod izleme duvarı + Frigate
  record) **gerçek görüntü** işler — kayıt süresi, erişim logu, veri sahibi hakları gibi
  KVKK yükümlülükleri **on-prod katmanın sorumluluğudur** (açık konu, bkz.
  [§10](#10-açık-sorular--sonraki-adımlar)).

---

## 9. Kuruluma Hazırlık Durumu (turnkey gerçeği — dürüst)

Yakın zamanda taşınabilirlik sağlamlaştırıldı (**PR #37**): Linux için compose
`extra_hosts: host-gateway` (bridge + frigate, host'taki Ollama'ya ulaşım),
`make migrate` `run --rm` ile, doküman doğruluk düzeltmeleri.

**Ama hâlâ tek-tık `docker pull` DEĞİL.** Kurulum "klonla → build → yapılandır"
akışıdır, ~6 adım:

1. `.env` doldur — bu arada Ollama host URL'i (Linux'ta PR #37'nin `host-gateway`
   fix'i sayesinde `host.docker.internal`)
2. host'ta Ollama kur
3. vision modeli çek (`qwen2.5vl:7b`)
4. `docker compose up -d --build`
5. `alembic upgrade head` (DB migrate — şart)
6. kamera config'i (`frigate/config.yml`)

Kurulum adımları: [`03 · Kurulum`](03-setup.md). Bu liste **çalışan** gerçektir; "turnkey"
ifadesi yalnız taşınabilirlik sağlamlaştırması içindir, sıfır-yapılandırma anlamına gelmez.

> **Dürüst sınır:** Bu akış **dev-stack'te (macOS Colima) koşuldu**. PR #37'nin Linux
> `host-gateway` fix'i teoride doğrudur, ama temiz bir Linux saha makinesinde uçtan uca
> kurulum (host Ollama + model + alembic dâhil) **henüz doğrulanmadı (⬜)**.

---

## 10. Açık Sorular / Sonraki Adımlar

- **WebRTC duvar** (⬜): go2rtc mı MediaMTX mi; H.264 substream zorunluluğunun saha
  kameralarında garantisi; çoklu-ekran grid düzeni — hepsi on-prod kararı.
- **Substream eşzamanlılık limiti** (⬜): aynı kameranın H.264 substream'ini hem izleme
  duvarı hem Frigate detect çekerse, Dahua/kamera **kaç eşzamanlı substream bağlantısı**
  verir? Substream paylaşımı (relay/proxy) mi gerekir, ayrı stream mi — saha riski.
- **GPU ölçekleme** (🟡): hangi backend (OpenVINO/TensorRT/ONNX-ROCm); GPU kamera
  kapasitesi **ölçülmeli** (şu an çıkarsanmış); CPU→GPU geçişinde detector p95/skip
  baseline'ı tekrar alınmalı.
- **Custom detector** (⬜): yalnız GPU Frigate yetmezse; sözleşme ([§5](#5-swappable-detector--insülasyon-sözleşmesi--✅-sözleşme-çalışıyor))
  korunmalı.
- **On-prod arayüz entegrasyonu** (⬜): backend + iskelet hazır; izleme duvarı ile
  backend'in birleştirilmesi planlandı, **henüz yapılmadı**. Açık: panel hangi API ile
  beslenir — Frigate `/api/events` mi, yoksa bridge'in açacağı yeni bir read-endpoint mi?
- **Saha KVKK** (⬜): on-prod katmanın gerçek-görüntü yükümlülükleri (kayıt süresi,
  erişim logu, veri sahibi hakları) — bkz. [§8](#8-güvenlik--kvkk).
- **Saha pilotu** (⬜): gerçek Dahua NVR + canlı kameralar — bkz.
  [`14 · Test Stratejisi §4`](14-testing-and-production-readiness.md) (Gerçek testlere
  hazırlık; Dahua entegrasyonu = "basamak 6").

---

## 11. İlişkili Dokümanlar

Bu doküman aşağıdakilere **referans** verir; içeriklerini tekrarlamaz. Entegrasyon
(özellikle on-prod izleme duvarı) **sonraya** bırakılmıştır.

- [`01 · Mimari`](01-architecture.md) — bileşen şeması, bridge/Frigate/Ollama yerleşimi.
- [`02 · Donanım`](02-hardware.md) — detector kapasitesi, CPU/Coral/GPU bağlamı.
- [`03 · Kurulum`](03-setup.md) — klonla→build→yapılandır akışı ([§9](#9-kuruluma-hazırlık-durumu-turnkey-gerçeği--dürüst)).
- [`10 · Neden Frigate?`](10-why-frigate.md) — saf vision LLM'in limitleri; neden Frigate detection/tracking yapar.
- [`12 · Adli Davranış Zekası`](12-forensic-behavioral-intelligence.md) — ölçülen ≠ çıkarsanan manşeti.
- [`14 · Test Stratejisi`](14-testing-and-production-readiness.md) — perf baseline, kanıt katmanları, saha sınırı.
- [`16 · QR Giriş Kamerası`](16-qr-entrance-camera.md) — kamera boyutlandırma/lens (saha konuşlandırma fiziği).
