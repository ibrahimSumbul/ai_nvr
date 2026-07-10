# 16 — QR Giriş Kamerası: Boyutlandırma & Lens Analizi (compact)

> **Statü: M8 tasarım eki — kod YOK.** Tır/dorse kimliğini girişte QR ile okuyup track'e iliştirme
> (dok-kapı atama/uygunluk) için **lens × mesafe × QR-boyutu** analizi + diğer etmenler. Uyarlamalı
> yakalama (shutter/IR/gain) → [`15-adaptive-capture.md`](15-adaptive-capture.md); demo bağlamı →
> [`13-portfolio-demo-vision.md`](13-portfolio-demo-vision.md) (Kamera 1).

## 16.1 Kimlik şeması (özet)

- QR = **`F0100`'den +1 sıralı opak ID** (düz-metin; telefonda yalnız "F0100" → eylem/anlam yok). Anlam
  (kapı/slot/izin) sunucuda **değişebilir eşleme** ile çözülür → QR = sabit handle, key içerde değişir.
- 5 karakter → **QR Versiyon 1 (21×21 modül), ECC level H (%30 onarım)**. F0100–F9999 = 9900 tır.
- **Sahtecilik çözümü = e-İrsaliye 4-yönlü uzlaştırma** (kullanıcı kararı): QR-token→rezervasyon ·
  fiziksel tır (M3 renk/dorse + ops. plaka ANPR)→kimlik · **e-İrsaliye (GİB imzalı)→bugün bu araç/kapı izinli mi** ·
  kamera→hangi kapı/ne zaman. Hepsi ÖLÇÜLEN/deterministik; VLM yalnız anomali anlatır. "Aynı tır olsa bile
  bugün izni yoksa → flag." e-İrsaliye otorite anchor olduğundan imzalı-token (Varyant B) **şart değil**.

## 16.2 Boyutlandırma formülü

```
Yatay FOV açısı = 2·atan( sensör_w / (2·f) )      # sensör_w ≈ 5.4 mm (1/2.8" 4MP)
FOV genişliği  W(D,f) = D × sensör_w / f          # D = mesafe
Min QR placard ≈ 0.06 × W                          # V1 (21 modül + 4-modül sessiz bölge ≈ 29) × ~5 px/modül (varsayılan decode tabanı)
                                                   #   = 145 px / 2560 px ≈ %5.7 → güvenli %6
```
*Not: 2560 px yatay (4MP/2K). "Min placard" = sessiz bölge dahil basılı kenar. Sensör boyutuna göre ±%10.*

## 16.3 Lens × mesafe × QR tablosu (2.5 / 5 / 20 / 50 mm)

| Lens (f) | Yatay FOV | Tipik standoff | O mesafede FOV gen. | **Min QR placard (~%6)** | Karakter |
|---|---|---|---|---|---|
| **2.5 mm** | ~94° (ultra-geniş) | 1.5–2 m | 3.2–4.3 m | **19–26 cm** | çok yakın kapı; köşe distorsiyonu; geniş yakalama penceresi |
| **5 mm** | ~57° (geniş) | 3–5 m | 3.2–5.4 m | **19–32 cm** | **dengeli**; 5 m'de FOV 5.4 m → ~30 cm (mevcut senaryo) |
| **20 mm** | ~15° (tele) | 8–10 m | 2.2–2.7 m | **13–16 cm** | dar pencere; 10 m'de ~15 cm yeter; sığ-ca DoF |
| **50 mm** | ~6° (uzun tele) | 20–30 m | 2.2–3.2 m | **13–19 cm** | ANPR menzili; sığ DoF + ışık zoru + küçük pencere |

**Okuma:** kısa odak (2.5–5 mm) = yakın + geniş → daha **büyük QR (~20–30 cm)** ama **çok kare** (bol decode denemesi) +
geniş diyafram (iyi ışık). Uzun odak (20–50 mm) = uzak + dar → **küçük QR (~13–19 cm)** okur ama **az kare**,
**sığ DoF** (odak kritik) ve **küçük diyafram** (ışık az → hızlı shutter zor).

## 16.4 Diğer etmenler (lens'ten bağımsız veya etkileşimli)

| Etmen | Etki | Not |
|---|---|---|
| **Motion blur / shutter** | lens'ten bağımsız; 15 km/h için modül-blur<1 → **~1/700 s (marjlı; ham hesap ~1/420 s)**, tatlı nokta **1/1000–1/2000 s** | 30 cm/V1 modül ~10–14 mm → 1/500 s'te bile tolere; sınır = ışık |
| **DoF** | ↑odak + ↓mesafe → ↓DoF (odak kritik) | uzun tele yakında çok sığ → **şeride sabit-odak** |
| **Yakalama penceresi** | dar FOV (uzun odak) → QR kısa görünür → az kare | 4.17 m/s'te FOV 2 m≈12 kare, 5 m≈30 kare @25fps |
| **Işık** | uzun-zoom lensler küçük diyafram → az ışık → hızlı shutter zor | wide lens (2.5–5 mm) f/1.6–2.0 → iyi; gece **IR** zorunlu |
| **Compute** | lens compute'u **etkilemez** | substream detect (640×480@5fps) + 4MP main (olay-anı grab) + **event-gated QR decode** → ~1 çekirdek + ~200–300 MB |
| **Yüksek açı** | QR (kaput/çatı, finder+perspektif) yüksek açıya **dayanıklı**; plaka (dik) bozulur | yüksek-açı senaryosu QR'ı kayırır |

## 16.5 Senaryo önerileri

| Senaryo | Lens | QR | Yakalama |
|---|---|---|---|
| Kontrollü giriş kapısı, ~5 m, yüksek açı | **5–8 mm** | ~25–30 cm | 1/1000 s + IR; substream detect |
| 10 m dış ortam | **16–25 mm varifocal** | ~20–25 cm (ECC-H) | WDR + 10 m IR + mat placard + uyarlamalı yakalama (§15) |
| 20–30 m uzak ANPR-sınıfı | **35–50 mm** | ~25–30 cm (DoF/ışık/pencere marjı) | güçlü IR + sabit-odak şerit |

**Genel reçete:** **varifocal lens** (sahada FOV ayarı) + 30 cm placard (her senaryoyu karşılar, bol marj) +
1/1000–1/2000 s + IR + substream-detect + e-İrsaliye uzlaştırma. Aşırı uzun tele yalnız gerçek uzun-menzil
gerektiğinde (DoF/ışık/pencere bedeli var).
