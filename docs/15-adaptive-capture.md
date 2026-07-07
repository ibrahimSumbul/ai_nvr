# 15 — Uyarlanabilir Görüntü Yakalama (ortam-duyarlı QR/kimlik okuma)

> **Statü: M8 tasarım eki — kod YOK.** Bu doküman, QR/kimlik okuma için görüntü-yakalama
> parametrelerinin (shutter/pozlama, gain, IR, profil) **ortama göre otomatik ayarlanmasını**
> bir tasarım kontratı olarak tanımlar. Henüz implement edilmedi; "ne yazılacağının" çerçevesidir.
> QR boyut/blur fiziği ve giriş-kimliği mimarisi için bkz. [`13-portfolio-demo-vision.md`](13-portfolio-demo-vision.md)
> (Kamera 1) ve [`12-forensic-behavioral-intelligence.md`](12-forensic-behavioral-intelligence.md) (grounding kontratı).

## 15.1 Problem

Tek bir sabit shutter/pozlama değeri **ortamlar arası yanlıştır**:
- Gündüz parlak güneş vs gece IR; açık hava vs kapalı dok; yağmur/sis/kar.
- 15 km/h tır için blur'ü dondurmak ~1/1000–1/2000 s ister; ama o hız ışığı 10–20× azaltır
  → zayıf ışıkta gain (ISO) fırlar → gürültü → QR okunmaz. **Fizik sınırı = ışık, compute değil.**
- 10+ kamerayı **elle tek tek ayarlamak ölçeklenmez** ve zamanla kayar (mevsim, gün-içi, lens kiri).

**Kilit ayrım — "AI otomatik ayarlar" ne DEĞİLDİR:** kameraların hazır **auto-exposure (AE)** ve
gündüz/gece IR-cut'ı bunun bir kısmını zaten yapar; bu yeni/AI değildir. Bu tasarımın **eklediği**:
generic "ortalama parlaklık" yerine **göreve-özel (QR-okunabilirliği) kapalı-döngü** optimizasyon —
*ölçülen decode başarısına* göre ayar.

## 15.2 Ölçülen sinyaller (hepsi MEASURED — grounding kontratı)

Hiçbir ayar kararı VLM yargısına dayanmaz; tümü deterministik sinyaller üzerinde:

| Sinyal | Nasıl | Sınıf |
|---|---|---|
| Sahne parlaklığı / histogram (clipping) | ROI'den ortalama luma + doygunluk oranı | ÖLÇÜLEN |
| Gürültü tahmini | düz bölge varyansı / yüksek-ISO işareti | ÖLÇÜLEN |
| Hareket-blur tahmini | kenar keskinliği (Laplacian) + tespit edilen nesne hızı | ÖLÇÜLEN/TÜRETİLMİŞ |
| **QR decode başarı oranı** | son N denemede başarı/başarısız (asıl geri-besleme) | ÖLÇÜLEN |
| Zaman / gün-gece | saat + foto-sensör/luma eşiği | ÖLÇÜLEN |
| Tespit edilen nesne + hız | Frigate (truck event, bbox hızı) | ÖLÇÜLEN |

## 15.3 Kontrol eylemleri

- **Shutter/pozlama** — blur hedefi (≲1 modül) ile ışık tavanı arasında denge.
- **Gain (ISO) tavanı** — gürültü QR'ı bozmadan önce sınırla; tavan dolunca shutter'ı *yavaşlatmak* yerine
  **IR/aydınlatmayı artır** (foton üret, gürültü üretme).
- **IR aydınlatıcı gücü** — gece + mesafeye göre.
- **Gün/gece + hava profilleri** — önceden kalibre edilmiş başlangıç noktaları.
- **Event-tetikli mod** — Frigate **tır algılayınca** kısa-shutter "burst" penceresi (sürekli değil;
  enerji/gürültü bütçesini korur). Kullanıcı isteği: "Frigate truck algıladığında 1/500 s+'e dek dene."

## 15.4 Döngü (Reflexion'a hizalı, ama deterministik karar)

```
ölç (15.2)  →  KARAR [deterministik politika: ışık/blur/gürültü bütçesi]  →  uygula (15.3)
   ▲                                                                              │
   └──────────  gözle: QR decode başarı oranı  ←  (geri-besleme) ←───────────────┘
```

