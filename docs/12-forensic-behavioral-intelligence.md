# 12 · Adli Davranış Zekası (Forensic Behavioral Intelligence)

> **Durum: tasarım spec'i (planlı, M8 önerisi).** Bu doküman aspirasyonel değil; mevcut koda **hizalı** yazıldı. Her bileşen "VAR (yeniden kullanılır)" veya "YENİ (build edilir)" diye işaretlidir. Henüz implement edilmemiş kısımlar `planlı` etiketlidir.

## 12.1 Tek cümlelik iddia

> ai_nvr olayı *tespit* etmez, **açıklar** — ve **gördüğü ile çıkardığını ayırarak** açıklar.

İzinsiz/yetkisiz bir kişi bir alana girdiğinde, çıkışından kısa süre (saniyeler–~1 dk) sonra; ne kadar kaldığını, ne yaptığını ve (varsa) komşu kameradan ne tarafa gittiğini anlatan **adli olay raporu** üretilir. Rapor iki bloğa ayrılır: **ÖLÇÜLEN** (timestamp/diff/detection kaynaklı, kesin) ve **ÇIKARSANAN** (VLM kaynaklı, belirsizlik işaretli).

Bu özellik mevcut "ilk-giriş alarmı"nın (bkz `docs/04-zone-rules.md`) üstüne bir **açıklama katmanı**dır; tır/dorse renk analizi (`docs/06-llm-strategy.md`) ile aynı hibrit deseni izler: ucuz CPU tespiti her şeyi tarar, VLM yalnız semantik gereken yerde devreye girer.

## 12.2 Kapsam ve sınırlar (non-goals)

Manşet "adli davranış zekası" şunları **taahhüt eder** ve şunları **dışarıda bırakır** — overclaim, iddianın kendisinden daha çok zarar verir.

