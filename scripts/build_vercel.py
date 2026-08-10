#!/usr/bin/env python3
"""Vercel deploy icin public/ klasorunu olusturur."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from reader_server import build_manifest  # noqa: E402
from lib.supabase_storage import is_configured, file_urls  # noqa: E402

PUBLIC = ROOT / "public"
READER = ROOT / "reader"
OUTPUT = ROOT / "output"
PDF = ROOT / "Dan-Brown-Sirlarin-Sirri.pdf"


def rewrite_manifest_with_urls(manifest: dict, url_map: dict[str, str]) -> dict:
    for page_key, items in manifest.get("pages", {}).items():
        for item in items:
            name = f"{page_key}_{item['index']}.mp3"
            if name in url_map:
                item["audio"] = url_map[name]
                item["available"] = True
    available_pages = sorted(
        int(page)
        for page, items in manifest.get("pages", {}).items()
        if any(item.get("available") for item in items)
    )
    manifest["availablePages"] = available_pages
    page_audio: dict[str, str] = {}
    for page in available_pages:
        name = f"{page}.mp3"
        if name in url_map:
            page_audio[str(page)] = url_map[name]
    manifest["pageAudio"] = page_audio
    return manifest


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

    url_map: dict[str, str] = {}
    if is_configured():
        url_map = file_urls("audio/pages/")
        if url_map:
            manifest = rewrite_manifest_with_urls(manifest, url_map)
            print(f"Supabase'ten {len(url_map)} ses dosyasi baglandi.")
        else:
            print("Supabase'te audio/pages/ altinda dosya bulunamadi, yerel yol kullanildi.")
    else:
        print("Supabase yapilandirilmadi, sesler yerel /audio/ yolundan sunulacak.")

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
        for name in (
            "cover.png",
            "icon-192.png",
            "icon-512.png",
            "apple-touch-icon.png",
            "favicon-16.png",
            "favicon-32.png",
            "site.webmanifest",
        ):
            source = READER / name
            if source.exists():
                shutil.copy2(source, PUBLIC / name)
        for i in range(8):
            name = f"front-{i}.png"
            source = READER / name
            if source.exists():
                shutil.copy2(source, PUBLIC / name)

    print(f"Vercel build hazir: {copied} yerel ses dosyasi, sayfalar {manifest['availablePages']}")


if __name__ == "__main__":
    main()
