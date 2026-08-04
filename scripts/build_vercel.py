#!/usr/bin/env python3
"""Vercel deploy icin public/ klasorunu olusturur."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reader_server import build_manifest  # noqa: E402

PUBLIC = ROOT / "public"
READER = ROOT / "reader"
OUTPUT = ROOT / "output"
PDF = ROOT / "Dan-Brown-Sirlarin-Sirri.pdf"


def main() -> None:
    if not PDF.exists():
        raise SystemExit(f"PDF bulunamadi: {PDF}")

    audio_dir = PUBLIC / "audio"
    if audio_dir.exists():
        shutil.rmtree(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for mp3 in sorted(OUTPUT.glob("*.mp3")):
        shutil.copy2(mp3, audio_dir / mp3.name)
        copied += 1

    manifest = build_manifest(PDF, OUTPUT)
    PUBLIC.mkdir(exist_ok=True)
    (PUBLIC / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if READER.exists():
        for name in ("index.html", "style.css", "app.js"):
            source = READER / name
            if source.exists():
                shutil.copy2(source, PUBLIC / name)

    print(f"Vercel build hazir: {copied} ses dosyasi, sayfalar {manifest['availablePages']}")


if __name__ == "__main__":
    main()
