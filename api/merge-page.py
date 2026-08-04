from http.server import BaseHTTPRequestHandler
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import urllib.request

PAUSE_MS = 1500

def _supabase_config():
    return {
        "url": os.environ.get("SUPABASE_URL", "").rstrip("/"),
        "key": os.environ.get("SUPABASE_SERVICE_KEY", "").strip(),
        "bucket": os.environ.get("SUPABASE_BUCKET", "audio").strip(),
    }


def _list_files(prefix):
    cfg = _supabase_config()
    req = urllib.request.Request(
        f"{cfg['url']}/storage/v1/object/list/{cfg['bucket']}",
        data=json.dumps({"prefix": prefix, "limit": 1000, "offset": 0}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg['key']}",
            "apikey": cfg["key"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return [i.get("name") for i in json.loads(resp.read().decode("utf-8")) if i.get("name")]


def _download(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _upload(key, data):
    cfg = _supabase_config()
    req = urllib.request.Request(
        f"{cfg['url']}/storage/v1/object/{cfg['bucket']}/{key}",
        data=data,
        method="PUT",
        headers={
            "Authorization": f"Bearer {cfg['key']}",
            "apikey": cfg["key"],
            "Content-Type": "audio/mpeg",
            "x-upsert": "true",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return f"{cfg['url']}/storage/v1/object/public/{cfg['bucket']}/{key}"


def _ffmpeg():
    from imageio_ffmpeg import get_ffmpeg_exe
    return get_ffmpeg_exe()


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            page = data.get("page")
            if not isinstance(page, int):
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"page (int) gerekli")
                return

            cfg = _supabase_config()
            names = [
                n
                for n in _list_files("audio/pages/")
                if n.startswith(f"{page}_")
            ]

            def sort_key(name):
                match = re.search(r"_(\d+)\.mp3$", name)
                return int(match.group(1)) if match else 0

            names.sort(key=sort_key)
            if not names:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"sayfa icin paragraf sesi bulunamadi")
                return

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp = Path(tmp_dir)
                for name in names:
                    url = f"{cfg['url']}/storage/v1/object/public/{cfg['bucket']}/audio/pages/{name}"
                    (tmp / name).write_bytes(_download(url))

                ff = _ffmpeg()
                silence = tmp / ".silence.mp3"
                subprocess.run(
                    [
                        ff, "-y", "-f", "lavfi",
                        "-i", "anullsrc=channel_layout=mono:sample_rate=48000",
                        "-t", str(PAUSE_MS / 1000.0),
                        "-c:a", "libmp3lame", "-b:a", "192k",
                        str(silence),
                    ],
                    check=True,
                    capture_output=True,
                )

                entries = []
                for i, name in enumerate(names):
                    entries.append(tmp / name)
                    if i < len(names) - 1:
                        entries.append(silence)

                list_path = tmp / "list.txt"
                with open(list_path, "w", encoding="utf-8") as handle:
                    for entry in entries:
                        escaped = str(entry.resolve()).replace("'", "'\\''")
                        handle.write(f"file '{escaped}'\n")

                merged = tmp / f"{page}.mp3"
                subprocess.run(
                    [
                        ff, "-y", "-f", "concat", "-safe", "0",
                        "-i", str(list_path), "-c", "copy", str(merged),
                    ],
                    check=True,
                    capture_output=True,
                )

                page_url = _upload(f"audio/pages/{page}.mp3", merged.read_bytes())

            body = json.dumps({"pageAudio": page_url}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            msg = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg)
