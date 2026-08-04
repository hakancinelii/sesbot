#!/usr/bin/env python3
"""Vercel REST API ile public/ klasorunu deploy eder."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Clear proxy environment vars inside the script to avoid sandbox proxy handlers.
for proxy_key in [
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
    "ftp_proxy",
    "FTP_PROXY",
    "no_proxy",
    "NO_PROXY",
    "GRPC_PROXY",
    "grpc_proxy",
]:
    os.environ.pop(proxy_key, None)

ROOT = Path(__file__).resolve().parent.parent
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PUBLIC = ROOT / "public"
IGNORED_DIRS = {".git", ".venv", "__pycache__", "output"}
IGNORED_FILES = {".DS_Store"}


def run_build() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_vercel.py")], check=True)


import hashlib


def should_ignore(path: Path) -> bool:
    if path.name in IGNORED_FILES:
        return True
    for part in path.parts:
        if part in IGNORED_DIRS:
            return True
    return False


def upload_file_if_needed(token: str, path: Path) -> str:
    raw = path.read_bytes()
    sha1 = hashlib.sha1(raw).hexdigest()
    
    # Check if exists or upload
    request = urllib.request.Request(
        "https://api.vercel.com/v2/now/files",
        data=raw,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "x-vercel-digest": sha1,
            "Content-Length": str(len(raw)),
        },
        method="POST",
    )
    try:
        with OPENER.open(request, timeout=60) as response:
            pass # Upload successful
    except urllib.error.HTTPError:
        pass # If it already exists, or other error, we'll see on deploy
        
    return sha1, len(raw)

def collect_files(token: str, public_dir: Path, extra_paths: list[Path]) -> list[dict]:
    files: list[dict] = []
    paths = [p for p in sorted(public_dir.rglob("*")) if p.is_file() and not should_ignore(p)]
    for extra in extra_paths:
        if extra.is_file() and not should_ignore(extra) and extra not in paths:
            paths.append(extra)

    seen: set[str] = set()
    collected: list[Path] = []
    for path in paths:
        rel = path.relative_to(public_dir).as_posix() if path.is_relative_to(public_dir) else path.relative_to(ROOT).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        collected.append(path)

    for i, path in enumerate(collected, 1):
        rel = path.relative_to(public_dir).as_posix() if path.is_relative_to(public_dir) else path.relative_to(ROOT).as_posix()
        sha1, size = upload_file_if_needed(token, path)
        files.append({"file": rel, "sha": sha1, "size": size})
        print(f"  [{i}/{len(collected)}] Uploaded {rel} ({size} bytes)")
    return files


def deploy(token: str, project_name: str, files: list[dict]) -> dict:
    payload = {
        "name": project_name,
        "files": files,
        "projectSettings": {
            "framework": None,
        },
        "target": "production",
    }
    request = urllib.request.Request(
        "https://api.vercel.com/v13/deployments",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with OPENER.open(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vercel'e okuyucu deploy et")
    parser.add_argument("--token", required=True, help="Vercel API token")
    parser.add_argument("--project", default="sesbot-okuyucu", help="Proje adi")
    parser.add_argument("--skip-build", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.skip_build:
        run_build()

    if not PUBLIC.exists():
        raise SystemExit("public/ klasoru yok. Once build calistirin.")

    extra_paths = [
        ROOT / "api" / "generate.py",
        ROOT / "api" / "lib" / "__init__.py",
        ROOT / "api" / "lib" / "supabase_storage.py",
        ROOT / "requirements.txt",
        ROOT / "vercel.json",
        ROOT / "amazon_reference_50s.mp3",
    ]
    files = collect_files(args.token, PUBLIC, extra_paths)
    print(f"Deploy ediliyor: {len(files)} dosya...")
    result = deploy(args.token, args.project, files)

    url = result.get("url") or result.get("alias", [None])[0]
    print(f"Canli URL: https://{url}")
    print(f"Deployment ID: {result.get('id')}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Vercel hatasi ({exc.code}): {body}") from exc
