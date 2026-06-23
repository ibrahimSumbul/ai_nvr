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

> Açık iş: **§15.8 Uzun-menzil dış ortam (10m, ANPR-sınıfı)** bölümü (tele ~16-25mm varifocal + WDR + mat
> ~25cm QR ECC-H + 10m IR + 1/1000-1/2000s; güneş/backlight/sis/gece/ısı-pırıltısı/odak) — taze session'da eklenecek.
