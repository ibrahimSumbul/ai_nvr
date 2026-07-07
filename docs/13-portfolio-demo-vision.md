# 13 — Portföy Demo Vizyonu (5 Kamera)

> Bu doküman AI NVR'ın **portföy demosunu** somutlaştırır: 5 kameralı, sahnelenmiş,
> gizlilik-öncelikli lokal AI senaryosu — "demoyu nasıl çekip kuruyoruz". Soyut M8
> spec'i ve build kontratları için bkz. [`12-forensic-behavioral-intelligence.md`](12-forensic-behavioral-intelligence.md).
> `docs/12` "M8 nedir"i, bu dosya "somut demoyu" anlatır.

## 1. Amaç

Mevcut Dahua CCTV altyapısı üzerinde, **görüntüler tesisten çıkmadan** (lokal Ollama
VLM, aylık $0), olayları yalnız *tespit* etmeyen, **açıklayan** ve **ölçüleni
çıkarsanandan ayıran** bir adli (forensic) katman.

Pitch: *"Olayı açıkla; ölçüleni beyandan ayır."*

## 2. Mimari ilke (omurga)

İki ilke tüm demoyu yönetir.

### 2.1 ÖLÇÜLEN vs ÇIKARSANAN
- **ÖLÇÜLEN** = deterministik, doğrulanabilir sensör çıktısı — Frigate sayımı/varlığı,
  kart sistemi kaydı, config (kapı no). Tekrar üretilebilir.
- **ÇIKARSANAN** = VLM'in semantik yargısı — yük tipi, hasar, anomali, ihlal türü.
  **Güven etiketli.**
- Her rapor alanı bu ikisinden hangisi olduğunu **açıkça** taşır (hem veri modelinde
  hem raporda). Bu ayrım portföyün manşetidir.

### 2.2 "VLM'i yalnız hak ettiği yerde"
- **Sayma, eşleştirme, aritmetik, sayım** → Frigate + veri + kod.
- **Semantik açıklama / yargı** → VLM.
- VLM'i her kameraya yapıştırmak (LLM-for-LLM's-sake) bir **anti-pattern**; restraint
  bir kıdem sinyalidir ve demonun parçası olarak **sergilenir**.
- **VLM'e asla saydırma** (palet, imza, kişi). Sayım her zaman ölçülen tarafta.

> **Gecikme:** VLM lokal CPU'da ~46 s/çağrı → yalnız **olay-sonu** veya **istisna**
> anında çağrılır. Real-time kararlar (forklift yakınlığı vb.) Frigate'in işidir.

## 3. 5-Kamera Haritası

Üç sütun, iki handoff + bir mutabakat:

| Sütun | Kameralar | Ne üretir |
|---|---|---|
| **Tır lifecycle** | 1 (giriş) → 2 (dok) | kimlik → kargo; birleşik tır yolculuğu raporu |
| **Kişi handoff** | 3 (oda) → 4 (kapı) | izinsiz giriş → nereye gitti |
| **Erişim mutabakatı** | 5 (geçiş/masa) | algılanan-gerçek vs kart/imza kaydı (turnikesiz) |

| # | Kamera | VLM çağırır? | Çekirdek mekanizma |
|---|---|---|---|
| 1 | Tır giriş | ✅ (mevcut M3) | truck-VLM kimlik + lifecycle zamanı |
| 2 | Tır dok | ✅ (yeni) | Frigate sayar, VLM envanter/anomali açıklar |
| 3 | Oda | ○ opsiyonel | zone state machine (varlık) |
| 4 | Oda kapısı | ❌ | spatial-temporal eşleştirme |
| 5 | Geçiş/masa | ✅ yalnız istisnada | Frigate+kart mutabakatı (VLM ihlal-anlatıcı) |

## 4. Kamera başına detay

### Kamera 1 — Tır giriş (kimlik + lifecycle açılış)
- **Açı:** giriş kapısı.
- **Frigate ölçer:** tır varlığı, `giriş_ts` / `çıkış_ts` → tesiste kalış süresi.
- **VLM (mevcut M3 truck akışı):** çekici rengi + dorse tipi/rengi (`qwen2.5vl`).
- **QR kimlik (M8 tasarım eki — kod YOK):** tır/dorse `F0100`-sıralı opak QR ile de kimliklenip
  dok-kapı atamasına bağlanabilir; yakalama/ortam fiziği + giriş-kamera rol şablonu
  [`15-adaptive-capture.md`](15-adaptive-capture.md) §15.8/§15.9, lens/boyut analizi
  [`16-qr-entrance-camera.md`](16-qr-entrance-camera.md).
