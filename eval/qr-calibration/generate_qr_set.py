#!/usr/bin/env python3
"""QR kalibrasyon seti üretici — F0100 giriş-kimliği tasarımının (docs/16) saha testi.

docs/16 §16.1'e göre QR = `F0100`'den sıralı **opak** ID, düz-metin, QR **Versiyon 1**
(21×21 modül), **ECC level H** (%30 onarım). Bu script bir *boy merdiveni* üretir:
her kod ayrı bir A4 sayfaya **tam fiziksel boyda** basılır, 5/10/15 m'de okunabilirlik
sahada ölçülür (eval harness felsefesi: model tahmin eder, saha doğrular).

Okuma-menzili tahmini docs/16 §16.2 fiziğinden türetilir (5 px/modül decode tabanı,
4MP ~2560px yatay). Menzili **lens belirler**, boy değil — bu yüzden her kod için hem
geniş (5mm) hem tele (20mm) referans menzil verilir. Çıktı: çok-sayfalı PDF + tekil PNG'ler.

Kullanım:  python3 generate_qr_set.py
"""
from __future__ import annotations
import os
import segno
from PIL import Image, ImageDraw, ImageFont

# ── Sabitler ────────────────────────────────────────────────────────────────
DPI = 300
CM = DPI / 2.54                       # 118.11 px/cm
A4_W, A4_H = round(21.0 * CM), round(29.7 * CM)   # 2480 × 3508 px
MARGIN = round(0.8 * CM)
QUIET = 4                             # sessiz bölge (modül) — placard bu dahil
MODULES = 21                          # QR V1
PLACARD_MODULES = MODULES + 2 * QUIET # 29 (docs/16 §16.2)

# docs/16 §16.2 fiziği: FOV_genişliği = D × sensör_w / f  →  2·tan(HFOV/2) = sensör_w/f
SENSOR_W = 5.4        # mm (1/2.8" 4MP)
H_RES = 2560          # px (4MP yatay)
PX_FLOOR = 5          # decode tabanı: px/modül (docs/16 §16.2)

# ID → placard boyu (cm). Hepsi tek A4'e sığar (≤19cm). 8 kod.
SET = [
    ("F0100", 5.0),
    ("F0101", 7.0),
    ("F0102", 9.0),
    ("F0103", 11.0),
    ("F0104", 13.0),
    ("F0105", 15.0),
    ("F0106", 17.0),
    ("F0107", 19.0),
]

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
PNG_DIR = os.path.join(OUT_DIR, "png")
PDF_PATH = os.path.join(OUT_DIR, "qr-calibration-set.pdf")
README_PATH = os.path.join(OUT_DIR, "README.md")


# ── Fizik yardımcıları ──────────────────────────────────────────────────────
def module_mm(placard_cm: float) -> float:
    """Modül kenarı (mm). Placard = 29 modül = placard_cm."""
    return placard_cm * 10.0 / PLACARD_MODULES


def max_read_distance_m(placard_cm: float, focal_mm: float) -> float:
    """docs/16 §16.2: px/modül = modül / (D·sensör_w/f) · H_res ; taban = 5 px/modül.
    D_max = (modül_mm/1000)·H_res·f / (PX_FLOOR·sensör_w)."""
    mm = module_mm(placard_cm)
    return (mm / 1000.0) * H_RES * focal_mm / (PX_FLOOR * SENSOR_W)


# ── Font ────────────────────────────────────────────────────────────────────
def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


F_TITLE = _font(52)
F_ID = _font(120)
F_LABEL = _font(40)
F_SMALL = _font(30)


# ── QR render (kesin fiziksel boy, sessiz bölge dahil) ──────────────────────
def render_qr(token: str, placard_cm: float) -> Image.Image:
    qr = segno.make(token, error="h", version=1)      # V1, ECC-H — docs/16 §16.1
    mat = [list(r) for r in qr.matrix_iter(scale=1, border=0)]   # 21×21, 1=koyu
    placard_px = round(placard_cm * CM)
    mpx = placard_px / PLACARD_MODULES
    img = Image.new("1", (placard_px, placard_px), 1)  # beyaz
    d = ImageDraw.Draw(img)
    for r in range(MODULES):
        for c in range(MODULES):
            if mat[r][c]:
                x0 = round((c + QUIET) * mpx)
                y0 = round((r + QUIET) * mpx)
                x1 = round((c + QUIET + 1) * mpx)
                y1 = round((r + QUIET + 1) * mpx)
                d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=0)
    return img


def _text_center(d, cx, y, text, font, fill=(0, 0, 0)):
    w = d.textlength(text, font=font)
    d.text((cx - w / 2, y), text, font=font, fill=fill)


