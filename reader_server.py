#!/usr/bin/env python3
"""Sesli kitap okuyucu arayuzu icin yerel sunucu."""

from __future__ import annotations

import argparse
import json
import mimetypes
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from sesbot import extract_paragraphs, VoxCPMClient, Paragraph, merge_page_audio

ROOT = Path(__file__).parent
READER_DIR = ROOT / "reader"
OUTPUT_DIR = ROOT / "output"
DEFAULT_PDF = ROOT / "Dan-Brown-Sirlarin-Sirri.pdf"
MANIFEST_FILE = ROOT / "manifest-runtime.json"


def load_runtime_manifest() -> dict | None:
    if not MANIFEST_FILE.exists():
        return None
    try:
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[okuyucu] Runtime manifest yuklenemedi: {exc}")
        return None


def build_manifest(pdf_path: Path, output_dir: Path) -> dict:
    paragraphs = extract_paragraphs(pdf_path)
    pages: dict[str, list[dict]] = {}

    for paragraph in paragraphs:
        page_key = str(paragraph.book_page)
        audio_name = paragraph.filename
        audio_path = output_dir / audio_name
        page_merged = output_dir / f"{paragraph.book_page}.mp3"

        pages.setdefault(page_key, []).append(
            {
                "index": paragraph.index_on_page,
                "text": paragraph.text,
                "audio": f"/audio/{audio_name}" if audio_path.exists() else None,
                "available": audio_path.exists(),
                "heading": paragraph.heading,
            }
        )

    available_pages = sorted(
        int(page)
        for page, items in pages.items()
        if any(item["available"] for item in items)
    )

    return {
        "title": pdf_path.stem,
        "pages": pages,
        "availablePages": available_pages,
        "pageAudio": {
            str(page): f"/audio/{page}.mp3"
            for page in available_pages
            if (output_dir / f"{page}.mp3").exists()
        },
    }


