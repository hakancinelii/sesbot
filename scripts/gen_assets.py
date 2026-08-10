#!/usr/bin/env python3
"""PDF kapagindan cover.png ve PWA ikonlarini uretir.

Ciktilari hem reader/ (yerel sunucu) hem public/ (Vercel) altina yazar.
"""

from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "Dan-Brown-Sirlarin-Sirri.pdf"
DEST_DIRS = (ROOT / "reader", ROOT / "public")
COVER_DPI = 150
ICON_SIZES = (16, 32, 48, 180, 192, 512)
PAD_RATIO = 0.02


def render_cover(dpi: int = COVER_DPI) -> Image.Image:
    doc = fitz.open(PDF)
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
    doc.close()
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return img


def square_icon(cover: Image.Image, size: int) -> Image.Image:
    """Kapak fotografini kare ikona cevirir (ortalar, arkaplan renkli)."""
    canvas = Image.new("RGB", (size, size), (247, 243, 235))
    scaled = ImageOps.contain(cover, (int(size * (1 - 2 * PAD_RATIO)), int(size * (1 - 2 * PAD_RATIO))))
    x = (size - scaled.width) // 2
    y = (size - scaled.height) // 2
    canvas.paste(scaled, (x, y))
    return canvas


def render_front_pages(dpi: int = 150) -> None:
    """Kitabin ilk 8 sayfasini (kapak, kunye vb.) gorsel olarak render eder.

    Cikti: reader/front-0.png .. front-7.png ve public/front-0.png ..
    (manifest'te sayfa 1..8 bu gorselleri gosterir)
    """
    doc = fitz.open(PDF)
    for pdf_index in range(8):
        page = doc[pdf_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        for dest in DEST_DIRS:
            dest.mkdir(parents=True, exist_ok=True)
            img.save(dest / f"front-{pdf_index}.png")
    doc.close()
    print("On sayfa gorselleri uretildi (front-0..7.png).")


def main() -> None:
    cover = render_cover()

    for dest in DEST_DIRS:
        dest.mkdir(parents=True, exist_ok=True)
        cover.save(dest / "cover.png")
        for size in ICON_SIZES:
            icon = square_icon(cover, size)
            if size <= 32:
                icon.save(dest / f"favicon-{size}.png")
            else:
                icon.save(dest / f"icon-{size}.png")
        apple = square_icon(cover, 180)
        apple.save(dest / "apple-touch-icon.png")
        print(f"Uretildi: {dest}")

    render_front_pages()

    webmanifest = {
        "name": "Sırların Sırrı - Sesli Kitap",
        "short_name": "Sırların Sırrı",
        "description": "Dan Brown - Sırların Sırrı sesli kitap okuyucu",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f7f3eb",
        "theme_color": "#8b4513",
        "lang": "tr",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
        ],
    }
    import json

    for dest in DEST_DIRS:
        (dest / "site.webmanifest").write_text(
            json.dumps(webmanifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print("site.webmanifest yazildi.")


if __name__ == "__main__":
    main()
