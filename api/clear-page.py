from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request

def _supabase_config():
    return {
        "url": os.environ.get("SUPABASE_URL", "").rstrip("/"),
        "key": os.environ.get("SUPABASE_SERVICE_KEY", "").strip(),
        "bucket": os.environ.get("SUPABASE_BUCKET", "audio").strip(),
    }


def _supabase_configured():
    cfg = _supabase_config()
    return bool(cfg["url"] and cfg["key"] and cfg["bucket"])


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


def _delete_files(keys):
    cfg = _supabase_config()
    req = urllib.request.Request(
        f"{cfg['url']}/storage/v1/object/{cfg['bucket']}",
        data=json.dumps({"prefixes": keys}).encode("utf-8"),
        method="DELETE",
        headers={
            "Authorization": f"Bearer {cfg['key']}",
            "apikey": cfg["key"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status


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

            deleted = []
            if _supabase_configured():
                prefix = f"audio/pages/{page}"
                names = [n for n in _list_files(prefix) if n.startswith(str(page))]
                if names:
                    keys = [f"audio/pages/{n}" for n in names]
                    _delete_files(keys)
                    deleted = names

            body = json.dumps({"deleted": deleted, "count": len(deleted)}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            msg = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(msg)