# ── Tek kod → A4 sayfa ──────────────────────────────────────────────────────
def make_page(token: str, placard_cm: float) -> Image.Image:
    page = Image.new("RGB", (A4_W, A4_H), (255, 255, 255))
    d = ImageDraw.Draw(page)
    cx = A4_W // 2

    _text_center(d, cx, MARGIN, "AI-NVR · QR Kalibrasyon", F_TITLE, (90, 90, 90))

    qr = render_qr(token, placard_cm).convert("RGB")
    qx = (A4_W - qr.width) // 2
    qy = round(1.7 * CM) + 60
    page.paste(qr, (qx, qy))

    # kesim kılavuzu (placard sınırı — açık gri)
    d.rectangle([qx, qy, qx + qr.width - 1, qy + qr.height - 1], outline=(200, 200, 200), width=1)

    y = qy + qr.height + round(0.7 * CM)
    _text_center(d, cx, y, token, F_ID, (0, 0, 0))
    y += 150

    mm = module_mm(placard_cm)
    d5 = max_read_distance_m(placard_cm, 5.0)
    d20 = max_read_distance_m(placard_cm, 20.0)
    lines = [
        f"Placard {placard_cm:.0f} cm (sessiz bölge dahil) · modül {mm:.1f} mm · QR V1 / ECC-H",
        f"Beklenen maks. okuma (4MP, docs/16): geniş 5mm ≈ {d5:.1f} m  ·  tele 20mm ≈ {d20:.1f} m",
    ]
    for ln in lines:
        _text_center(d, cx, y, ln, F_LABEL, (40, 40, 40))
        y += 56

    # 5 cm ölçek çubuğu (baskı ölçeğini cetvelle doğrula)
    bar_y = A4_H - round(1.6 * CM)
    bx0 = cx - round(2.5 * CM)
    bx1 = cx + round(2.5 * CM)
    d.line([bx0, bar_y, bx1, bar_y], fill=(0, 0, 0), width=4)
    for i in range(6):
        x = bx0 + round(i * CM)
        d.line([x, bar_y - 16, x, bar_y + 16], fill=(0, 0, 0), width=4)
    _text_center(d, cx, bar_y + 26, "◄ 5.0 cm ► — cetvelle doğrula", F_SMALL, (0, 0, 0))

    _text_center(
        d, cx, A4_H - round(0.7 * CM),
        "%100 / GERÇEK BOYUT bas — 'sayfaya sığdır' KAPALI olsun.",
        F_SMALL, (170, 30, 30),
    )
    return page


# ── İndeks sayfası ──────────────────────────────────────────────────────────
def make_index() -> Image.Image:
    page = Image.new("RGB", (A4_W, A4_H), (255, 255, 255))
    d = ImageDraw.Draw(page)
    x = MARGIN
    y = MARGIN
    d.text((x, y), "AI-NVR · QR Kalibrasyon Seti", font=F_TITLE, fill=(0, 0, 0)); y += 90
    for ln in [
        "F0100 giriş-kimliği tasarımının (docs/16) saha testi. Opak ID, QR V1, ECC-H.",
        "Amaç: 5 / 10 / 15 m'de hangi boy+lens okunuyor — sahada ölç, docs/16 modelini doğrula.",
        "",
        "BASKI: her sayfayı A4'e %100 (gerçek boyut) bas. Ölçek çubuğu cetvelle 5.0 cm olmalı.",
        "Mat kâğıt tercih et (parlak = IR/ışık hotspot). Gece IR testinde retroreflektif kullanma.",
        "",
        "⚠ Menzili LENS belirler, boy değil:",
        "  · geniş lens (~5mm): en büyük 19cm kod bile ~3 m ötede takılır → yakın test.",
        "  · tele/zoom (~20mm): 15cm ≈ 10 m, 19cm ≈ 12 m → 10-15 m için tele/optik-zoom şart.",
        "",
        "Kod → boy → beklenen maks. okuma (4MP, docs/16 §16.2; 5px/modül tabanı):",
    ]:
        d.text((x, y), ln, font=F_SMALL, fill=(40, 40, 40)); y += 42

    y += 10
    d.text((x, y), f"{'ID':<8}{'Placard':<12}{'Modül':<12}{'5mm(geniş)':<16}{'20mm(tele)':<16}",
           font=F_LABEL, fill=(0, 0, 0)); y += 54
    for token, cm in SET:
        row = (f"{token:<8}{str(int(cm))+' cm':<12}{module_mm(cm):.1f} mm      "
               f"{max_read_distance_m(cm,5.0):.1f} m           {max_read_distance_m(cm,20.0):.1f} m")
        d.text((x, y), row, font=F_LABEL, fill=(30, 30, 30)); y += 50

    y += 30
    for ln in [
        "Not: değerler 4MP + ideal kontrast varsayar; telefon/başka kamera farklıdır → ampirik ölç.",
        "Her testte hangi ID'lerin decode olduğunu kaydet → docs/16 tablosuna karşı kalibrasyon.",
    ]:
        d.text((x, y), ln, font=F_SMALL, fill=(90, 90, 90)); y += 40
    return page


# ── README ──────────────────────────────────────────────────────────────────
def write_readme():
    rows = "\n".join(
        f"| {t} | {int(c)} cm | {module_mm(c):.1f} mm | {max_read_distance_m(c,5.0):.1f} m | {max_read_distance_m(c,20.0):.1f} m |"
        for t, c in SET
    )
    md = f"""# QR Kalibrasyon Seti

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
{rows}

## Test protokolü
1. Kodları bas, doğru boyu cetvelle doğrula.
2. Kamerayı 5 / 10 / 15 m'ye kur (lens/zoom'u not et).
3. Her mesafede videoyu çek; hangi ID'ler decode oluyor kaydet.
4. Ölçüleni docs/16 tablosuyla karşılaştır (model doğru mu? lens etkisi?).

Üretim: `python3 generate_qr_set.py` (segno + Pillow).
"""
    with open(README_PATH, "w") as f:
        f.write(md)


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    os.makedirs(PNG_DIR, exist_ok=True)
    pages = [make_index()]
    for token, cm in SET:
        pages.append(make_page(token, cm))
        render_qr(token, cm).save(os.path.join(PNG_DIR, f"{token}.png"))
    pages[0].save(PDF_PATH, "PDF", resolution=float(DPI), save_all=True, append_images=pages[1:])
    write_readme()
    print(f"OK: {len(SET)} kod → {PDF_PATH}")
    print(f"     PNG'ler → {PNG_DIR}/")
    for token, cm in SET:
        print(f"  {token}  {int(cm):>2} cm  modül {module_mm(cm):.1f}mm  "
              f"@5mm {max_read_distance_m(cm,5.0):.1f}m  @20mm {max_read_distance_m(cm,20.0):.1f}m")


if __name__ == "__main__":
    main()
