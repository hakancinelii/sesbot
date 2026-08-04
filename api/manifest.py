from http.server import BaseHTTPRequestHandler
import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PDF = os.path.join(os.path.dirname(__file__), "..", "Dan-Brown-Sirlarin-Sirri.pdf")

_pages_cache = None


def _supabase_config():
    return {
        "url": os.environ.get("SUPABASE_URL", "").rstrip("/"),
        "key": os.environ.get("SUPABASE_SERVICE_KEY", "").strip(),
        "bucket": os.environ.get("SUPABASE_BUCKET", "audio").strip(),
    }


def _supabase_configured():
    cfg = _supabase_config()
    return bool(cfg["url"] and cfg["key"] and cfg["bucket"])


def _supabase_audio_urls():
    """Supabase bucket icindeki sesleri {dosya_adi: public_url} olarak doner."""
    import urllib.request

    cfg = _supabase_config()
    url = f"{cfg['url']}/storage/v1/object/list/{cfg['bucket']}"
    payload = json.dumps({"prefix": "audio/pages/", "limit": 1000, "offset": 0}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {cfg['key']}",
        "apikey": cfg["key"],
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            items = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}

    result = {}
    for item in items:
        name = item.get("name")
        if name:
            result[name] = (
                f"{cfg['url']}/storage/v1/object/public/{cfg['bucket']}/audio/pages/{name}"
            )
    return result


def _get_pages():
    global _pages_cache
    if _pages_cache is not None:
        return _pages_cache
    from sesbot import extract_paragraphs

    pages = {}
    for paragraph in extract_paragraphs(PDF):
        key = str(paragraph.book_page)
        pages.setdefault(key, []).append(
            {
                "index": paragraph.index_on_page,
                "text": paragraph.text,
                "audio": None,
                "available": False,
                "heading": paragraph.heading,
            }
        )
    _pages_cache = pages
    return pages


def _build_manifest():
    pages = copy.deepcopy(_get_pages())
    url_map = _supabase_audio_urls()

    for page_key, items in pages.items():
        for item in items:
            name = f"{page_key}_{item['index']}.mp3"
            if name in url_map:
                item["audio"] = url_map[name]
                item["available"] = True

    available_pages = sorted(
        int(page)
        for page, items in pages.items()
        if any(item["available"] for item in items)
    )
    page_audio = {}
    for page in available_pages:
        name = f"{page}.mp3"
        if name in url_map:
            page_audio[str(page)] = url_map[name]

    return {
        "title": "Dan-Brown-Sirlarin-Sirri",
        "pages": pages,
        "availablePages": available_pages,
        "pageAudio": page_audio,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            manifest = _build_manifest()
        except Exception as exc:
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))
            return

        body = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
