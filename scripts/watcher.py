#!/usr/bin/env python3
"""VoxCPM API kuyrugu acilinca narrate_all.py batch'ini otomatik baslatir.

Her N dakikada bir API'yi dener (kuyruk duruyorsa 503 aninda doner, is yuklemez).
API aciksa ve batch calismiyorsa batch'i yeniden baslatir. Batch calisirken
mudahale etmez.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "watcher.log"
POLL_SECONDS = 300  # 5 dakika
GRADIO_URL = "https://voxcpm.modelbest.cn/gradio_api/call/generate"
ENV = {
    "SUPABASE_URL": os.environ.get("SUPABASE_URL", ""),
    "SUPABASE_SERVICE_KEY": os.environ.get("SUPABASE_SERVICE_KEY", ""),
    "SUPABASE_BUCKET": os.environ.get("SUPABASE_BUCKET", "audio"),
}


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def api_queue_open() -> bool:
    body = (
        '{"data":["test","",null,false,"",2.0,false,false,10,"watchdog"]}'
    ).encode("utf-8")
    req = urllib.request.Request(GRADIO_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                return False
            # API kuyruk tabanli; generate POST basarili olsa bile kuyruk
            # bos sonuc ("complete" ama data yok) verebilir. Uretimin
            # gercekten ses donup donmedigini SSE'de data satiri arayarak dogrula.
            event_id = json.loads(resp.read().decode("utf-8")).get("event_id")
            if not event_id:
                return False
            stream = urllib.request.urlopen(
                f"{GRADIO_URL}/{event_id}", timeout=30
            )
            deadline = time.time() + 30
            for raw_line in stream:
                if time.time() > deadline:
                    return False
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="ignore")
                if line.startswith("data:") and ('"url"' in line or '"path"' in line):
                    return True
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                    if event == "error":
                        return False
            return False
    except urllib.error.HTTPError as exc:
        return exc.code != 503
    except Exception:
        return False


def batch_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-f", "narrate_all.py"], capture_output=True, text=True
    )
    return result.returncode == 0


def launch_batch() -> None:
    env = os.environ.copy()
    env.update(ENV)
    workers = os.environ.get("NARRATE_WORKERS", "1")
    start_page = os.environ.get("NARRATE_START_PAGE", "1")
    cmd = [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "narrate_all.py"),
           "--workers", workers, "--start-page", start_page]
    log(f"API acik, batch baslatiliyor... (workers={workers}, start-page={start_page})")
    with open(ROOT / "narrate_all.log", "a", encoding="utf-8") as handle:
        subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )


def main() -> None:
    if not all(ENV.values()):
        raise SystemExit("SUPABASE_* ortam degiskenleri gerekli.")

    log(f"Izleyici basladi. {POLL_SECONDS}s aralikla kontrol.")
    while True:
        if not batch_running():
            if api_queue_open():
                launch_batch()
            else:
                log("API kapali (kuyruk duruyor), bekleniyor...")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Izleyici kapatildi.")