- **Çekirdek politika = kurallar/kontrol döngüsü** (ışık-blur-gürültü bütçe çözümü) — basit, denetlenebilir,
  halüsinasyonsuz. VLM döngüde **yok**.
- **Opsiyonel öğrenen katman (M8.3 dismissal-learning ile aynı omurga):** decode başarısızlıklarından
  zamanla **profil/eşik adaptasyonu** (hangi ortamda hangi başlangıç parametresi işe yaradı) — episodik
  geri-besleme, [`12`](12-forensic-behavioral-intelligence.md) §12.9 Reflexion deseni. Bu katman **abartılmaz**:
  "AI sihirle bilir" değil, "ölçülen sonuçtan öğrenir".

## 15.5 Grounding kontratına bağlanış

- Tüm ayar **kararları** ÖLÇÜLEN sinyaller üzerinde **deterministik** → "VLM'i yalnız hak ettiği yerde"
  tezinin örneği (ayar = mantık; VLM = yalnız ihlal/anomali anlatısı, ayrı yol).
- QR kimliği (sonuç) = **ÖLÇÜLEN** (decode edildi/edilemedi); kapı-atama uygunluğu = lookup + aritmetik.
- Dürüst sınır: **AE foton yaratamaz.** Işık fiziksel taban; uyarlama yalnız *mevcut* ışığı en iyi kullanır.
  Yetersizse çözüm donanım (IR/aydınlatma/WDR), yazılım değil.

## 15.6 Sınırlar & açık iş (build öncesi)

- **Donanım bağımlılığı:** shutter/gain/IR'ı runtime'da programatik değiştirmek kamera-bağımlı (ONVIF
  imaging profilleri / üretici API). Bazı kameralar yalnız AE preset'i verir → o zaman **adanmış sabit-ayar
  ANPR-tarzı giriş kamerası** (sabit hızlı shutter + IR) daha sağlam (bkz. §13 Kamera 1).
- **Kalibrasyon:** profil başlangıçları ve eşikler gerçek sahada ölçülerek kurulur (eval harness deseni,
  [`eval/README.md`](../eval/README.md)).
- **Kapsam:** bu doküman tasarım; M8.1+ build sırasında `frigate/config.yml` rolleri + bridge controller +
  decode-başarı metriği + (opsiyonel) öğrenen katman olarak somutlaşır.

## 15.7 QR veri içeriği — opak token, anlam sunucuda (değişen "key")

**Karar: QR'a bilgi (URL/cümle/manifest) KOYMA; kısa opak bir token koy.** Anlam (kapı, zaman-slotu,
tır kimliği, geçerlilik) sunucu-tarafı **değişebilir eşleme** ile çözülür. QR = sabit *handle*; "key"
(eşleme) değiştikçe **aynı QR farklı anlam** verir.