- **Rol:** kamera 2'deki unload'u **doğru tıra bağlayan çıpa**. Tek başına neredeyse
  mevcut özellik — değeri LİNK'te; lifecycle'ın açılış perdesi.
- **Video:** tırın kapıdan girişi + çıkışı.

### Kamera 2 — Tır dok (unload envanteri) ⭐ en güçlü dilim
- **Açı:** **tepeden (overhead)** — sayım + mekânsal anomali için ideal.
- **Frigate ölçer:** palet çizgi-geçişi sayımı (ÖLÇÜLEN); "boşaltma bitti" sinyali
  (N dk yeni geçiş yok + tır hâlâ rampada).
- **VLM (yeni, olay-sonu tek çağrı):** yük tipi/içerik (streç/açık-kasa/varil),
  durum (hasarlı/eğik/dengesiz), sahne anomalisi (sürücü şeridinde palet, yere
  düşmüş yük). **Odak = envanter** (kullanıcı seçimi); hasar önemli; baret/PPE **değil**.
- **Çıktı şeması (taslak):**
  ```
  UnloadRaporu:
    kapi_no:       3                       # ÖLÇÜLEN (config)
    palet_sayisi:  8                       # ÖLÇÜLEN (Frigate çizgi-geçişi)
    tir_rengi:     beyaz                    # kamera 1 (truck akışı)
    yuk_tipi:      [streç×6, açık-varil×2]  # ÇIKARSANAN (VLM)
    durum:         anomali                  # normal|dikkat|anomali (VLM)
    anomaliler:    ["1 palet sürücü şeridinde"]  # ÇIKARSANAN (VLM)
    guven:         0.82
  ```
- **Killer çıktı (kamera 1+2 birleşik):**
  > *"Beyaz çekici / tenteli dorse — Kapı girişi 14:20 → Dok 3'te 8 palet boşalttı
  > (6 streç, 2 varil) 14:35 → çıkış 15:10. Tesiste 50 dk."*
- **Güvenlik notu:** forklift/transpalet önünde kişi = **Frigate real-time** (bbox
  yakınlığı, ÖLÇÜLEN — 46 s ile *önlenemez*); VLM yalnız kapanış raporunda not düşer
  ("boşaltmada 1 yakın-temas").
- **Video:** tırdan paletlerin (forklift/elle) bir çizgiyi geçerek inişi, tepeden.

### Kamera 3 — Oda (izinsiz giriş — handoff açılış)
- **Frigate ölçer:** kişi varlığı (mevcut zone state machine, M2).
- **VLM (opsiyonel, M8.1):** grounded narrative — davetsiz kişinin betimi.
- **Rol:** kişi-lifecycle açılışı.
- **Video:** birinin odaya izinsiz girişi.

### Kamera 4 — Oda kapısı (çıkış/yön — handoff kapanış)
- **Frigate ölçer:** çıkış geçişi.
- **Mekanizma:** spatial-temporal eşleştirme (M8.2) — *aynı kişi mi?* **Görünüm-tabanlı
  Re-ID DEĞİL** (KVKK + güvenilirlik kararı).
- **Çıktı:** davetsiz kişinin izi (oda → çıkış → yön).
- **Not:** kullanıcı bu iki kamera videosunu kendisi hazırlıyor.

### Kamera 5 — Geçiş/masa (erişim mutabakatı — turnikesiz)
- **Açı:** masayı/geçişi **5-10 m'den** görür; **belgeyi GÖRMEZ** — eylemi sayar
  (kaç kişi geçti/imza attı, ne zaman).
- **Frigate ölçer:** kişi geçiş sayımı + zaman (ÖLÇÜLEN).
- **Kart sistemi:** kart okuma kaydı (1-5 cm) — **veri, görüntü değil**.
- **Mutabakat:** kişi-sayımı vs kart-sayımı = **aritmetik (VLM DEĞİL)** → tailgating /
  başkası-adına (proxy) bayrağı. Örn. "12 kişi geçti, 14 kart → 2 fazla."
- **VLM (yalnız istisnada):** ihlal türünü açıklar — "iki kişi yakın yürüdü, ikincisi
  kart okutmadı = piggyback" vs "biri kapıyı tuttu" vs "kart elden ele verildi".