| Taahhüt | NON-GOAL (yapmaz / iddia etmez) |
|---|---|
| Olaydan sonra zengin, sorgulanabilir açıklayıcı rapor | Gerçek-zamanlı otomatik savunma/müdahale (sistem güvenlik **izlemesi** yapar, otonom müdahale **etmez**) |
| 2. kameraya **spatial-temporal handoff** (zaman + topoloji) | Görünüm-tabanlı robust cross-camera **Re-ID** (implement edilmedikçe "Re-ID" denmez) |
| VLM'e **değişim-tetikli birkaç keyframe** | VLM'e 5fps ham akış (maliyet wedge'ini çökertir — bkz 12.7) |
| Çıkarımları **belirsizlik işaretiyle** sunmak | VLM tahminlerini kesin fact gibi sunmak (KILL-SHOT: confabulation) |
| İngestion: deterministik pipeline + tek VLM çağrısı | İngestion'da agentic AI (agentic yalnız **sorgu zamanına** ait — bkz 12.12) |

Gecikme bu senaryoda **kusur değil**: kullanım senaryosu ofis/depo operasyonel görünürlüğüdür; olayı 30sn–2dk sonra öğrenmek fazlasıyla zamanındadır (gerekçe: `docs/06`, `docs/07`).

## 12.3 Algı substratı: Frigate ne görebilir? (yetenek vs izlenen)

"ÖLÇÜLEN" bloğunun tavanı, Frigate'in nesne tespitidir — ne kadar sınıf görebiliyorsak o kadar şeyi sayısal dayanaklayabiliriz. **İki katmanı karıştırmamak şart:**

**(A) Yetenek.** Frigate'in default modeli (OpenVINO SSDLite MobileNet v2, COCO labelmap) aşağıdaki nesne sınıflarını **algılayabilir**. Ham labelmap 90 isim içerir; pratikte üretilmeyen ~10 "paper" kategorisi (street sign, hat, shoe, eye glasses, plate, mirror, window, desk, door, blender, hair brush) çıkarılınca **~80 güvenilir sınıf** kalır:

| Kategori | Nesneler (Frigate default / COCO) |
|---|---|
| İnsan | **person** |
| Araçlar | bicycle, car, motorcycle, airplane, bus, train, **truck**, boat |
| Sokak/trafik | traffic light, fire hydrant, stop sign, parking meter, bench |
| Hayvanlar | bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe |
| Kişisel eşya / çanta | **backpack**, umbrella, **handbag**, tie, **suitcase** |
| Spor | frisbee, skis, snowboard, sports ball, kite, baseball bat, baseball glove, skateboard, surfboard, tennis racket |
| Mutfak / yiyecek | **bottle**, wine glass, **cup**, fork, knife, spoon, bowl, banana, apple, sandwich, orange, broccoli, carrot, hot dog, pizza, donut, cake |
| Mobilya | chair, couch, potted plant, bed, dining table, toilet |
| Elektronik / ofis | tv, **laptop**, mouse, remote, **keyboard**, **cell phone** |
| Ev aletleri | microwave, oven, toaster, sink, refrigerator |
| Diğer ev eşyaları | **book**, clock, vase, scissors, teddy bear, hair drier, toothbrush |

> Davranış zekası için **kalın** sınıflar en alakalısı: person, laptop, backpack, handbag, suitcase, cell phone, keyboard, book, bottle, cup. Yani "masada laptop", "sırt çantası bıraktı", "telefonla oynadı" ifadelerinin ÖLÇÜLEN dayanağı modelde **zaten var** — yeni eğitim gerekmez.

**(B) Şu an izlenen.** Bu projenin `frigate/config.yml`'i (`objects.track`, satır 55-61) şu an **yalnızca 5 sınıfı izler**: `person, car, truck, motorcycle, bicycle`. Geri kalan ~75 sınıf model tarafından **algılanabilir ama izlenmek için config'e eklenmedikçe olay üretmez**. Adli-zeka için bir nesne (ör. `laptop`, `backpack`, `suitcase`) gerektiğinde **tek satır config** ile eklenir.

> **Gotcha — truck→car remap:** Frigate'in default labelmap'i COCO index 7'yi (`truck`) varsayılan olarak **`car`'a remap eder** (tüm büyük araçlar müdahalesiz `car` görünür). Bu repo bunu **bilinçle geri alır** (`frigate/config.yml:33-35`, `model.labelmap → 7: truck`) ki tır/renk analizi ayrı `truck` etiketi alsın. Düz Frigate kurulumunda `truck` ≡ `car`'dır.

> **İki ayrı "track" kavramını karıştırma:** (1) Frigate detektör tracking'i (`frigate/config.yml objects.track`) = modelin hangi sınıfları izleyeceği. (2) Bridge zone kuralı `track_objects` (`bridge/config/zones.yaml`, ör. `[person]`; `zones.py`) = uygulama-seviyesi olay filtresi. Aynı değiller.

**Donanım/model notu:** Liste default CPU/OpenVINO modeli içindir. YOLO/ONNX/RT-DETR = 80-class trimmed COCO; Google Coral/EdgeTPU = donanım limiti nedeniyle **~17 sınıflık alt küme**; custom model = farklı set. İmaj `:stable` (numerik pin yok) — üretimde sabit release tag önerilir.

**Sınır (dürüstlük tezi):** bu liste **ÖLÇÜLEN'in tavanını** çizer — model neyi sayısal *görebilir*. Niyet, etkileşim, sahiplik, kimlik bu listede **yoktur**; onlar daima **ÇIKARSANAN** kalır.

*Kaynak: Frigate "Available Objects" + `labelmap.txt` (docs.frigate.video), adversarial doğrulanmış.*

## 12.4 Grounding contract — ÖLÇÜLEN ≠ ÇIKARSANAN (özün özü)

Manşetin yaşam-ölüm noktası budur. "Laptopla 30-35sn ilgilendi" gibi bir cümleyi VLM kendinden emin biçimde **uydurabilir**; skeptik bir değerlendirici ilk olarak bunu yakalar ve **tek sahte detay tüm raporu** geçersiz kılar. Bu yüzden her rapor alanı bir kaynağa ve bir sınıfa bağlanır:

| Rapor ifadesi | Kaynak | Sınıf |
|---|---|---|
| Süre (giriş–çıkış) | `zone_events` first_entry.ts → exit.ts (`duration_s`) — **VAR** | ÖLÇÜLEN |
| "~2 dk hareketsiz durdu" | `FrigateObject.stationary` + box hareketsizliği — **VAR** | ÖLÇÜLEN (hareketsizlik) |
| "Masaya bir nesne bıraktı" | masa **ROI** + before/after frame diff (nesne kalıcılığı) — **YENİ** | ÖLÇÜLEN (nesne kaldı) |
| "Laptopla ~30sn ilgilendi" | person bbox ∩ `laptop` bbox örtüşme süresi (laptop = COCO sınıfı) — **YENİ** | ÖLÇÜLEN (örtüşme) + ÇIKARSANAN ("ilgilenme") |
| "Bıraktığı şey muhtemelen bir belge" | VLM keyframe yorumu — **YENİ** | ÇIKARSANAN (confidence'lı) |
| Handoff: "doğu yönüne gitti" | exit camA.ts + entry camB.ts + topoloji — **YENİ** | ÖLÇÜLEN (zaman+kamera) + ÇIKARSANAN ("aynı kişi") |

**İki ölçüm mekanizması, doğru yerde (12.3'ten):**
- **Nesne-nesne örtüşmesi** (person ∩ laptop/backpack/suitcase) → güvenilir algılanan COCO sınıfları için; ilgili sınıf `objects.track`'e eklenince **Frigate-native ÖLÇÜLEN** olur. *(Laptop şu an izlenmiyor — M8.1'de `objects.track`'e eklenecek, bkz 12.12.)*
- **ROI + frame-diff** → yüzey/alan ("masa") ve "geride bırakılan nesne" için; çünkü genel ofis masası güvenilir bir COCO sınıfı değildir (`desk` zayıf, çıkarıldı). Sabit bölge + diff daha sağlamdır.

**İlke:** VLM'e "masaya ne bıraktı?" diye **sorma** — diff/detection nesnenin varlığını/örtüşmeyi tespit etsin (ÖLÇÜLEN), VLM yalnız onu **adlandırsın/yorumlasın** (ÇIKARSANAN). Süre VLM tahmininden değil, detection timestamp'inden gelir.

**Birleştirici tez:** ürünün güvenilirliği = ölçülen/çıkarsanan ayrımının dürüstlüğü. Bu, projenin konumlandırma tezindeki dürüstlük ilkesinin (bkz `docs/06`, `docs/07`) fraktalıdır.

## 12.5 Olay raporu şeması

İnsan-okur çıktı (alarm/panel) iki-bloklu:

```
OLAY #1473 · Toplantı Odası · 14:02:11–14:05:36

[ÖLÇÜLEN]
• Süre: 3 dk 25 sn  (giriş/çıkış detection)
• ~2 dk hareketsiz  (stationary)
• Masada yeni nesne kaldı  (ROI + before/after diff, conf 0.91)
• Laptop ile 32 sn bbox örtüşmesi  (person ∩ laptop)

[ÇIKARSANAN — VLM, belirsiz]
• "Muhtemelen masaya bir belge bıraktı"  (orta güven)
• "Laptopla etkileşmiş olabilir; ekran açıldı mı doğrulanamadı"
• "~2 dk hareketsiz → bekleme/gözlem olabilir"

[HANDOFF]
• 14:05:38 koridor kamerası: doğu yönü  (çıkış +2 sn, spatial-temporal eşleşme)
```

Alarm teslimatı: kısa özet (1 cümle) mevcut Dahua/DMSS external alarm **description** alanına gider (`dahua.py` — **VAR**); tam rapor DB'de saklanır ve panelden açılır.

## 12.6 Pipeline / veri akışı (mevcut mimariye hizalı)

```
Frigate MQTT event ──▶ Bridge (mqtt.py/events.py — VAR)
   │
   ├─ Zone state machine (zones.py — VAR)
   │     first_entry ──▶ occupancy session başlat (session_id) [YENİ]
   │     occupancy süresince ──▶ değişim-tetikli keyframe örnekle [YENİ]
   │     exit/timeout ──▶ session kapat; duration_s (VAR) + keyframe seti hazır
   │
   ├─ Grounding adımı [YENİ]  (ÖLÇÜLEN blok)
   │     • masa ROI before/after frame diff (nesne kalıcılığı)
   │     • person ∩ obje (laptop vb.) bbox örtüşme süresi  [obje objects.track'te]
   │     • stationary toplamı (VAR sinyal)
   │
   ├─ VLM narrative çağrısı (llm.py — provider switch VAR)  (ÇIKARSANAN blok)
   │     call_type="behavior_narrative"; input=keyframe seti + ÖLÇÜLEN faktlar
   │     output: per-claim çıkarım + confidence + belirsizlik işareti
   │     → llm_usage'a token/latency/maliyet (VAR tablo)
   │
   ├─ Handoff eşleştirme [YENİ]
   │     exit(camA) ↔ sonraki first_entry(camB), Δt < pencere + topoloji
   │
   ├─ Rapor birleştir (ÖLÇÜLEN + ÇIKARSANAN + HANDOFF) [YENİ]
   │
   └─ Teslimat: Dahua/DMSS alarm (VAR) + DB sakla (YENİ tablo)
```

Yeniden kullanım oranı yüksek; gerçek yeni kod yüzeyi: keyframe örnekleme, frame diff, narrative VLM şeması, handoff eşleştirme, rapor tablosu.

## 12.7 Maliyet kalibrasyonu (wedge'i koru)

- Frigate istenirse 5fps **kaydetsin**; ama VLM'e **5fps gönderme** (300 kare/dk → olay başına token patlar, "Haiku-only ölçeklenmez" duvarına kendin koşarsın).
- VLM girdisi = occupancy başına **değişim-tetikli birkaç keyframe** (ör. sahne değişiminde + giriş/çıkış anı), tipik 3–6 kare; yükseklik `llm_snapshot_max_height` ile sınırlı (VAR, 480px).
- Olay başına **tek** narrative VLM çağrısı (tır analizindeki tek-çağrı deseniyle aynı).
- Nesne-örtüşmesi ve süre **VLM'siz** ölçülür (Frigate detection + timestamp) → token harcamadan ÖLÇÜLEN blok.
- Maliyet/token olay başına `llm_usage`'tan ölçülür (VAR) → 12.9'daki düşüş eğrisinin kanıt kaynağı.

## 12.8 Veri modeli eklemeleri (planlı)

Mevcut tablolarla (`zone_events`, `truck_events`, `llm_usage`, `door_events`) tutarlı; yeni:

- **`occupancy_sessions`** [YENİ]: `id`, `session_id`, `zone`, `camera_id`, `entry_ts`, `exit_ts`, `duration_s`, `stationary_s`, `keyframe_paths JSONB`, `frigate_event_id`.
- **`incident_reports`** [YENİ]: `id`, `session_id FK`, `measured JSONB` (ÖLÇÜLEN faktlar + her birine kaynak), `inferred JSONB` (VLM çıkarımları + per-claim confidence), `summary TEXT`, `llm_usage_id FK` (VAR tabloya), `dahua_alarm_sent` (VAR pattern), `dismissed_at TIMESTAMPTZ` [feedback loop], `feedback TEXT`.
- **`camera_topology`** (config, zones.yaml) [YENİ]: komşuluk + yön etiketi (camA.exit → camB ⇒ "doğu") + makul geçiş süresi penceresi.

`incident_reports.measured` vs `inferred` ayrımı = grounding contract'ın DB'deki karşılığı. `dismissed_at/feedback` = 12.9 döngüsünün girdisi.

## 12.9 Dismissal-learning loop (ürün-tarafı Reflexion — fazlı)

Konumlandırmadaki Reflexion anlatısının (Shinn et al. 2023: act → öz-eleştiri → epizodik hafıza → sonraki denemede daha iyi) **ürün tarafındaki somut karşılığı** budur:

1. Kullanıcı bir alarmı **dismiss eder** (`dismissed_at` + `feedback`).
2. Sistem o paterni episodik hafızaya/RAG'a yazar: "bu imza (ör. her gün 18:00, X bölgesi, ~3dk) iyi huylu".
3. Sonraki benzer olayda: alarmı **bastır** veya pahalı VLM çağrısı yerine **ucuz cache'li açıklama** kullan.

**Kanıt = olay başına token/maliyet eğrisinin zamanla düşüşü** (`llm_usage`'tan ölçülür — VAR). Bu, "daha akıllı/hızlı/az token" iddiasının ölçülebilir halidir.

> **Dikkat (dürüst isimlendirme):** salt "benzer geçmişi retrieve edip few-shot besleme" Reflexion **değil** — o *retrieval-augmented amortization*. Reflexion eşleşmesi spesifik olarak dismissal→stored-feedback→suppress döngüsüdür. Shinn et al. 2023 buna göre, abartmadan cite edilir.

Bu loop **fazlı**: portföyün ilk dilimi raporu üretir; loop ikinci dilimde devreye girer (token eğrisi düşüşü demo'da gösterilir).

## 12.10 Çoklu kamera handoff (spatial-temporal)

Portföy için **2 kamera yeterli**. Mekanizma görünüm-tabanlı Re-ID **değil**:

- `exit(camA, t)` olayı ardından `first_entry(camB, t+Δ)` olayı, `Δ < topoloji penceresi` ise "aynı kişi" **çıkarılır** (ÇIKARSANAN), yön `camera_topology`'den **ölçülür** (ÖLÇÜLEN).
- Çıktı: "çıkış +2sn'de koridor kamerasında doğu yönü".
- Gerçek Re-ID implement edilmediği sürece raporda "muhtemelen aynı kişi" + güven seviyesi kullanılır; "robust Re-ID" iddia edilmez.

## 12.11 Ölçüm / kabul kriterleri

Demo'yu *iddiaya* çeviren metrikler:

- **Grounding doğruluğu**: ÖLÇÜLEN bloktaki faktların doğruluğu (% — kalibrasyon setinde).
- **Confabulation oranı**: işaretsiz/yanlış çıkarım sayısı (hedef ≈ 0; her çıkarım confidence ile işaretli olmalı).
- **Token/olay eğrisi**: zamanla düşüş (dismissal loop etkisi, `llm_usage`).
- **Handoff isabeti**: doğru yön + doğru eşleşme oranı (2-kamera senaryosu).

## 12.12 Fazlandırma (önerilen M8)

1. **M8.1 — Grounded rapor (tek kamera)**: occupancy session + masa ROI before/after diff + `objects.track`'e ofis nesneleri ekle (laptop/backpack/suitcase) + person∩obje örtüşmesi + stationary + tek narrative VLM çağrısı + iki-bloklu rapor + alarm/DB. *Manşeti ayağa kaldıran dilim.*
2. **M8.2 — Handoff (2. kamera)**: camera_topology + spatial-temporal eşleştirme.
3. **M8.3 — Dismissal-learning loop**: feedback yakalama + suppress/cache + token eğrisi ölçümü.
4. **(İleri) Sorgu-zamanı agentic**: "geçen hafta kasaya yaklaşıp oyalanan herkesi bul" — episodik hafıza üzerinde çok-adımlı sorgu. Manşet değil, "ileri seviye".

---

İlgili: `docs/04-zone-rules.md` (state machine), `docs/06-llm-strategy.md` (VLM deseni), `docs/07-cost-analysis.md` (wedge), `docs/10-why-frigate.md` (hibrit gerekçe), `docs/15-adaptive-capture.md` (uyarlanabilir yakalama) + `docs/16-qr-entrance-camera.md` (QR giriş lens/kimlik — M8 uzantısı).

---

# Appendix A — Build kontratları (geliştirici)

> **Buradan itibarısı geliştirici içindir.** Outward okur §12.12'de durabilir. Bu ek, §12.1–12.12'deki tasarım tezini **build edilebilir kontratlara** (DDL, VLM şeması, grounding algoritmaları, kabul kriterleri) çevirir. İçerik üç adversarial geçişten süzülmüştür: **(1) red-team** (anti-confab grounding sözleşmesine saldırı), **(2) completeness** (bir geliştiricinin M8'i implement ederken çarpacağı kenar durumlar/eksikler), **(3) consistency** (gerçek koda — `db.py`/`llm.py`/`events.py`/alembic/`frigate/config.yml` — sadakat). Her kontrat **mevcut koda hizalı**; satır referansları bu repo'nun `main`'ine (commit `2c05061`) göredir.
>
> **Statü:** M8 önerisi. Hiçbir kod henüz yazılmadı; bu ek "ne yazılacağının" sözleşmesidir, "yazıldı" iddiası değil.

## A.0 — Üç geçişin zorladığı yük-taşıyan kararlar

Red-team verdict'i nettir: tasarım naif "VLM'e sahneyi anlattır"dan **maddi olarak güçlü** ama §12.11'in "confabulation ≈ 0" hedefini **taslak haliyle tutturmuyordu**. Aşağıdaki kararlar bu boşlukları kapatır; her biri ek içinde işlenir.

| # | Karar | Hangi geçiş | Neden (kısaca) |
|---|---|---|---|
| 1 | **Üçüncü sınıf: TÜRETİLMİŞ** (ÖLÇÜLEN ve ÇIKARSANAN arasına) | red-team | ROI-diff booleanı / detektör-skoruyla geçitlenmiş "nesne var" eşik üstü gürültüden türetilir; `duration_s` gibi kesin **değildir**. İkisini aynı `MEASURED` etiketiyle render etmek operatöre yanlış kesinlik verir → A.1. |
| 2 | **`summary` üretilmez, türetilir** | red-team | İnsan/Dahua'nın gördüğü tek alan `summary`'ydi ve sözleşme uygulanmayan tek alandı. Artık writer tarafında ÖLÇÜLEN/TÜRETİLMİŞ + en yüksek-güvenli **işaretli** claim'den **deterministik** kurulur → A.4. |
| 3 | **marker↔confidence tutarlılık bantları + alarm tabanı** | red-team | `muhtemelen` + `confidence 0.97` şemaca kabul ediliyordu (çelişki). Validator bantları + `confidence < 0.3` → yalnız-DB → A.4. |
| 4 | **kimlik/niyet promptla değil, kodla yasak** | red-team | 7B yerel VLM promptu rutin ihlal eder; işaretli bir niyet claim'i hâlâ niyet iddiasıdır. Lexicon reject + kapalı `subject` enum → A.4. |
| 5 | **Provider-seviyesi zorlama**: `extra='forbid'` + Ollama'ya gerçek JSON Schema + numeric-scrub | red-team | `format:"json"` yalnız geçerli JSON zorlar, **şemayı değil**. `extra='ignore'` off-contract alanı sessizce yutar → A.4. |
| 6 | **`same_person` booleanı kaldırıldı** | red-team | `true` boolean, kardeş `class:INFERRED` etiketine rağmen **fact gibi okunur**. Yalnız `same_person_confidence` saklanır → A.6. |
| 7 | **Sessionization kararı**: M8.1 = **per-ZONE** oturum, tek-occupant; çoklu-occupant → atıf bastırılır | completeness | `zones.py` state machine **per-zone**'dur (tek `_state`, `_active_ids` seti); per-person oturum kodda **yoktur**. En büyük boşluk → A.2. |
| 8 | **PII / KVKK-GDPR saklama + profilleme** | completeness | M8, kimliklenebilir kişiler hakkında **serbest-metin davranış çıkarımı** ve uzun-vadeli **imza profili** ekler; repo'nun gizlilik tezine aykırı, sıfır saklama tasarımı vardı → A.8. |
| 9 | **Degraded rapor yolu** (VLM/keyframe yokken ÖLÇÜLEN-only) | completeness | `insert_incident_report` hem measured hem inferred ister; VLM hata yolu yarı-telliydi. Sentinel + deterministik özet → A.7. |
| 10 | **Idempotency**: UNIQUE kısıtları + deterministik `session_id` + idempotent alarm | completeness | Restart/replay aynı event'i yeniden açıp **çift alarm + çift LLM maliyeti** üretir → A.7. |
| 11 | **ROI BEFORE-frame kaynağı kararı** | completeness | `record.enabled=false` → tarihsel kare API'si yok; `_handle_first_entry` kişi zaten karedeyken ateşler. Temiz BEFORE karesi için EMPTY-state cache → A.5. |
| 12 | **Çoklu-occupant guard, own-item dürüstlüğü, zero-keyframe, handoff belirsizliği, saat kayması, `active_hours`, `stationary_s` toplama** | completeness | Her biri "build eden çarpacak" — A.5/A.6/A.7. |
| 13 | **Consistency düzeltmeleri**: `dahua_` token'ı korunur, kanonik claim şekli `{text,confidence,uncertainty_marker}`, uydurma `anthropic elif` kaldırılır, `duration_s REAL` gerekçelenir, native-kolon index yeni-konvansiyon, `ovl_pair_dt_s` | consistency | Gerçek koda birebir sadakat → ilgili A bölümleri. |

---

## A.1 — Üç sınıflı grounding: ÖLÇÜLEN / TÜRETİLMİŞ / ÇIKARSANAN

§12.4 iki sınıf kurar (ÖLÇÜLEN / ÇIKARSANAN). Build için **üç** sınıf gerekir — çünkü ÖLÇÜLEN bloğunun içine **eşik-üstü türetilmiş** faktlar sızıyordu (`"masada nesne kaldı", conf 0.91` ve `bbox örtüşmesi`). Bunlar `duration_s` (detection ateşlediyse yanlış olamaz) ile **aynı kesinlikte değildir**; gürültülü bir sinyal üzerinde eşiktir.

| Sınıf | Tanım | Örnekler | Render kuralı |
|---|---|---|---|
| **ÖLÇÜLEN** | Detection ateşlediyse yanlış olamayan timestamp / süre / geometri | `duration_s`, `stationary_s` (toplam), ham bbox örtüşme saniyesi/oranı, frame_time | Mutlak; eşik gösterilmez |
| **TÜRETİLMİŞ** | Doğruluğu gürültülü sinyal üzerinde bir **eşiğe** bağlı fakt | ROI-diff "nesne kaldı" booleanı, detektör-skoruyla geçitlenmiş "laptop var" | **Eşik + sinyal marjı görünür** render: `ROI değişti: diff 0.31 / eşik 0.12 (blob 0.04)`; gürültü vakalarında **çekimser kal** (hiçbir şey yayma) |
| **ÇIKARSANAN** | VLM semantik yorumu | "muhtemelen belge bıraktı", "ilgilenmiş olabilir" | Daima `confidence` + `uncertainty_marker` |

**Yeni invariant'lar:**
- `class='MEASURED'` **yalnızca** detection ateşlediğinde doğru olan timestamp/süre/geometri içindir.
- COCO nesne varlığı (örtüşme) bir **TÜRETİLMİŞ** fakttır ve detektör skorunu fakt'ın parçası olarak taşır (laptop 0.87 → kapalı bir klasör de olabilir).
- ROI-diff boolean'ı, Algoritma 3'ün saydığı kamera-titremesi/yaygın-değişim vakalarında **`true` üretmez → çekimser kalır** (yanlış `MEASURED true` değil).
- §12.5 raporu üç-bloklu olur: `[ÖLÇÜLEN] / [TÜRETİLMİŞ] / [ÇIKARSANAN] / [HANDOFF]`. DB'de üç ayrı JSONB: `measured` / `derived` / `inferred` (A.3). **§12.5'teki örnek iki-bloklu haliyle bu kontrattan ÖNCEsini gösterir** — oradaki "Masada yeni nesne kaldı (conf 0.91)" ve "Laptop ile 32 sn bbox örtüşmesi" satırları artık `[ÖLÇÜLEN]`'den `[TÜRETİLMİŞ]`'e taşınır.

> **Birleştirici tez korunur:** ürünün güvenilirliği = sınıf ayrımının dürüstlüğü. TÜRETİLMİŞ sınıfı bu dürüstlüğü **artırır** — "eşik üstü bir sinyal" ile "kesin ölçüm"ü operatöre ayrı gösterir.

---

## A.2 — Sessionization & subject seçimi (M8.1 kararı)

**Yük-taşıyan boşluk (completeness CRIT):** tüm M8 tasarımı **per-PERSON occupancy oturumu** (entry/exit/duration/stationary/keyframe seti per özne) varsayar, ama mevcut zone state machine **per-ZONE**'dur: `zones.py` tek `_state`, tek `_since`, tek `_last_seen`, ve bireysel zamanlanmayan bir `_active_ids` **seti** tutar. `EMPTY→OCCUPIED` yalnız **ilk** girende ateşler; sonraki girenler sessiz heartbeat'tir. Çıkıştaki `duration_s` = zone'un **herhangi biri** tarafından dolu kaldığı süre, herhangi tek kişinin değil. Yani "bir kişinin giriş→çıkış oturumu" kodda **yoktur**.

**Karar — M8.1 = per-ZONE oturum (açık basitleştirme):**
- Bir oturum = bir `EMPTY→OCCUPIED→EMPTY` döngüsü.
- **Özne** = döngü boyunca en yüksek-skorlu `person` event_id'si (`event.score`, events.py:29) → `occupancy_sessions.subject_event_id`.
- `entry_ts` = ilk girenin ts'i, `exit_ts` = zone boşaldığı ts (mevcut `_handle_exit`).
- **Çoklu-occupant** (döngü sırasında herhangi an >1 eşzamanlı `person`): `multi_occupant=true` işaretlenir ve **per-kişi atıf YAPILMAZ** (A.5 guard). "En yüksek-skorlu özne" sezgisi bir nesne-kaldı/örtüşme faktını asla spesifik kişiye **atfetmez**.
- `ZoneRules.max_occupants_for_report` (default 1): aşılırsa rapor yalnız düşük-güvenli "çoklu kişi, atıf yapılamaz" ÖLÇÜLEN kaydı üretir.

**Deferred (M8.1+):** gerçek per-kişi oturum için Frigate tracking-id yaşam döngüsüne (`new→update→end`, events.py) bağlı, zone machine'den bağımsız bir per-event_id tracker. M8.1 bunu **kapsam dışı** bırakır ve §12.2 non-goal'a "co-occupancy altında per-kişi atıf" eklenir.

> Bu karar `occupancy_sessions` şemasına yazılır: `open_occupancy_session(zone, camera_id, entry_ts, subject_event_id, ...)` — hangi modelin kullanıldığı satır seviyesinde kayıtlıdır.

---

## A.3 — Veri modeli (alembic `0005`)

> ⚠ **Migration no güncellendi:** 0001–0004 alındı (M1–M7; `0003`=disk_status, `0004`=service_status). M8 tabloları (`occupancy_sessions`/`incident_reports`/`camera_topology`) henüz **YOK** → ilk boş slot **`0005`** (M8.1'de oluşturulur).

Konvansiyon: raw `op.execute` SQL (0001/0002 deseni), `BIGSERIAL PRIMARY KEY`, `metadata JSONB DEFAULT '{}'::jsonb`, `idx_<table>_<cols>` (ts DESC), `downgrade` FK-sırasıyla `DROP TABLE IF EXISTS`.

**Consistency notları (gerçek koda hizalı):**
- `door_events` süreyi `duration_ms INT` (0001:48) tutar; biz `occupancy_sessions.duration_s REAL` kullanıyoruz. **Gerekçe (docstring'e yazılır):** adli süreler saniye–dakika ölçeğindedir, alt-saniye hassasiyeti anlamsız; `REAL`, score/güven `REAL` deseniyle (0001:29,94) tutarlı. `door_events` ms'i özellikle alt-saniye kapı-açık zamanlaması içindir, burada geçerli değil. (Δt handoff penceresi ayrı: ts kolonları `TIMESTAMPTZ(3)`, 0001:46-47 deseni.)
- `frigate_event_id` üzerinde **native kolon + düz index** — bu **yeni bir konvansiyon**, 0002'nin JSONB expression-index deseni (`(metadata->>'frigate_event_id')`, 0002:28-29) **değil**. Native olduğu için düz index yeterli.
- Alarm kolonları `dahua_` token'ını **korur** (`dahua_alarm_sent`, `dahua_alarm_retry_count`) — `zone_events` + `db.py:119,127` deseniyle birebir.

```sql
-- =====================================================================
-- occupancy_sessions — bir zone-occupancy döngüsü (A.2: per-zone, tek özne)
-- =====================================================================
CREATE TABLE occupancy_sessions (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE,          -- DETERMINISTIK: frigate_event_id'den türet → replay çarpışır (idempotency, A.7)
    zone TEXT NOT NULL,
    camera_id TEXT NOT NULL,
    subject_event_id TEXT,                    -- A.2: döngünün en yüksek-skorlu person id'si
    entry_ts TIMESTAMPTZ(3) NOT NULL,         -- ÖLÇÜLEN
    exit_ts TIMESTAMPTZ(3),                   -- açıkken NULL
    duration_s REAL,                          -- ÖLÇÜLEN; açıkken NULL (gerekçe yukarıda)
    stationary_s REAL,                        -- ÖLÇÜLEN; A.5 Alg-4 ile toplanır
    keyframe_paths JSONB NOT NULL DEFAULT '[]'::jsonb,  -- değişim-tetikli keyframe yolları (§12.6)
    multi_occupant BOOLEAN NOT NULL DEFAULT FALSE,      -- A.2 guard
    status TEXT NOT NULL DEFAULT 'open',      -- open | closed | truncated_by_restart (A.7)
    frigate_event_id TEXT,
    expires_at TIMESTAMPTZ,                   -- A.8 saklama (purge cron anahtarı)
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_occupancy_sessions_zone_ts ON occupancy_sessions (zone, entry_ts DESC);
CREATE INDEX idx_occupancy_sessions_open ON occupancy_sessions (camera_id, entry_ts DESC)
    WHERE exit_ts IS NULL;                    -- A.7 stale-open sweeper ucuz tarar
CREATE INDEX idx_occupancy_sessions_frigate_event_id ON occupancy_sessions (frigate_event_id);  -- native kolon, düz index (yeni konvansiyon)

-- =====================================================================
-- incident_reports — üç-bloklu grounding (A.1) + dismissal loop + idempotency
-- =====================================================================
CREATE TABLE incident_reports (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE           -- A.7: M8.1 tek-rapor-per-session; çift alarm engellenir
        REFERENCES occupancy_sessions (session_id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    summary TEXT,                             -- A.4: DETERMINISTIK türetilir (VLM yazmaz), Dahua description'a gider
    measured JSONB NOT NULL DEFAULT '{}'::jsonb,  -- ÖLÇÜLEN (A.1)
    derived  JSONB NOT NULL DEFAULT '{}'::jsonb,  -- TÜRETİLMİŞ (A.1 — yeni blok)
    inferred JSONB NOT NULL DEFAULT '{}'::jsonb,  -- ÇIKARSANAN (VLM, per-claim conf+marker)
    handoff  JSONB NOT NULL DEFAULT '{}'::jsonb,  -- §12.10 / A.6 (same_person boolean YOK)
    vlm_status TEXT NOT NULL DEFAULT 'ok',    -- ok | vlm_unavailable | no_keyframes (A.7 degraded)
    llm_usage_id BIGINT REFERENCES llm_usage (id) ON DELETE SET NULL,  -- 0001:97 deseni
    dahua_alarm_sent BOOLEAN NOT NULL DEFAULT FALSE,   -- dahua_ token korunur
    dahua_alarm_retry_count INT NOT NULL DEFAULT 0,
    dismissed_at TIMESTAMPTZ,                 -- §12.9 dismissal-learning loop
    feedback TEXT,
    expires_at TIMESTAMPTZ,                   -- A.8 saklama
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_incident_reports_ts ON incident_reports (ts DESC);
CREATE INDEX idx_incident_reports_dismissed ON incident_reports (dismissed_at DESC)
    WHERE dismissed_at IS NOT NULL;

-- =====================================================================
-- camera_topology — handoff komşuluk + yön + makul geçiş penceresi (A.6)
-- =====================================================================
CREATE TABLE camera_topology (
    id BIGSERIAL PRIMARY KEY,
    from_camera_id TEXT NOT NULL,
    to_camera_id TEXT NOT NULL,
    direction TEXT NOT NULL,                  -- ÖLÇÜLEN (topoloji)
    min_transit_s REAL NOT NULL DEFAULT 0,
    max_transit_s REAL NOT NULL,
    skew_tolerance_s REAL NOT NULL DEFAULT 2.0,  -- A.6: kameralar-arası saat kayması payı
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_camera_topology_edge UNIQUE (from_camera_id, to_camera_id)
);
CREATE INDEX idx_camera_topology_from ON camera_topology (from_camera_id) WHERE enabled = TRUE;
```

**`db.py` helper imzaları** (konvansiyon: `async`, `self.pool.acquire()`, `$N` param, `json.dumps(...)+$N::jsonb`, `RETURNING id → int(row["id"])`, structlog `<table>.inserted`):

```python
# ---- occupancy_sessions ----
async def open_occupancy_session(self, session_id, zone, camera_id, entry_ts,
                                 subject_event_id=None, frigate_event_id=None,
                                 metadata=None) -> int: ...
async def close_occupancy_session(self, session_id, exit_ts, duration_s,
                                  stationary_s=None, keyframe_paths=None,
                                  status="closed") -> None: ...
async def get_open_occupancy_session(self, zone) -> dict | None: ...
async def get_last_closed_session(self, camera_id, since) -> dict | None: ...   # handoff exit kaynağı
async def close_stale_open_sessions(self, older_than) -> int: ...               # A.7 restart sweeper

# ---- incident_reports ----
async def insert_incident_report(self, session_id, summary, measured, derived,
                                 inferred, handoff=None, vlm_status="ok",
                                 llm_usage_id=None, metadata=None) -> int: ...   # üç blok ayrı
async def get_incident_report(self, report_id) -> dict | None: ...
async def dismiss_incident_report(self, report_id, feedback=None) -> None: ...
# alarm-tracking: dahua_ token korunur (db.py:119,127 deseni, incident-scoped)
async def mark_incident_dahua_sent(self, report_id) -> None: ...
async def increment_incident_dahua_retry(self, report_id) -> int: ...

# ---- camera_topology ----
async def get_topology_neighbors(self, from_camera_id) -> list[dict]: ...        # to/direction/min,max_transit_s/skew
async def upsert_camera_topology(self, from_camera_id, to_camera_id, direction,
                                 max_transit_s, min_transit_s=0.0,
                                 skew_tolerance_s=2.0, enabled=True) -> None: ... # ON CONFLICT (from,to) DO UPDATE
```

> `insert_llm_usage` (db.py:181-216) **değişmez** — `call_type='behavior_narrative'` generic string olarak girer (`'truck_color'` ile aynı yol).

---

## A.4 — VLM kontratı: `BehaviorNarrative` (anti-confab çekirdek)

Manşetin yaşam-ölüm noktası. **Yapısal kazanım:** ÖLÇÜLEN/TÜRETİLMİŞ faktlar çıktı şemasının **dışında** yaşar (prompt'a bağlam olarak girer) → model bir ölçülen sayıyı tipli bir alana **yazamaz**. Ama red-team üç serbest-metin/skaler kaçağı buldu: `summary`, `confidence` skalerleri, ve hâlâ-serbest `claim.text`. Bunlar kapatılır.

### A.4.1 Şema (drop into `bridge/bridge/llm.py`, `TruckAnalysis`'ten sonra)

Kanonik claim şekli **`{text, confidence, uncertainty_marker}`** (consistency: Draft1'in `uncertainty/grounded_by/class` varyantı değil; Draft4 audit'i bu isimlere hizalanır).

```python
UncertaintyMarker = Literal["muhtemelen", "olabilir", "belirsiz", "dogrulanamadi"]
Subject = Literal["bir kişi", "birden fazla kişi"]   # kimlik yapısal olarak ifade edilemez

class InferredClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")        # off-contract alan = HARD fail (sessiz yutma yok)
    subject: Subject = "bir kişi"                     # kimlik yasak: enum'la zorlanır
    text: str = Field(max_length=240)                # ölçülen sayı/süre TEKRAR edilmez; kimlik/niyet fact değil
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty_marker: UncertaintyMarker
    grounded_by: list[str] = Field(default_factory=list)  # measured/derived fact key'leri (A.4.3 doğrular)

class BehaviorNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[InferredClaim] = Field(default_factory=list, max_length=8)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    visual_limitations: str | None = Field(default=None, max_length=240)  # göremediğin → buraya, claim'e değil
    # NOT: human-facing `summary` BURADA YOK — writer deterministik kurar (A.4.4).

    @model_validator(mode="after")
    def _consistency(self) -> "BehaviorNarrative":
        band = {"belirsiz": 0.4, "dogrulanamadi": 0.4, "olabilir": 0.7, "muhtemelen": 0.8}
        for c in self.claims:
            if c.confidence > band[c.uncertainty_marker]:        # marker↔confidence bandı
                raise ValueError(f"{c.uncertainty_marker} ile confidence {c.confidence} çelişir")
            # "kesin" katmanı YOK by design: en güçlü marker (muhtemelen) bile <= 0.8 → hiçbir claim near-certainty taşımaz
        cap = max((c.confidence for c in self.claims), default=0.3)
        if self.overall_confidence > cap:                        # en iyi claim'inden fazla emin olamazsın
            raise ValueError("overall_confidence > max(claim.confidence)")
        return self
```

**`LLMResult.parsed` union genişletilir** (llm.py:84 yorumu — *"ileride union eklenir"* — bunu yetkilendirir):
```python
parsed: TruckAnalysis | BehaviorNarrative   # call_type'a göre; diğer LLMResult alanları değişmez
```

### A.4.2 Provider-seviyesi zorlama (red-team: `format:"json"` şemayı zorlamaz)
- **`extra='forbid'`** (yukarıda) — `zone_config.py:22`'nin güvenlik-kritik config deseniyle aynı. Off-contract alan görünür hata olur, sessizce yutulmaz.
- **Ollama**: `format` parametresine string `"json"` yerine **gerçek `BehaviorNarrative` JSON Schema dict'i** geçilir (Ollama 0.5+ structured outputs) → enum/required decode anında zorlanır (kurulu Ollama sürümünde doğrulanacak, A.10), yalnız post-hoc değil.
- **`build_llm_client` (llm.py:205-212) DEĞİŞMEZ** — `ollama if` → doğrudan `raise ValueError`. Taslaktaki yorumlu `anthropic elif` **uydurmaydı, eklenmez** (consistency). Anthropic yalnız prozada "planlı": indiğinde aynı JSON Schema'yı **tool `input_schema`** olarak kullanır (forced structured output) + system-prompt cache → `cached_input_tokens>0`, `cost_usd` hesaplanır (§12.9 token eğrisi). Aynı `BehaviorNarrative.model_validate` `tool_use.input`'a uygulanır → `LLMResult` provider-agnostik kalır.

### A.4.3 Writer-tarafı sözleşme zorlaması (prompt değil, kod)
`incidents.py` (trucks.py muadili) **persist'ten önce** her `claim.text` + türetilen `summary` üzerinde:
1. **numeric-scrub**: `\d+\s*(sn|saniye|dk|dakika|m|cm|%)` gibi ölçülen-sayı tekrarı taşıyan claim → reddet veya rakamı strip + `confidence` düşür. (ÖLÇÜLEN sayı zaten kesin; VLM'in tekrarı sızıntıdır.)
2. **kimlik/niyet lexicon reject**: kara liste — kimlik (`hırsız/çalışan/yetkili/yetkisiz/misafir/X kişisi`), niyet/eylem-as-fact (`çaldı/sızdırdı/açtı/kırdı/izinsiz girdi`), **sahiplik/şüphe** (`terk edilmiş/şüpheli paket` — A.5 own-item). Hit → claim reddi (retry) **veya** `confidence` hard-cap + `uncertainty_marker='belirsiz'`.
3. **`grounded_by` referans bütünlüğü**: somut eylem/nesne içeren her claim için `grounded_by` **zorunlu ve boş-değil**; her key gerçek `measured`/`derived` fact key'lerine karşı doğrulanır. Sarkan/uydurma referans → claim reddi veya referans strip + downgrade. Dayanaksız spesifik claim → `dogrulanamadi` + `visual_limitations`'a yönlendir.

### A.4.4 `summary` üretilmez — **deterministik türetilir** (red-team #1 kill-shot)
İnsan/Dahua'nın gördüğü tek alan budur ve VLM'e bırakılamaz. `incident_reports.summary` writer tarafında kurulur:
```
{zone}: bir kişi {duration} ({stationary} hareketsiz). [TÜRETİLMİŞ varsa] Masada nesne değişimi (diff {d}/eşik {t}). Çıkarım: {top_marked_claim.text} ({marker}, güven {conf}).
```
- ÖLÇÜLEN/TÜRETİLMİŞ kısım `incident_reports.measured/derived`'den (kanıtlanır doğru) gelir.
- ÇIKARSANAN kısım yalnız **`confidence ≥ 0.3`** olan en yüksek-güvenli **işaretli** claim'den; altı **yalnız-DB** (alarm description'a girmez).
- VLM'in serbest özeti **yoktur** (şemada `summary` alanı yok, A.4.1) — insan-okur özet daima bu deterministik şablondur.

### A.4.5 Prompt + çağrı (mevcut desene hizalı)
- `BEHAVIOR_NARRATIVE_PROMPT_SYSTEM` (Türkçe, `TRUCK_PROMPT_SYSTEM` yanına): "ÖLÇÜLEN ≠ ÇIKARSANAN; ölçülen sayıyı TEKRAR ETME; kimlik/niyet fact değil; göremediğini `visual_limitations`'a; her cümle işaretli." **Eklenen yasak:** sahiplik/şüphe ("terk edilmiş/şüpheli" — own-item, A.5).
- `OllamaClient.analyze_behavior(keyframe_paths, measured_facts)`: `analyze_truck`'ı 1:1 yansıtır (retry/timeout/`prompt_eval_count`/`eval_count`). Farklar: çoklu `images` dizisi, `measured_facts` prompt'a **nitel kovalarla** (ham sayı değil — "uzun süre kaldı" / "kısa") girer (red-team: bağlamdaki ham sayı tekrar edilir), **`num_predict=1024`** (completeness: 512 zengin sahnede JSON'u kesip parse-fail + retry yakar → en değerli olaylar en çok başarısız olur). `log.warning('llm.attempt_failed')`'a `call_type` **eklenmez** (consistency: analyze_truck llm.py:184-189 omit eder).
- `LLMClient` Protocol'üne `analyze_behavior` eklenir.

---

## A.5 — Grounding algoritmaları (M8.1)

Tasarım sadece mevcut 10 `FrigateObject` alanına dayanır (events.py:29-35): `score, frame_time, current_zones, entered_zones, box=[x,y,w,h]|None, has_snapshot, stationary`. **`velocity/area/motionless_count` yoktur.** **`box=[x,y,w,h]`** → tüm geometri köşeye çevrilir: `x2=x+w, y2=y+h` (`box[2]/box[3]`'ü doğrudan x2/y2 sanmak **bug**'dır — load-bearing).

### Algoritma 1 — Keyframe örnekleme (occupancy başına ≤6 kare)
- **Hook'lar:** ENTRY (`_handle_first_entry`, `entered_zones` truthy), per-update (OCCUPIED heartbeat — bugün boş; değişim-tetik buraya), EXIT (`_handle_exit`, `exit_timeout` sonrası).
- **Kaynak (constraint):** `record.enabled=false` (frigate/config.yml:52-53) → tarihsel kare API'si yok. Örnek = tetik anında `snapshots.fetch_camera_latest(camera)` (snapshots.py:67-80), `event.after.frame_time` ile etiketli (ÖLÇÜLEN). ENTRY/EXIT fallback = `fetch_event_snapshot(event_id, height)` (snapshots.py:34,45 — `has_snapshot=true` olunca garanti).
- **Tetik (hibrit):** zorunlu anlar (ENTRY/EXIT, stationary↔moving edge) + sahne-değişim (centroid yer-değiştirme > `kf_move_frac` *veya* bbox-alan değişimi > `kf_area_frac`) + açlık-önleyici interval tabanı (`kf_min_interval_s`). Cap `kf_max_frames=6`, iki kare arası min `kf_min_gap_s`.
- **Sınır:** seçim ve **neden** seçildiği ÖLÇÜLEN'dir; karelerin VLM'e verilip "ne oluyor" diye yorumlanması ÇIKARSANAN.

### Algoritma 2 — person ∩ obje örtüşmesi (dwell)
- **Önkoşul (tek satır config + A.5 not):** hedef sınıflar `objects.track`'te olmalı (şu an yalnız person/car/truck/motorcycle/bicycle, config.yml:56-61; **laptop/backpack/suitcase yok**). **Completeness uyarısı:** sınıf eklemek CPU-only Frigate'te (640×480@5fps, Coral yok) detection gürültüsü + CPU artırır → watchdog fps'i düşürebilir. **Karar:** sınıf eklemeyi **yalnız forensic kameralara** (per-camera `objects.track` override) ve **`min_score ≥ 0.6` + `min_area`** ile yap; `perf.py` ile fps before/after gate. `ovl_min_score` Frigate person eşiğinin (0.6) **altına** düşürülmez.
- **Geometri:** IoU değil **containment-bias**: `ovr = inter_area / min(area_person, area_object)` — küçük nesne (laptop) büyük person bbox'ı içindeyken ~1.0. ÖLÇÜLEN blokta hem `ovr` (trigger) hem IoU (diagnostic).
- **Dwell:** `frame_time` deltalarından topla; tek boşluğu `ovl_max_gap_s`'te capla (dropout şişirmesin); `ovr ≥ ovl_min_ratio` & aynı zone & skorlar ≥ eşik. `overlap_total_s ≥ ovl_min_duration_s` (default 5s) altı raporlanmaz.
- **Sınır:** "person ∩ laptop 32s (peak 0.78)" ÖLÇÜLEN; "kullandı/açtı/sahibi" ÇIKARSANAN (örtüşme "kullanım"ı asla ölçemez).

### Algoritma 3 — before/after ROI diff ("nesne kaldı") → **TÜRETİLMİŞ** (MEASURED değil)
- **Bağımlılık (load-bearing):** `pyproject.toml`'de numpy/Pillow/opencv **yok**. Yeni opsiyonel grup `forensics = ["pillow>=10.4.0","numpy>=2.0.0"]` (llm/viewer gruplarını yansıt, pyproject.toml:35-44). opencv'den kaçın.
- **BEFORE-frame kararı (completeness #1 doğruluk riski):** `record.enabled=false` + `_handle_first_entry` kişi zaten karedeyken ateşler → temiz pre-entry karesi yok. **Karar:** zone EMPTY iken **per-forensic-camera EMPTY-state frame cache** — düşük frekanslı (30–60s) arka plan poll'u tek cached kareyi günceller, `OCCUPIED`'da silinir; BEFORE karesi ≤60s bayat olabilir (dokümante). (Alternatif: forensic kameralara düşük-fps `record` rolü açıp `/api/<cam>/recordings/<ts>`'den tam-ts kare çek — disk maliyeti A.8'e yazılır.) **Biri seçilmeden Alg-3 ÇALIŞTIRILMAZ** — BEFORE=entry-frame ile "nesne kaldı MEASURED" iddia edilmez.
- **Temiz kaynak (red-team #10, default):** `snapshots.bounding_box=true` + `timestamp=true` (config.yml:46-47) jpg'ye bbox/label/timestamp **basar** → hem VLM bunları "gördüm" diye tekrar eder hem ROI-diff'i tetikler (değişen timestamp bandı = garanti false-positive). Forensic kameralarda **overlay-kapalı temiz kaynak** default; mümkün değilse timestamp bandı + person bbox bölgesi maskelenir.
- **Yöntem:** gri-tonlama → exclusion mask (person bbox + overlay bandı) → `diff = mean(|after-before|)` → karar: `diff ≥ roi_diff_threshold` **VE** değişen-piksel oranı ≥ eşik **VE** blob **kompakt** (gerçek nesne lokal; aydınlatma yaygın → reddet). Kamera-titremesi/yaygın-değişimde **ÇEKİMSER** (false `true` değil).
- **Sınıf:** çıktı **TÜRETİLMİŞ** — "ROI değişti, sinyal-güveni 0.91" eşik/marj görünür render edilir (A.1). VLM yalnız **adlandırır** ("muhtemelen belge", ÇIKARSANAN).
- **Own-item dürüstlüğü (completeness):** ÖLÇÜLEN/TÜRETİLMİŞ fakt = "ROI değişti / yeni lokalize nesne" — **"terk edilmiş/şüpheli" DEĞİL** (o sahiplik+niyet → ÇIKARSANAN, A.4.3 lexicon yasaklar). **İşaretli diff yönü** (eklendi vs kaldırıldı) MEASURED'a yazılır → çoklu-oturum al/bırak en azından görünür olur.

### Algoritma 4 — `stationary_s` toplama (completeness: hesaplama yolu yoktu)
Zone machine `stationary_s`'i **biriktirmiyor**; §12.4/§12.5 ve şema toplam bir değer varsayıyor. **Spec:** özne `event_id` başına, `after.stationary==true` iken `frame_time` deltalarını topla; tek inter-frame boşluğu (örn. 2s) capla (dropout absorbe); `stationary→moving`'de reset. Frigate 0.17'nin 5fps'te yavaş iç hareket için `stationary`'yi güvenilir toggle'ladığı **doğrulanana kadar** `stationary_s` MEASURED blokta kendi güvenilirlik-çekincesini taşır.

### Config anahtarları (`ZoneRules`, zone_config.py:19 — `extra='forbid'` → tanımlı olmalı)
```python
forensic_enabled: bool = False
max_occupants_for_report: int = Field(default=1, ge=1, le=10)        # A.2 guard
min_keyframes: int = Field(default=1, ge=0, le=6)                    # A.7 zero-keyframe
# keyframe
kf_max_frames: int = Field(default=6, ge=1, le=12)
kf_min_interval_s: float = Field(default=20.0, ge=2.0, le=120.0)
kf_min_gap_s: float = Field(default=4.0, ge=0.5, le=30.0)
kf_move_frac: float = Field(default=0.08, ge=0.0, le=1.0)
kf_area_frac: float = Field(default=0.30, ge=0.0, le=2.0)
# overlap
overlap_classes: list[str] = Field(default_factory=lambda: ["laptop", "backpack", "suitcase"])
ovl_min_ratio: float = Field(default=0.15, ge=0.0, le=1.0)
ovl_min_score: float = Field(default=0.6, ge=0.6, le=1.0)            # Frigate person eşiği (0.6) taban — tip-zorlamalı, altına inilemez
ovl_min_duration_s: float = Field(default=5.0, ge=0.0, le=120.0)
ovl_pair_dt_s: float = Field(default=1.0, ge=0.1, le=5.0)            # consistency: _s sonekiyle birleşik isim
ovl_max_gap_s: float = Field(default=2.0, ge=0.2, le=10.0)
# roi diff
roi: list[float] | None = None                                       # [rx1,ry1,rx2,ry2] normalize
roi_diff_threshold: float = Field(default=0.12, ge=0.0, le=1.0)
roi_pixel_delta: int = Field(default=25, ge=1, le=255)
roi_min_changed_frac: float = Field(default=0.04, ge=0.0, le=1.0)
roi_min_blob_frac: float = Field(default=0.01, ge=0.0, le=1.0)
```

---

## A.6 — Çoklu kamera handoff (M8.2)

Mekanizma görünüm-tabanlı Re-ID **değil**: `exit(camA,t)` → `first_entry(camB, t+Δ)`, `Δ ∈ [min_transit_s, max_transit_s]` ise yön topolojiden **ölçülür**, "aynı kişi" **çıkarılır**.

- **`same_person` booleanı KALDIRILDI** (red-team #6): `true` boolean kardeş `class:INFERRED`'e rağmen fact gibi okunur ve bir downstream `if handoff.same_person:` kimliği fact olarak iddia eder. `handoff` JSONB yalnız: `to_camera_id`, `direction` (ÖLÇÜLEN), `delta_s` (ÖLÇÜLEN), **`same_person_confidence` (float)**, `candidate_count`. Render zorunlu işaretle: "muhtemelen aynı kişi, güven 0.7" — asla çıplak `true`.
- **Belirsizlik kuralı (completeness):** Δt penceresinde 0/1/N aday `first_entry` olabilir. **>1 aday → `matched=false`, `same_person_confidence` düşük, `reason='ambiguous_multiple_candidates'`** — bir tanesini seçme. Yalnız pencerede **tam 1** aday varken (ve camA'dan rakip başka exit yokken) `same_person_confidence` yüksek. `candidate_count` MEASURED yazılır. Bu, precision≥0.90 gate'ini ulaşılabilir kılar. (N-to-1 ters durumu da kapsanır.)
- **Saat kayması (completeness):** Δt ms hassasiyetli (`TIMESTAMPTZ(3)`) ama iki timestamp kaynağı var — Frigate `frame_time` (events.py:30) ve bridge host saati (`zones.py` ts injection). **Karar:** handoff Δt için **iki kamerada da AYNI kaynak** kullanılır; NTP senkronu deployment önkoşuludur (`docs/08-operations`'a eklenir); `camera_topology.skew_tolerance_s` pencereye eklenir. Hangi kaynak kullanıldığı handoff MEASURED bloğa yazılır (auditability). (Inject-clock testi kaymayı kapsamaz — çekince dokümante.)
- **Not:** handoff-matcher algoritma artefaktı henüz yok (yalnız DB helper'ları) → M8.2'de yazılacak gerçek boşluk.

---

## A.7 — Degraded yollar, idempotency, alarm geçidi

**VLM hata / zero-keyframe (degraded rapor):** `analyze_behavior` `LLMError` atarsa **veya** keyframe sayısı 0 ise rapor **yine yazılır** ama `inferred = {"claims": [], "status": "vlm_unavailable"}` (veya `no_keyframes`), `vlm_status` kolonu işaretli, `summary` = ÖLÇÜLEN/TÜRETİLMİŞ'ten deterministik şablon (A.4.4 — "...görsel yorum üretilemedi"). Confab audit (A.9) `vlm_status != 'ok'` raporları "her claim işaretli" kuralından **muaf** tutar (boş claims dizisi confabulation değil). `analyze_behavior` boş keyframe'de **exception atmaz**, degraded yola düşer.

**Idempotency (completeness — çift alarm/çift LLM maliyeti):**
- `occupancy_sessions.session_id` **deterministik** `frigate_event_id`'den türetilir → restart/MQTT-replay aynı session'a çarpar (UNIQUE).
- `incident_reports.session_id` **UNIQUE** → M8.1 tek-rapor-per-session.
- Alarm emisyonu idempotent: göndermeden önce `dahua_alarm_sent` kontrol (zones.py pending deseni). **Bridge/Frigate restart zaten raporlanmış session'ı yeniden ALARM ETMEZ.**

**Restart kurtarma (completeness):** `restore_from_db` (zones.py:105-135) yalnız first_entry'i ele alır. Mid-occupancy restart'ta açık session (`exit_ts NULL`), kısmi keyframe seti ve in-memory akümülatörler (overlap/stationary) **kaybolur** (trucks.py `_processed` gibi). **Spec:** `close_stale_open_sessions(older_than)` sweeper (`idx_occupancy_sessions_open`) eski açık session'ları `status='truncated_by_restart'` ile kapatır, **alarm etmez**; restart'ta yeni event işlemeden önce reconcile. Restart-kesintili session = ne persist edildiyse o + ÖLÇÜLEN-only.

**`active_hours` geçidi (completeness — tutarlılık):** bugün `first_entry` yalnız `first_entry_alarm AND is_active AND alert_on_empty_arrival` ile alarmlar (zones.py:197-200); mesai-dışı LOG'lanır, alarmlanmaz. M8 ikinci alarm yolu (`incident_reports.dahua_alarm_sent`) ekler. **Karar:** rapor **her zaman üretilir+saklanır** (adli değer, `zone_events` gibi) ama **Dahua ALARM'ı first_entry ile AYNI `active_hours`/`alert_on_empty_arrival` mantığını uygular** (`_is_within_active_hours` reuse) — iki yol tutarlı. §12.5'e "rapor üretimi ≠ alarm emisyonu; alarm `active_hours`'a uyar" yazılır. (VLM maliyetinin mesai-dışı koşup koşmayacağı ayrı wedge kararı.)

---

## A.8 — Gizlilik / KVKK-GDPR (saklama + profilleme)

> **Completeness CRIT — manşet dürüstlüğü için yük-taşıyan.** Repo'nun tezi "görüntüler tesisi terk etmez" (`docs/02`, `docs/11`) ve snapshot'lar zaten KVKK kişisel veri + saklama politikası gerektirir (`docs/09`). M8 **ekler:** (1) kimliklenebilir kişiler hakkında **serbest-metin davranış çıkarımı** (`incident_reports`), (2) session başına 3–6 **keyframe** (snapshots.py temizlik yapmaz), (3) dismissal-loop'un yinelenen kişilere dair **uzun-vadeli davranış imzası** (RAG/episodik) — sistemdeki **en hassas** artefakt. Davranış çıkarımı bir snapshot'tan KVKK/GDPR açısından **daha** hassastır (profilleme, GDPR Art. 22).

**Kontratlar:**
- **Saklama:** `occupancy_sessions` + `incident_reports`'a `expires_at` (yukarıda); `ts`'e dayalı **purge cron** hem satırları hem `keyframe_paths` **dosyalarını** siler (`docs/08`'deki `find -mtime +90 -delete` deseni). Salt satır silmek yetmez — dosyalar da.
- **Dismissal-loop imzaları kimlik-anahtarlı OLMAZ:** imza = `zone + zaman-kovası + süre` (örn. `zoneB|recurring|~3min`), **kişi-id/yüz değil**. Episodik hafıza KVKK-ilgili profilleme olarak kendi saklamasıyla dokümante.
- **VLM yerel kalır (default):** narrative `Ollama` ile lokal. Anthropic'e geçiş **davranış görüntülerini tesis dışına** gönderir → gizlilik tezini kırar; truck analiziyle **aynı `planlı` çekincesi** ardına geçitlenir (kullanıcı açık opt-in).
- (Bu bölüm geliştirici ek'inde tutuldu; istenirse outward `§12.13` olarak terfi edilebilir — bkz commit notu.)

---

## A.9 — Kabul protokolü (`bridge/bridge/eval.py`)

`perf.py` şeklini yansıtır: `Thresholds` dataclass + IO-suz saf scorer'lar + `CheckResult`/`Verdict` + `make eval` (exit 0/1). Fixtures inject-clock + offline replay (`test_zones.py` deseni) ile canlı Frigate'siz koşar.

| Metrik | Gate | Ölçüm |
|---|---|---|
| Grounding doğruluğu (ÖLÇÜLEN+TÜRETİLMİŞ) | ≥ %98 per-fact; hiçbir `fact_key` < %90 | 2 annotator ham klibe karşı (kappa ≥ 0.8, 3. hakem); 30-olay kalibrasyon |
| Confabulation oranı | ~0 (kalibrasyonda 0 defekt; prod ≤ %2) | **içerik-farkında** audit (aşağı) |
| Token/olay eğrisi | ≥ %30 düşüş, eğim negatif | `llm_usage` `call_type='behavior_narrative'`, **aynı-imza** kohort |
| Handoff eşleşme | precision ≥ 0.90, recall ≥ 0.80 | scripted exit/entry çiftleri (≥25), confusion matrix |
| Handoff yön | ≥ %95 | `camera_topology` ground truth |

**Confabulation audit GENİŞLETİLDİ (red-team #9 — yapısal audit yalın haliyle 5 saldırının 4'ünü kaçırıyordu).** Yalnız "marker var mı" değil, **`summary` + her `claim.text` üzerinde içerik-farkında**: (i) kimlik/niyet lexicon taraması, (ii) rakam/numeric taraması (measured/derived'den kanıtlanır kopyalanmayan her rakam = defekt), (iii) **marker↔confidence bant tutarlılığı**, (iv) `grounded_by` referans bütünlüğü, (v) `overall_confidence ≤ max(claim.confidence)`. **`summary` denetlenen yüzeye dahil.** `vlm_status != 'ok'` raporları muaf (A.7). Ancak böyle §12.11'in "confabulation≈0, %100 makine-denetlenebilir" iddiası savunulabilir.

- **Token eğrisi**: `metadata->>'signature'` damgası (dismissal loop) **şart** — yoksa early/late düşüş "daha az zor vaka" demek olabilir, "loop çalışıyor" değil. `_growth_pct` (perf.py:286-310) en-küçük-kareler eğimi reuse; `growth_pct ≤ -30` gate.
- **Yapısal confab audit + token-curve** ayrıca canlı `llm_usage`/`incident_reports` üzerinde **nightly cron** (perf.py'nin 24s/CI amacı gibi) → prod'da sürekli izlenir; grounding/handoff fixture-set'te release başına.

---

## A.10 — Build öncesi netleşecek açık kararlar

Bunlar taslakların `open_questions`'ından **build kararına terfi edilmesi gereken**, ama bu ek'te tek-doğru-cevabı olmayan kalemler:

1. **`incident_reports.inferred` serileştirme:** `BehaviorNarrative.model_dump()` olduğu gibi mi (claims+overall+visual_limitations) yoksa `summary` zaten deterministik writer'da kurulduğundan inferred yalnız claims mi? (A.4.4 ile çözülüyor ama panel render sözleşmesi netleşmeli.)
2. **qwen2.5vl:7b çoklu-görüntü:** `analyze_behavior` tek `/api/generate`'e 3–6 görüntü yollar; modelin hepsine güvenilir dikkat ettiği **doğrulanmalı** (yoksa keyframe'leri tek montaja birleştir veya kare sayısını düşür).
3. **`stationary` toggle güvenilirliği:** Frigate 0.17, 5fps'te yavaş iç hareket için `stationary`'yi güvenilir mi toggle'lıyor (A.5 Alg-4 doğruluğunu doğrudan etkiler).
4. **Anthropic fiyat tablosu:** `cost_usd` + `cached_input_tokens` "planlı" referanslı ama config'de fiyat tablosu yok (yalnız `llm_monthly_budget_usd`); §12.9 token-eğrisi kanıtı AnthropicClient indiğinde bunun tellenmesine bağlı.
5. **EMPTY-state cache vs düşük-fps record rolü** (A.5 BEFORE-frame): yaklaşım A.5'te **karara bağlandı** (EMPTY-state cache default, record rolü alternatif); açık olan yalnız disk/CPU bütçesine göre ikisi arası **deployment seçimi**.

---

*Bu ek üç adversarial geçişin (red-team / completeness / consistency) bulgularını sentezler. Kaynak workflow çıktısı kalıcı: `handoff-spec-sharpen-output-wt57v47g6.json` (7 ajan, 4 taslak + 3 lens). Manşet/grounding kararları → `docs/12` §12.1–12.4 + portföy konumlandırması.*
