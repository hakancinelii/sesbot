#!/usr/bin/env python3
"""Kitabin TAMAMINI seslendirir: her sayfanin paragraflarini VoxCPM ile uretir,
Supabase'e yukler ve tam sayfa sesini birlestirir. Kaldigi yerden devam eder.

Paralel calistirma: --workers N ile ayni anda N sayfa seslendirilir.
(VoxCPM demo API'si kuyruk tabanlidir; cok agresif paralellik 503
kisitlamasina yol acabilir, varsayilan 2 guvenli bir denge.)

Kullanim:
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... SUPABASE_BUCKET=audio \
        python3 scripts/narrate_all.py [--workers 2]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
MAX_RETRIES = 30
CONSECUTIVE_503_EXIT = 3

_log_lock = threading.Lock()
_state_lock = threading.Lock()


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with _log_lock:
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


def save_progress(last_page: int, done_count: int, skipped: int) -> None:
    with _state_lock:
        with open(PROGRESS, "w", encoding="utf-8") as handle:
            json.dump(
                {"last_page": last_page, "done": done_count, "skipped": skipped},
                handle,
            )


class NarrationState:
    def __init__(self, total_paras: int) -> None:
        self.done: set[str] = set()
        self.skipped = 0
        self.consecutive_503 = 0
        self.stop_requested = False
        self.total_paras = total_paras

    def remaining(self) -> int:
        return sum(
            1
            for task in self._tasks
            for p in task[1]
            if not p.heading and p.filename not in self.done
        )


def make_client() -> VoxCPMClient:
    client = VoxCPMClient(cfg_value=2.0)
    client.upload_reference(REFERENCE)
    return client


def narrate_page(
    book_page: int,
    missing_paras: list,
    state: NarrationState,
    total_pages: int,
) -> None:
    import requests

    client = make_client()
    page_ok = True
    for para in missing_paras:
        if state.stop_requested:
            log(f"  Durduruldu, sayfa {book_page} yarida birakildi.")
            page_ok = False
            break
        ok_uploaded = False
        attempt = 1
        while attempt <= MAX_RETRIES and not state.stop_requested:
            try:
                result = client.generate(para.text)
                audio_url = result.get("url")
                if not audio_url:
                    audio_url = f"{client.space_url}/gradio_api/file={result['path']}"
                audio = requests.get(audio_url, timeout=120).content
                upload_bytes(f"audio/pages/{para.filename}", audio)
                with _state_lock:
                    state.done.add(para.filename)
                    state.consecutive_503 = 0
                    remaining = state.remaining()
                log(f"  {para.filename} OK ({len(audio)} byte, kalan {remaining})")
                ok_uploaded = True
                break
            except Exception as exc:
                is_503 = "503" in str(exc) or "Service Unavailable" in str(exc)
                if is_503:
                    with _state_lock:
                        state.consecutive_503 += 1
                        if state.consecutive_503 >= CONSECUTIVE_503_EXIT:
                            state.stop_requested = True
                    if state.stop_requested:
                        log("API kuyrugu kapali (3x503), is cikiliyor. Watcher yeniden baslatacak.")
                        page_ok = False
                        break
                    wait = 180
                    log(f"  {para.filename} API 503 (kisitlama) -> {wait}s sonra tekrar")
                    time.sleep(wait)
                    attempt += 1
                    continue
                wait = 20 * attempt
                log(f"  {para.filename} hata ({attempt}/{MAX_RETRIES}): {exc} -> {wait}s sonra tekrar")
                time.sleep(wait)
                attempt += 1
        if not ok_uploaded:
            log(f"  {para.filename} BASARISIZ, sayfa atlaniyor.")
            page_ok = False
            break

    if page_ok:
        merge_page(book_page)
    else:
        log(f"  Sayfa {book_page} eksik paragraf nedeniyle atlandi.")

    with _state_lock:
        save_progress(
            book_page,
            len(state.done),
            state.skipped,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=2, help="Ayni anda seslendirilecek sayfa sayisi")
    args = parser.parse_args()
    workers = max(1, args.workers)

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

    tasks: list[tuple[int, list]] = []
    state = NarrationState(total_paras=sum(len(v) for v in pages.values()))
    state.done = set(done)
    for book_page, page_paras in sorted(pages.items()):
        missing = [p for p in page_paras if not p.heading and p.filename not in state.done]
        if not missing:
            state.skipped += 1
            continue
        tasks.append((book_page, missing))
    state._tasks = tasks

    if not tasks:
        log("Yapilacak sayfa kalmadi, cikiliyor.")
        return

    log(f"{len(tasks)} sayfa bekliyor, {workers} paralel isci ile calisiyor.")

    total_pages = len(pages)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(narrate_page, book_page, missing, state, total_pages)
            for book_page, missing in tasks
        ]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                log(f"Paralel isci hatasi: {exc}")
            if state.stop_requested:
                for f in futures:
                    f.cancel()

    log(f"TAMAMLANDI. Hazir paragraf: {len(state.done)}")


if __name__ == "__main__":
    main()
