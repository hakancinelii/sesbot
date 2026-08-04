"""Supabase Storage yardimci modulu.

Ortam degiskenlerinden okur:
- SUPABASE_URL (orn. https://xyzcompany.supabase.co)
- SUPABASE_SERVICE_KEY (service_role key)
- SUPABASE_BUCKET (storage bucket adi, varsayilan: audio)

Ortam degiskenleri tanimli degilse is_configured() False doner ve
mevcut (Supabase'siz) akis bozulmadan devam eder.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

DEFAULT_BUCKET = "audio"


def config() -> dict:
    return {
        "url": os.environ.get("SUPABASE_URL", "").rstrip("/"),
        "key": os.environ.get("SUPABASE_SERVICE_KEY", "").strip(),
        "bucket": os.environ.get("SUPABASE_BUCKET", DEFAULT_BUCKET).strip(),
    }


def is_configured() -> bool:
    cfg = config()
    return bool(cfg["url"] and cfg["key"] and cfg["bucket"])


def public_url(key: str) -> str:
    cfg = config()
    return f"{cfg['url']}/storage/v1/object/public/{cfg['bucket']}/{key}"


def upload_bytes(key: str, data: bytes, content_type: str = "audio/mpeg") -> str:
    cfg = config()
    if not is_configured():
        raise RuntimeError("Supabase yapilandirilmadi (SUPABASE_URL/KEY/BUCKET eksik).")

    url = f"{cfg['url']}/storage/v1/object/{cfg['bucket']}/{key}"
    headers = {
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    request = urllib.request.Request(url, data=data, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=120) as _resp:
            return public_url(key)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase yukleme hatasi ({exc.code}): {detail}") from exc


def upload_file(key: str, path: str, content_type: str = "audio/mpeg") -> str:
    with open(path, "rb") as handle:
        data = handle.read()
    return upload_bytes(key, data, content_type=content_type)