class ReaderHandler(BaseHTTPRequestHandler):
    manifest: dict = {}
    output_dir: Path = OUTPUT_DIR
    pdf_path: Path = DEFAULT_PDF

    def log_message(self, format: str, *args) -> None:
        print(f"[okuyucu] {self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path in ("/api/manifest", "/manifest.json"):
            self._send_json(self.manifest)
            return

        if path.startswith("/audio/"):
            filename = Path(path.removeprefix("/audio/")).name
            audio_path = self.output_dir / filename
            if not audio_path.exists() or audio_path.parent.resolve() != self.output_dir.resolve():
                self.send_error(404)
                return
            content = audio_path.read_bytes()
            content_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
            return

        if path in ("", "/"):
            target = READER_DIR / "index.html"
        else:
            target = READER_DIR / path.lstrip("/")

        if not target.exists() or not target.is_file():
            self.send_error(404)
            return

        content = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/generate":
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                text = data.get('text', '').strip()

                if not text:
                    self.send_error(400, "No text provided")
                    return

                print(f"[okuyucu] /api/generate istegi alindi: {text[:50]}...")
                client = VoxCPMClient(cfg_value=2.0)
                
                ref_path = ROOT / "amazon_reference_50s.mp3"
                if not ref_path.exists():
                    self.send_error(500, "Referans ses bulunamadi")
                    return

                client.upload_reference(ref_path)
                result = client.generate(text)
                
                # Sesi indir ve HTTP ile dön
                import requests
                url = result.get("url")
                if not url:
                    url = f"{client.space_url}/gradio_api/file={result['path']}"

                audio_resp = requests.get(url, timeout=120)
                audio_resp.raise_for_status()
                audio_bytes = audio_resp.content

                page = data.get("page")
                paragraph_index = data.get("paragraphIndex")
                generated_path = None
                if page is not None and isinstance(paragraph_index, int):
                    page_key = str(page).replace("/", "_")
                    file_name = f"{page_key}_{paragraph_index + 1}.mp3"
                    save_path = self.output_dir / file_name
                    save_path.write_bytes(audio_bytes)
                    generated_path = f"/audio/{file_name}"
                    print(f"[okuyucu] Ses kaydedildi: {save_path}")

                    page_str = str(page)
                    paragraph_list = self.manifest.get("pages", {}).get(page_str)
                    if paragraph_list and 0 <= paragraph_index < len(paragraph_list):
                        paragraph_list[paragraph_index]["audio"] = generated_path
                        paragraph_list[paragraph_index]["available"] = True
                        if page_str not in map(str, self.manifest.get("availablePages", [])):
                            self.manifest.setdefault("availablePages", []).append(int(page_str))
                            self.manifest["availablePages"] = sorted(self.manifest["availablePages"])

                self._persist_manifest()
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(audio_bytes)))
                if generated_path is not None:
                    self.send_header("X-Generated-Audio-Path", generated_path)
                self.end_headers()
                self.wfile.write(audio_bytes)
                print(f"[okuyucu] Ses uretildi ve donduruldu.")

            except Exception as e:
                self.send_error(500, str(e))
            return

        if path == "/api/merge-page":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode("utf-8"))
                page = data.get("page")
                if not isinstance(page, int):
                    self.send_error(400, "Sayfa numarasi gerekli")
                    return

                page_key = str(page)
                paragraph_list = self.manifest.get("pages", {}).get(page_key)
                if not paragraph_list:
                    self.send_error(404, "Sayfa bulunamadi")
                    return

                missing_files = [
                    self.output_dir / f"{page}_{p['index']}.mp3"
                    for p in paragraph_list
                    if not (self.output_dir / f"{page}_{p['index']}.mp3").exists()
                ]
                if missing_files:
                    self.send_error(400, "Sayfa icin tum paragraf sesleri yok")
                    return

                paragraph_objects = [
                    Paragraph(book_page=page, index_on_page=p["index"], text=p["text"])
                    for p in paragraph_list
                ]
                merged_path = merge_page_audio(
                    self.output_dir,
                    page,
                    paragraph_objects,
                    pause_ms=1500,
                    force=True,
                )

                merged_url = f"/audio/{merged_path.name}"
                self.manifest.setdefault("pageAudio", {})[page_key] = merged_url
                self._persist_manifest()
                self._send_json({"pageAudio": merged_url})
            except Exception as e:
                self.send_error(500, str(e))
            return

        if path == "/api/clear-page":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode("utf-8"))
                page = data.get("page")
                if not isinstance(page, int):
                    self.send_error(400, "Sayfa numarasi gerekli")
                    return

                deleted = []
                for file_path in sorted(self.output_dir.glob(f"{page}_*.mp3")):
                    file_path.unlink(missing_ok=True)
                    deleted.append(file_path.name)
                merged = self.output_dir / f"{page}.mp3"
                if merged.exists():
                    merged.unlink()
                    deleted.append(merged.name)

                self._send_json({"deleted": deleted, "count": len(deleted)})
            except Exception as e:
                self.send_error(500, str(e))
            return

        self.send_error(404)

    def _send_json(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _persist_manifest(self) -> None:
        try:
            MANIFEST_FILE.write_text(
                json.dumps(self.manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[okuyucu] Runtime manifest kaydedildi: {MANIFEST_FILE}")
        except Exception as exc:
            print(f"[okuyucu] Runtime manifest kaydedilemedi: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sesli kitap okuyucu sunucusu")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.pdf.exists():
        raise SystemExit(f"PDF bulunamadi: {args.pdf}")

    runtime_manifest = load_runtime_manifest()
    if runtime_manifest is not None:
        print(f"[okuyucu] Runtime manifest yuklendi: {MANIFEST_FILE}")
        ReaderHandler.manifest = runtime_manifest
    else:
        ReaderHandler.manifest = build_manifest(args.pdf, args.output)

    ReaderHandler.output_dir = args.output.resolve()
    url = f"http://{args.host}:{args.port}"
    print(f"Okuyucu acildi: {url}")
    print(f"Hazir sayfalar: {ReaderHandler.manifest['availablePages']}")

    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSunucu kapatildi.")


if __name__ == "__main__":
    main()
