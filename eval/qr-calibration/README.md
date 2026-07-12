# QR Kalibrasyon Seti

`F0100` giriş-kimliği tasarımının ([docs/16](../../docs/16-qr-entrance-camera.md)) saha testi.
Opak ID, QR **V1**, **ECC-H**; placard = 29 modül (sessiz bölge dahil).

## Baskı
- Her sayfayı A4'e **%100 / gerçek boyut** bas ("sayfaya sığdır" KAPALI).
- Ölçek çubuğu cetvelle **5.0 cm** olmalı — değilse ölçek yanlış.
- **Mat** kâğıt (parlak yüzey IR/ışık hotspot yapar; docs/15 §15.8).

## Menzili lens belirler (boy değil)
docs/16 §16.2 fiziği (4MP 2560px, 5px/modül decode tabanı). 10-15 m için **tele/optik-zoom** şart:
geniş ~5mm lensle en büyük 19cm kod bile ~3 m'de takılır.

| ID | Placard | Modül | maks. okuma @5mm (geniş) | @20mm (tele) |
|----|---------|-------|--------------------------|--------------|
| F0100 | 5 cm | 1.7 mm | 0.8 m | 3.3 m |
| F0101 | 7 cm | 2.4 mm | 1.1 m | 4.6 m |
| F0102 | 9 cm | 3.1 mm | 1.5 m | 5.9 m |
| F0103 | 11 cm | 3.8 mm | 1.8 m | 7.2 m |
| F0104 | 13 cm | 4.5 mm | 2.1 m | 8.5 m |
| F0105 | 15 cm | 5.2 mm | 2.5 m | 9.8 m |
| F0106 | 17 cm | 5.9 mm | 2.8 m | 11.1 m |
| F0107 | 19 cm | 6.6 mm | 3.1 m | 12.4 m |

## Test protokolü
1. Kodları bas, doğru boyu cetvelle doğrula.
2. Kamerayı 5 / 10 / 15 m'ye kur (lens/zoom'u not et).
3. Her mesafede videoyu çek; hangi ID'ler decode oluyor kaydet.
4. Ölçüleni docs/16 tablosuyla karşılaştır (model doğru mu? lens etkisi?).

Üretim: `python3 generate_qr_set.py` (segno + Pillow).