- **Neden az veri:** kapasite ↑ → QR versiyonu ↑ → modül ↑ → aynı okunabilirlik için fiziksel QR **büyür**
  (10m/15 km/h'te zorlaşır). Kısa ID → V1–V2 (en küçük/sağlam). URL → V3+, cümle → V4+.
- **Varyant A (basit, sağlam):** kalıcı opak ID; rezervasyon tablosu `{id → bugünkü kapı, slot}`. Yeniden-basım
  yok, yazılımdan ata/iptal et.
- **Varyant B (yüksek güvenlik):** sefer-başına **imzalı + süreli** token → replay/klon imkânsız; bedeli her
  sefer yeni QR üretimi. (e-İrsaliye otorite anchor'ı varken **çoğu durumda gereksiz** — bkz.
  [`16-qr-entrance-camera.md`](16-qr-entrance-camera.md) §16.1.)
- **Klon/replay azaltma (A'da):** QR tek başına geçiş vermez — (1) canlı rezervasyon penceresiyle uzlaştırılır,
  (2) kamera fiziksel tırı çapraz-doğrular (M3 renk/dorse), (3) B'de imza. Anlam QR'da olmadığı için klonlama
  düşük-değer; iptal/yeniden-atama/denetim sunucuda.
- **Grounding:** token = ÖLÇÜLEN (okundu); çözülen anlam = ÖLÇÜLEN (mevcut key'e lookup); eşleşme =
  deterministik mantık; VLM = yalnız anomali anlatısı (yanlış kapı / süre dolmuş / tır-token uyumsuz).

## 15.8 Uzun-menzil dış ortam (10 m, ANPR-sınıfı) — yakalama & ortam fiziği

> Bu bölüm [`16-qr-entrance-camera.md`](16-qr-entrance-camera.md) §16.5'in **"10 m dış ortam"** satırının
> ("16–25 mm varifocal + WDR + 10 m IR + mat placard + uyarlamalı yakalama") **yakalama/ortam-fiziği**
> detayıdır. **Lens × mesafe × QR-boyutu ve compute** orada çözüldü (§16.3/§16.4) → burada **tekrarlanmaz**;
> bu bölüm yalnız 10 m'de fiziğin nerede sınırladığını ve donanım karşılığını anlatır.

Kontrollü ~5 m giriş kapısından (§16.5 birinci satır) farkı: mesafe artınca **ışık bütçesi çöker** ve
dış ortam **denetlenemez** hale gelir. Sıralı darboğazlar:

- **Işık-vs-shutter darboğazı (bağlayıcı kısıt).** 15 km/h'i dondurmak ~1/700 s eşiğinde başlar,
  marjlı çalışma noktası 1/1000–1/2000 s (§16.4 motion-blur satırı); ama uzun-tele lensin küçük diyaframı
  (§16.4 ışık satırı) o hızda sensöre
  az foton bırakır. 10 m'de bu ikisi **çakışır** → §15.1'in "fizik sınırı = ışık, compute değil" tezi
  burada en serttir. Çözüm foton üretmek (IR/aydınlatma/WDR), gain'i (gürültüyü) fırlatmak **değil**
  (§15.3 gain-tavanı politikası).
- **WDR / backlight / güneş.** Açık havada güneş tıranın arkasında veya placard'a çarpıp **parlama**
  yaratır → generic "sahne-ortalaması" pozlama QR'ı ya yakar ya karartır. Gerekir: **WDR sensörü** +
  pozlama **ölçümünü placard ROI'sine** kilitle (§15.2 luma/histogram sinyali sahne değil ROI üstünden).
- **Sis / yağmur / kir → ECC marjı.** Kontrast düşürücü hava ve lens/placard kiri modül kenarlarını
  yumuşatır. **ECC level H (%30 onarım, §16.1)** bozulan modüllere marj verir — ama ECC **kısmi** bozulmayı
  kurtarır, **tam örtme/okunamazlığı değil**. Dürüst sınır: ağır sis/çamur = donanım/konum sorunu, yazılım değil.
- **Gece 10 m IR + ⚠ retroreflektif tuzağı.** 10 m'de gece güçlü IR ister; ama placard **retroreflektif**
  malzemeye basılırsa IR ışığı doğrudan geri yansır → **IR-hotspot / blooming** → beyaz patlamış leke →
  QR okunamaz. Çözüm: **mat / IR-dostu (retroreflektif-olmayan) baskı** — §16.5 "mat placard" satırının
  fiziksel gerekçesi budur. Çıplak gözle sezilmeyen, sahada QR'ı öldüren spesifik bir hatadır.
- **Isı-pırıltısı (heat shimmer).** Uzun menzil + sıcak zemin (asfalt/gün ortası) → atmosferik pırıltı
  modül kenarlarını titretir. Azaltma sınırlı (kısa entegrasyon + çok-kare "en iyi kareyi seç"); temelde
  **ortamsal** — mesafeyi kısaltmak en etkili çözüm.
- **DoF → şeride sabit-odak.** Menzil için gereken uzun odak = sığ DoF (§16.4 DoF satırı: uzun tele →
  sığ; sabit odakta mesafe DoF'u *derinleştirir*, sığlığın kaynağı odak/büyütme). Otomatik-odak avlanması
  yerine **giriş şeridine sabit-odak**. (Mekanizma §16.4'te; burada yalnız ortam bağlamı.)

**Özet karar:** 10 m dış-ortam okuması **mümkün ama donanıma bağımlı** — sizing/lens §16, ortam-fiziği bu
bölüm. Yazılım (uyarlamalı yakalama §15.2–15.4) yalnız *mevcut* fotonu en iyi kullanır; foton yetmiyorsa
çözüm IR/WDR/mat-baskı/mesafe, kod değil (§15.5 dürüst sınır).

## 15.9 Frigate giriş-kamera rol şablonu (örnek — kod değil)

> **Örnek/illüstratif YAML** — mevcut `frigate/config.yml`'e **eklenmedi** (bu doküman M8 tasarım eki, kod
> YOK). Kanıtlanmış `cam_tir` bloğunu (`frigate/config.yml:167-183`) giriş-QR rolüne uyarlar; §15.6'nın
> "M8.1'de config rolleri + bridge controller olarak somutlaşır" ileri-atfının somut karşılığıdır.

Giriş kamerası **iki-akışlı** çalışır: düşük-çözünürlüklü **substream** Frigate'e tespit için, yüksek-çözünürlüklü
**4MP main** yalnız olay anında QR karesi için.

```yaml
# ÖRNEK — mevcut config'e eklenmedi (illüstratif). cam_tir (frigate/config.yml:167-183) temelli.
cam_giris:
  ffmpeg:
    inputs:
      # GİRDİ substream native fps'te kalmalı — 5fps'lik bir *girdi* Frigate watchdog'unu tetikler (config.yml:158-159).
      - path: rtsp://host.docker.internal:8554/cam_giris   # DÜŞÜK-ÇÖZ substream
        roles: [detect]
  detect:
    enabled: true
    width: 640
    height: 480
    fps: 5                    # detect alt-örnekleme oranı; girdi capture fps'inden bağımsız (cam_tir ile aynı)
  motion:                     # cam_tir ile aynı — hareket eşiği tır sahnesine ayarlı
    threshold: 18
    contour_area: 10
    improve_contrast: true
  zones:
    cam_giris_zone:
      coordinates: 0,480,640,480,640,0,0,0
  # 4MP main'e Frigate `record` rolü VERİLMEZ: record kapalı (config.yml:55-57 record.enabled: false —
  #   "kayıt Dahua NVR'da"). QR-kalite yüksek-çöz kareyi Frigate'in detect-çöz snapshot'ı üretmez;
  #   truck-event tetiğiyle ayrı M8.1 QR bileşeni 4MP main'den (Frigate-paketli go2rtc restream) çeker.
```

**Yakalama politikası:**

- **Tespit = Frigate**, düşük-çöz substream üstünde (kanıtlanmış cam_tir deseni). Frigate `truck` olayını
  MQTT'ye yayar.
- **Yüksek-çöz QR karesi = olay-tetikli anlık-görüntü**, record-clip **değil**. Bu, deponun kayıt duruşuyla
  tutarlı: `record.enabled=false` (kayıt Dahua NVR'da, config.yml:55-57) + `snapshots.enabled` global açık
  (config.yml:48-49) → "sürekli klip değil, olay anında kare" zaten projenin duruşu. *(docs/16 §16.4'teki
  "4MP record" ibaresi genel çift-akış etiketidir; burada record-rolü kapalı olduğundan yakalama anlık-görüntü
  biçimindedir — çelişki değil, netleştirme.)* QR-kalite kareyi üreten Frigate snapshot'ı (detect-çöz) **değil**,
  4MP main'den çeken M8.1 bileşenidir.
- **QR decode Frigate-native DEĞİL** → ayrı **M8.1 bileşeni** (pyzbar/zxing-sınıfı), truck-event ile tetiklenir.
  Böylece **hatalı bir QR okuması asla bir Frigate tespiti gibi görünemez** — sınıf sınırı korunur.

**Grounding (üç-sınıf köprü, [`12-forensic-behavioral-intelligence.md`](12-forensic-behavioral-intelligence.md)
§A.1):** §15.5/§15.7'deki iki-sınıf QR çerçevesi, §A.1'in üç sınıfına şöyle oturur — decode edilen token =
**ÖLÇÜLEN** (ECC sağlamasıyla sert geç/kal, eşik-türevi değil); blur / decode-güven ön-eşiği (§15.2 hareket-blur
satırı) = **TÜRETİLMİŞ** (gürültülü keskinlik sinyali üstünde eşik → düşükse çekimser kal, hatalı okuma yayma);
kapı-uygunluğu = deterministik lookup (ÖLÇÜLEN); VLM = yalnız anomali anlatısı (**ÇIKARSANAN**).

**Detector-bağımsız:** tespit Frigate/MQTT sözleşmesi arkasında durduğundan CPU detektörünü Coral/GPU'ya takas
etmek `detectors:` bloğu değişikliğidir (config.yml:24-30), bu kamera rol şablonuna dokunmaz — QR/giriş tasarımı
detektörden bağımsızdır (ölçekleme/detektör-takası: [`17-deployment-and-scaling.md`](17-deployment-and-scaling.md)).
