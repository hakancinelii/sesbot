#!/usr/bin/env python3
"""Build + Vercel'e deploy (token ortam degiskeninden okunur)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    token = os.environ.get("VERCEL_TOKEN")
    if not token:
        raise SystemExit("VERCEL_TOKEN ortam degiskeni gerekli.")

    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_vercel.py")], check=True)

    node_paths = [
        "/tmp/node-v22.14.0-darwin-arm64/bin",
        "/tmp/node-v22.14.0-darwin-x64/bin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    env = os.environ.copy()
    env["PATH"] = ":".join(node_paths + [env.get("PATH", "")])
    env["VERCEL_TOKEN"] = token

    subprocess.run(
        ["npx", "--yes", "vercel", "deploy", "--prod", "--yes"],
        cwd=ROOT / "public",
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
