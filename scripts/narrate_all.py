#!/usr/bin/env python3
"""Kitabin TAMAMINI seslendirir: her sayfanin paragraflarini VoxCPM ile uretir,
Supabase'e yukler ve tam sayfa sesini birlestirir. Kaldigi yerden devam eder.

Kullanim:
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... SUPABASE_BUCKET=audio \
        python3 scripts/narrate_all.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from sesbot import extract_paragraphs, VoxCPMClient  # noqa: E402
from lib.supabase_storage import (  # noqa: E402
    is_configured,
    upload_bytes,
    file_urls,
)

LOG = ROOT / "narrate_all.log"
PROGRESS = ROOT / "narrate_progress.json"
PDF = ROOT / "Dan-Brown-Sirlarin-Sirri.pdf"
REFERENCE = ROOT / "amazon_reference_50s.mp3"
MERGE_URL = "https://sesbot-okuyucu-theta.vercel.app/api/merge-page"

PARA_RE = re.compile(r"^\d+_\d+\.mp3$")


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def merge_page(book_page: int) -> bool:
    import urllib.request

    body = json.dumps({"page": book_page}).encode("utf-8")
    req = urllib.request.Request(
        MERGE_URL, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("pageAudio"))
    except Exception as exc:
        log(f"  Sayfa {book_page} birlestirme hatasi: {exc}")
        return False


def main() -> None:
    if not is_configured():
        raise SystemExit("SUPABASE_URL / SERVICE_KEY / BUCKET ortam degiskenleri gerekli.")

    paragraphs = extract_paragraphs(PDF)
    pages: dict[int, list] = {}
    for para in paragraphs:
        pages.setdefault(para.book_page, []).append(para)

    url_map = file_urls("audio/pages/")
    done = {name for name in url_map if PARA_RE.match(name)}
    log(f"Toplam {sum(len(v) for v in pages.values())} paragraf, "
        f"{len(done)} hazir.")

    import requests

    client = VoxCPMClient(cfg_value=2.0)
    log("Referans ses yukleniyor...")
    client.upload_reference(REFERENCE)

    total_pages = len(pages)
    skipped = 0
    for index, (book_page, page_paras) in enumerate(sorted(pages.items()), 1):
        missing = [p for p in page_paras if not p.heading and p.filename not in done]
        if not missing:
            skipped += 1
            continue
        log(f"[{index}/{total_pages}] Sayfa {book_page}: {len(missing)} paragraf "
            f"(kalan toplam ~{sum(1 for p in paragraphs if not p.heading and p.filename not in done)})")

        page_ok = True
        for para in missing:
            ok_uploaded = False
            for attempt in range(1, 6):
                try:
                    result = client.generate(para.text)
                    audio_url = result.get("url")
                    if not audio_url:
                        audio_url = f"{client.space_url}/gradio_api/file={result['path']}"
                    audio = requests.get(audio_url, timeout=120).content
                    upload_bytes(f"audio/pages/{para.filename}", audio)
                    done.add(para.filename)
                    log(f"  {para.filename} OK ({len(audio)} byte, "
                        f"kalan {sum(1 for p in paragraphs if not p.heading and p.filename not in done)})")
                    ok_uploaded = True
                    break
                except Exception as exc:
                    wait = 20 * attempt
                    log(f"  {para.filename} hata ({attempt}/5): {exc} -> {wait}s sonra tekrar")
                    time.sleep(wait)
            if not ok_uploaded:
                log(f"  {para.filename} BASARISIZ, sayfa atlaniyor.")
                page_ok = False
                break

        if page_ok:
            merge_page(book_page)
        else:
            log(f"  Sayfa {book_page} eksik paragraf nedeniyle atlandi.")

        with open(PROGRESS, "w", encoding="utf-8") as handle:
            json.dump(
                {"last_page": book_page, "done": len(done), "skipped": skipped},
                handle,
            )

    log(f"TAMAMLANDI. Hazir paragraf: {len(done)}")


if __name__ == "__main__":
    main()
