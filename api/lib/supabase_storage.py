"""Supabase Storage yardimci modulu.

Ortam degiskenlerinden okur:
- SUPABASE_URL (orn. https://xyzcompany.supabase.co)
- SUPABASE_SERVICE_KEY (service_role key)
- SUPABASE_BUCKET (storage bucket adi, varsayilan: audio)

Ortam degiskenleri tanimli degilse is_configured() False doner ve
mevcut (Supabase'siz) akis bozulmadan devam eder.
"""

from __future__ import annotations

import json
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


def list_files(prefix: str = "") -> list[dict]:
    cfg = config()
    if not is_configured():
        raise RuntimeError("Supabase yapilandirilmadi (SUPABASE_URL/KEY/BUCKET eksik).")

    url = f"{cfg['url']}/storage/v1/object/list/{cfg['bucket']}"
    headers = {
        "Authorization": f"Bearer {cfg['key']}",
        "apikey": cfg["key"],
        "Content-Type": "application/json",
    }

    result: list[dict] = []
    offset = 0
    while True:
        payload = json.dumps(
            {"prefix": prefix, "limit": 1000, "offset": offset}
        ).encode("utf-8")
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                items = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase listeleme hatasi ({exc.code}): {detail}") from exc

        if not items:
            break
        result.extend(i for i in items if i.get("metadata") and i.get("name"))
        if len(items) < 1000:
            break
        offset += 1000
    return result


def file_urls(prefix: str = "") -> dict[str, str]:
    """Bucket icindeki dosyalari {dosya_adi: public_url} sozlugu olarak doner."""
    result: dict[str, str] = {}
    try:
        for item in list_files(prefix):
            name = item.get("name", "")
            if name:
                result[name] = public_url(f"{prefix}{name}")
    except RuntimeError:
        return {}
    return result
