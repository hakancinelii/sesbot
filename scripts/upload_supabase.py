#!/usr/bin/env python3
"""Upload merged page MP3 files from output/ to Supabase Storage.

Requires environment variables:
- SUPABASE_URL (e.g. https://xyzcompany.supabase.co)
- SUPABASE_SERVICE_KEY (service_role key)
- SUPABASE_BUCKET (storage bucket name)

Usage: python3 scripts/upload_supabase.py --prefix audio/pages

The script will upload files named like `24.mp3`, `25.mp3` etc from `output/`.
On success it prints the public URL for each uploaded file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET")

if not SUPABASE_URL or not SUPABASE_KEY or not SUPABASE_BUCKET:
    sys.exit(
        "Missing env vars. Set SUPABASE_URL, SUPABASE_SERVICE_KEY and SUPABASE_BUCKET before running."
    )

STORAGE_UPLOAD = SUPABASE_URL.rstrip("/") + "/storage/v1/object/"


def upload_file(bucket: str, key: str, path: Path) -> str:
    url = STORAGE_UPLOAD + f"{bucket}/{key}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "x-upsert": "true",
    }
    # Read bytes and put
    with path.open("rb") as fh:
        resp = requests.put(url, headers=headers, data=fh)
    if not resp.ok:
        raise RuntimeError(f"Upload failed: {resp.status_code} {resp.text}")
    # Construct public URL
    public = SUPABASE_URL.rstrip("/") + f"/storage/v1/object/public/{bucket}/{key}"
    return public


def find_merged_pages(output_dir: Path) -> list[Path]:
    files = []
    for p in sorted(output_dir.iterdir()):
        if p.is_file() and p.name.endswith(".mp3") and p.name[:-4].isdigit():
            files.append(p)
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="audio/pages", help="Storage key prefix")
    args = parser.parse_args()

    pages = find_merged_pages(OUTPUT)
    if not pages:
        print("No merged page mp3 files found in output/ (files like 24.mp3)")
        return 1

    print(f"Found {len(pages)} merged page files, uploading to Supabase bucket '{SUPABASE_BUCKET}'...")
    results = []
    for p in pages:
        key = f"{args.prefix}/{p.name}"
        print(f"Uploading {p.name} -> {key} ...", end=" ")
        try:
            public = upload_file(SUPABASE_BUCKET, key, p)
            print("OK")
            print(public)
            results.append({"file": p.name, "url": public})
        except Exception as exc:
            print("FAILED")
            print(exc)

    # Optionally write a small manifest output
    out_manifest = OUTPUT / "supabase-uploads.json"
    out_manifest.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
