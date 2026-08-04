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
from lib.supabase_storage import is_configured, upload_file  # noqa: E402

PUBLIC = ROOT / "public"
READER = ROOT / "reader"
OUTPUT = ROOT / "output"
PDF = ROOT / "Dan-Brown-Sirlarin-Sirri.pdf"


def rewrite_manifest_with_supabase(manifest: dict, url_map: dict[str, str]) -> dict:
    for items in manifest.get("pages", {}).values():
        for item in items:
            audio = item.get("audio")
            if audio:
                name = audio.rsplit("/", 1)[-1]
                if name in url_map:
                    item["audio"] = url_map[name]
    page_audio = manifest.get("pageAudio", {})
    for page_key, audio in list(page_audio.items()):
        name = audio.rsplit("/", 1)[-1]
        if name in url_map:
            page_audio[page_key] = url_map[name]
    return manifest


def upload_audio_to_supabase(audio_dir: Path) -> dict[str, str]:
    url_map: dict[str, str] = {}
    if not is_configured():
        print("Supabase yapilandirilmadi, audio Supabase'e yuklenmeyecek.")
        return url_map
    for mp3 in sorted(audio_dir.glob("*.mp3")):
        key = f"audio/pages/{mp3.name}"
        try:
            url = upload_file(key, str(mp3))
            url_map[mp3.name] = url
        except Exception as exc:
            print(f"  Supabase yukleme hatasi ({mp3.name}): {exc}")
    print(f"Supabase'e {len(url_map)} ses dosyasi yuklendi.")
    return url_map


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
    url_map = upload_audio_to_supabase(audio_dir)
    if url_map:
        manifest = rewrite_manifest_with_supabase(manifest, url_map)
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
