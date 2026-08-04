#!/usr/bin/env python3
"""Kitabin tum sayfalarini macOS Vision OCR ile okuyup ocr_text/ altina kaydeder.

Cikti: ocr_text/ocr_pages.json
    { "<pdf_index>": {"book_page": <int|None>, "text": "<satirlar>"} }
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "Dan-Brown-Sirlarin-Sirri.pdf"
OUT_DIR = ROOT / "ocr_text"
OUT_FILE = OUT_DIR / "ocr_pages.json"
HELPER = Path(__file__).parent / "ocr_helper.swift"
DEFAULT_DPI = 3.0


def get_printed_page_number(page: fitz.Page):
    import re

    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        text = "".join(
            span["text"]
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        ).strip()
        bbox = block["bbox"]
        if re.fullmatch(r"\d{1,4}", text) and bbox[1] > page.rect.height * 0.8:
            return int(text)
    return None


def ocr_page_number(text: str):
    """OCR metninin alt kismindan sayfa numarasini bulur.

    Sayfa numarasi genellikle son satirdir ancak 'F: 4' gibi artefaktlar
    sona eklenebilir; bu yuzden son 5 satir geriye dogru taranir.
    """
    import re

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines[-5:]):
        if re.fullmatch(r"\d{1,4}", line):
            number = int(line)
            if 1 <= number <= 700:
                return number
    return None


def ocr_image(image_path: Path) -> str:
    result = subprocess.run(
        ["swift", str(HELPER), str(image_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"OCR basarisiz: {result.stderr[:300]}")
    return result.stdout


def ocr_page(doc: fitz.Document, pdf_index: int, dpi: float) -> str:
    page = doc[pdf_index]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi, dpi))
    with tempfile.TemporaryDirectory() as tmp:
        image_path = Path(tmp) / "page.png"
        pix.save(str(image_path))
        return ocr_image(image_path)


def main() -> None:
    start_page_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end_page_arg = int(sys.argv[2]) if len(sys.argv) > 2 else None

    OUT_DIR.mkdir(exist_ok=True)
    existing = {}
    if OUT_FILE.exists():
        existing = json.loads(OUT_FILE.read_text(encoding="utf-8"))

    doc = fitz.open(PDF)
    page_count = doc.page_count
    end = min(end_page_arg, page_count) if end_page_arg else page_count

    started = time.time()
    for pdf_index in range(start_page_arg, end):
        try:
            text = ocr_page(doc, pdf_index, DEFAULT_DPI)
            book_page = ocr_page_number(text) or get_printed_page_number(doc[pdf_index])
            existing[str(pdf_index)] = {"book_page": book_page, "text": text}
        except Exception as exc:
            print(f"[{pdf_index}/{page_count}] HATA: {exc}", flush=True)
            existing[str(pdf_index)] = {"book_page": None, "text": ""}
            continue

        if (pdf_index + 1) % 10 == 0 or pdf_index == end - 1:
            OUT_FILE.write_text(
                json.dumps(existing, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            elapsed = time.time() - started
            rate = (pdf_index - start_page_arg + 1) / elapsed if elapsed else 0
            remaining = (end - pdf_index - 1) / rate if rate else 0
            print(
                f"[{pdf_index + 1}/{end}] tamam ({elapsed:.0f}s gecti, "
                f"~{remaining / 60:.0f} dk kaldi)",
                flush=True,
            )

    OUT_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\nBitti. {OUT_FILE}")


if __name__ == "__main__":
    main()