- **Vizyon:** **turnikeyi kaldıran** kamera+kart füzyonu; ticari/rakip seviyesinde.
- **Disiplin vurgusu:** bu kamerada VLM **ikincil** — çekirdek sensor-fusion. "VLM'i
  zorlamadım, yalnız ihlali anlattırdım" hikâyesi bizzat kıdem sinyali.
- **Kapsam dışı:** yüz-kart eşleşmesi (CompreFace) — KVKK-ağır, demoda yok.
- **Video:** mevcut yoklama-masası videosu (kullanıcıda var).

## 5. Cross-camera handoff — tek mekanizma, iki varlık

Tır (1→2) ve kişi (3→4) **aynı M8.2 desenini** paylaşır:
- `camera_topology` — hangi kamera hangisine besler.
- Zaman penceresi + komşuluk + saat-kayması payı.
- **İmza:** tır = renk+dorse; kişi = spatial-temporal (görünüm-Re-ID **yok**).
- **Belirsizlik kuralı** (Appendix A): aynı anda 2 benzer tır/kişi → "belirsiz" +
  işaretle, uydurma.

Tek kod, iki varlık tipi → mühendislik ekonomisi. Portföyde handoff'u **iki farklı
varlıkta** göstermek tek başına güçlü bir mimari hikâye.

## 6. VLM kullanım disiplini (özet)

| Kamera | VLM | Neden |
|---|---|---|
| 1 | ✅ mevcut | tır kimlik (renk/dorse) |
| 2 | ✅ yeni | yük envanteri + anomali (sayım Frigate'in) |
| 3 | ○ opsiyonel | grounded narrative |
| 4 | ❌ | eşleştirme = aritmetik/spatial-temporal |
| 5 | ✅ istisnada | ihlal-anlatıcı (çekirdek Frigate+kart) |

Mesaj: **VLM hak ettiği yerde; sayım/eşleştirme/mutabakat ölçülen tarafta.**

## 7. Açık kararlar & riskler (build öncesi çözülecek)

1. **Palet tespiti** — "palet" COCO'da **yok** (truck vardı, label 7). Seçenekler:
   (a) custom YOLO (eğitim verisi + iş), (b) COCO-proxy (forklift/kişi-taşıma sayımı),
   (c) tek-kare VLM-doğrulama + Frigate çapraz kontrol. **Build öncesi karar.**
2. **Tır eşzamanlılığı** — tek-tır (zaman penceresi yeter, basit) vs çoklu-tır (imza
   zorunlu + belirsizlik kuralı, iddialı). Demo hangisi için kurulacak?
3. **Forklift-yakınlık** — Frigate real-time (ÖLÇÜLEN); VLM yalnız rapora not düşer.
4. **VLM-sayım yasak** — hiçbir yerde (palet, imza, kişi). Sayım = Frigate/kart.
5. **Yüz tanıma kapsam dışı** — CompreFace yüz-kart eşleşmesi KVKK-ağır → demoda yok.
6. **KVKK** — isim/plaka okunmaz; görüntü tesisten çıkmaz; saklama/profilleme Appendix A.

## 8. Faz eşleme

- Demo = **M8.1** (per-kamera VLM rapor: kamera 2 unload, opsiyonel 3) +
  **M8.2** (handoff: tır 1→2, kişi 3→4).
- **Korunur:** M3 truck akışı (kamera 1 = onun gerçek evi), M7 alarmlar
  (kamera/Frigate/disk offline).
- Erişim mutabakatı (kamera 5) = yeni bir sensor-fusion dilimi (kart sistemi
  entegrasyonu gerektirir).

## 9. Build sırası

**0. Önce görüntüler (kullanıcı):** her senaryo için uygun demo videosu **oluştur veya
mevcutlardan belirle** → MediaMTX ile yayınla. Build, gerçek senaryo görüntüsü olmadan
başlamaz — senaryo videosu kontratın bir parçasıdır.

Sonra (öneri):
1. **Kamera 2 (unload envanteri)** — en güçlü, en bağımsız dilim; palet-tespiti
   kararını (madde 7.1) erken zorlar.
2. **Kamera 1 ile birleştir** — tır lifecycle birleşik raporu (handoff'un ilk örneği).
3. **Kişi handoff (3→4)** — kullanıcı videoları hazır olunca; M8.2 handoff motoru.
4. **Kamera 5 mutabakat** — kart sistemi entegrasyonu gerektirir (en sona).

Her dilim: Frigate config + bridge handler + VLM şema/prompt + DB + Grafana + test +
çok-geçişli adversarial review (M7'deki gibi).
