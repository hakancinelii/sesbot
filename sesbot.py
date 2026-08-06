#!/usr/bin/env python3
"""PDF kitap paragraf seslendirme botu - VoxCPM Demo."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import fitz

VOXCPM_SPACE = "https://openbmb-voxcpm-demo.hf.space"
SOFT_HYPHEN = "\u00ad"
SENTENCE_END = re.compile(r'[.!?\u2026]["\']?\s*$')
STARTS_PARAGRAPH = re.compile(r'^[A-Z\u00c7\u011e\u0130\u00d6\u015e\u00dc"\u00ab(]')


@dataclass
class Paragraph:
    book_page: int
    index_on_page: int
    text: str
    heading: bool = False

    @property
    def filename(self) -> str:
        return f"{self.book_page}_{self.index_on_page}.mp3"


def merge_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    merged: list[str] = []
    buffer = ""
    prev_had_soft_hyphen = False

    for raw_line in lines:
        had_trailing_soft = raw_line.endswith(SOFT_HYPHEN)
        line = raw_line.replace(SOFT_HYPHEN, "")

        if not buffer:
            buffer = line
            prev_had_soft_hyphen = had_trailing_soft
            continue

        if prev_had_soft_hyphen or buffer.endswith("-"):
            buffer = buffer.rstrip("-") + line
        elif not SENTENCE_END.search(buffer):
            buffer = f"{buffer} {line}"
        else:
            merged.append(buffer)
            buffer = line

        prev_had_soft_hyphen = had_trailing_soft

    if buffer:
        merged.append(buffer)
    return merged


def split_paragraphs(text: str) -> list[str]:
    parts = merge_lines(text)
    paragraphs: list[str] = []
    buffer = ""

    for part in parts:
        if not buffer:
            buffer = part
            continue

        if SENTENCE_END.search(buffer) and STARTS_PARAGRAPH.match(part):
            paragraphs.append(buffer.strip())
            buffer = part
        else:
            buffer = f"{buffer} {part}"

    if buffer.strip():
        paragraphs.append(buffer.strip())
    return paragraphs


def is_noise(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned or cleaned == "*":
        return True
    if re.fullmatch(r"\d{1,4}", cleaned):
        return True
    if len(cleaned) < 20:
        return True
    return False


def get_printed_page_number(page: fitz.Page) -> Optional[int]:
    candidates: list[int] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        text = "".join(
            span["text"]
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        ).strip()
        bbox = block["bbox"]
        if re.fullmatch(r"\d{1,4}", text) and bbox[1] > page.rect.height * 0.8:
            candidates.append(int(text))
    return candidates[0] if candidates else None


def join_paragraph_text(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    if left.endswith("-"):
        return left[:-1] + right
    return f"{left} {right}"


def ends_incomplete(text: str) -> bool:
    cleaned = text.rstrip()
    if cleaned.endswith("-"):
        return True
    return not SENTENCE_END.search(cleaned)


def starts_continuation(text: str) -> bool:
    cleaned = text.lstrip()
    if not cleaned:
        return False
    return not bool(STARTS_PARAGRAPH.match(cleaned))


def merge_cross_page_paragraphs(paragraphs: list[Paragraph]) -> list[Paragraph]:
    if not paragraphs:
        return []

    merged: list[Paragraph] = []
    index = 0
    while index < len(paragraphs):
        current = paragraphs[index]
        next_index = index + 1

        while next_index < len(paragraphs):
            nxt = paragraphs[next_index]
            if nxt.book_page != current.book_page + (next_index - index):
                break
            if not ends_incomplete(current.text):
                break
            if not starts_continuation(nxt.text):
                break

            current = Paragraph(
                book_page=current.book_page,
                index_on_page=current.index_on_page,
                text=join_paragraph_text(current.text, nxt.text),
            )
            next_index += 1

        merged.append(current)
        index = next_index

    counters: dict[int, int] = {}
    renumbered: list[Paragraph] = []
    for paragraph in merged:
        counters[paragraph.book_page] = counters.get(paragraph.book_page, 0) + 1
        renumbered.append(
            Paragraph(
                book_page=paragraph.book_page,
                index_on_page=counters[paragraph.book_page],
                text=paragraph.text,
            )
        )
    return renumbered


CHAR_MAP = {
    0x0262: "ı",
    0x1BA1: "A",
    0x1BF4: "ş",
    0x1BF8: "e",
    0x1BF9: "ş",
    0x1BFA: "u",
    0x1BFB: "e",
    0x1BFC: "",
    0x1BFD: "s",
    0x1BFE: "r",
    0x1BFF: "",
    0x1C00: "r",
    0x1C01: "m",
    0x1C02: "k",
    0x1C03: "t",
    0x1C04: "r",
    0x1C05: "a",
    0x1C06: "m",
    0x1C07: "n",
    0x1C08: "k",
    0x1C09: "r",
    0x1C0A: "ğ",
    0x1C0B: "e",
    0x1C0C: "h",
    0x1C0D: "ı",
}


def clean_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    cleaned = []
    for char in normalized:
        if char == SOFT_HYPHEN:
            continue
        cp = ord(char)
        if cp in CHAR_MAP:
            cleaned.append(CHAR_MAP[cp])
            continue
        category = unicodedata.category(char)
        if category.startswith("C"):
            continue
        cleaned.append(char)
    return "".join(cleaned)


def join_spans(spans: list[dict]) -> str:
    line_text = ""
    for span in spans:
        part = clean_text(span["text"])
        if line_text and not line_text[-1].isspace() and not line_text.endswith("-") and part and not part[0].isspace():
            line_text += " "
        line_text += part
    return line_text


def extract_page_blocks(doc: fitz.Document, pdf_index: int) -> list[str]:
    blocks: list[str] = []
    for block in doc[pdf_index].get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        block_text = "\n".join(
            join_spans(line.get("spans", []))
            for line in block.get("lines", [])
        )
        for paragraph in split_paragraphs(block_text):
            if not is_noise(paragraph):
                blocks.append(paragraph)
    return blocks


OCR_TEXT_NAME = "ocr_pages.json"

OCR_ARTIFACT_MAP = {
    0x0219: "ş",  # s with comma (Vision Roman artifact)
    0x0218: "Ş",
    0x021B: "t",  # t with comma
    0x021A: "T",
    0x00A0: " ",  # non-breaking space
    0x2019: "'",  # right single quote
    0x2018: "'",
    0x201C: '"',
    0x201D: '"',
}


def clean_ocr_text(text: str) -> str:
    out: list[str] = []
    for char in text:
        if char in "\n\r":
            out.append(char)
            continue
        cp = ord(char)
        if cp in OCR_ARTIFACT_MAP:
            out.append(OCR_ARTIFACT_MAP[cp])
            continue
        category = unicodedata.category(char)
        if category.startswith("C"):
            continue
        out.append(char)
    return "".join(out)


def find_ocr_text() -> Optional[Path]:
    candidates = [
        Path(__file__).resolve().parent / "ocr_text" / OCR_TEXT_NAME,
        Path("/var/task") / "ocr_text" / OCR_TEXT_NAME,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


CHAPTER_HEADING_RE = re.compile(r"^\d{1,3}\.\s*BÖLÜM$", re.IGNORECASE)
STANDALONE_HEADINGS = {"ÖNSÖZ", "SONSÖZ", "EPİLOG", "EPILOG", "PROLOG", "PROLOGUE"}


def is_chapter_heading(line: str) -> bool:
    s = line.strip().strip("\"'").strip()
    if not s:
        return False
    if CHAPTER_HEADING_RE.match(s):
        return True
    return s.upper() in STANDALONE_HEADINGS


def front_matter_pages() -> list[Paragraph]:
    """Kitabin on sayfalarini (kapak, kunye, ithaf vb.) sozde sayfa numaralariyla dondurur.

    OCR'da book_page olmayan ilk sayfalar (PDF 0-7) sirasiyla 1..8
    sayfalarina eslenir; kitap govdesi 9'dan baslar.
    """
    ocr_path = find_ocr_text()
    if ocr_path is None:
        return []
    data = json.loads(ocr_path.read_text(encoding="utf-8"))

    result: list[Paragraph] = []
    pseudo_page = 1
    for pdf_index in sorted(data, key=lambda k: int(k)):
        entry = data[pdf_index]
        if entry.get("book_page") is not None:
            break
        text = entry.get("text", "")
        if not text.strip():
            pseudo_page += 1
            continue
        page_text = clean_ocr_text(text)
        page_text = re.sub(r"\s+\d{1,4}\s*$", "", page_text.rstrip())
        for index, para in enumerate(split_paragraphs(page_text), start=1):
            if not is_noise(para):
                result.append(
                    Paragraph(book_page=pseudo_page, index_on_page=index, text=para)
                )
        pseudo_page += 1
    return result


def extract_paragraphs_from_ocr(
    ocr_path: Path,
    start_page: int = 1,
    end_page: Optional[int] = None,
) -> list[Paragraph]:
    data = json.loads(ocr_path.read_text(encoding="utf-8"))

    pages: dict[int, str] = {}
    headings: dict[int, str] = {}
    for pdf_index, entry in data.items():
        book_page = entry.get("book_page")
        text = entry.get("text", "")
        if book_page is None or not text.strip():
            continue
        page_text = clean_ocr_text(text)
        page_text = re.sub(r"\s+\d{1,4}\s*$", "", page_text.rstrip())

        body_lines: list[str] = []
        for line in page_text.splitlines():
            if book_page not in headings and is_chapter_heading(line):
                headings[book_page] = line.strip().strip("\"'").strip()
            else:
                body_lines.append(line)
        pages[book_page] = "\n".join(body_lines)

    last_page = end_page or max(pages)
    merge_start = max(1, start_page - 1)

    raw_paragraphs: list[Paragraph] = []
    for book_page in sorted(pages):
        if book_page < merge_start or book_page > last_page:
            continue
        for index, text in enumerate(split_paragraphs(pages[book_page]), start=1):
            if not is_noise(text):
                raw_paragraphs.append(
                    Paragraph(book_page=book_page, index_on_page=index, text=text)
                )

    merged = merge_cross_page_paragraphs(raw_paragraphs)

    body_by_page: dict[int, list[Paragraph]] = {}
    for paragraph in merged:
        body_by_page.setdefault(paragraph.book_page, []).append(paragraph)

    final: list[Paragraph] = []
    if start_page <= 1:
        final.extend(front_matter_pages())
    all_pages = sorted(set(pages) | set(body_by_page))
    for book_page in all_pages:
        if book_page < start_page or book_page > last_page:
            continue
        if book_page in headings:
            final.append(
                Paragraph(
                    book_page=book_page,
                    index_on_page=0,
                    text=headings[book_page],
                    heading=True,
                )
            )
        final.extend(body_by_page.get(book_page, []))
    return final


def extract_paragraphs(
    pdf_path: Path,
    start_page: int = 1,
    end_page: Optional[int] = None,
) -> list[Paragraph]:
    ocr_path = find_ocr_text()
    if ocr_path is not None:
        try:
            return extract_paragraphs_from_ocr(ocr_path, start_page, end_page)
        except Exception as exc:
            print(f"OCR metin kullanilamadi, PDF katmanina geciliyor: {exc}")

    doc = fitz.open(pdf_path)
    last_page = end_page or max(
        get_printed_page_number(doc[i]) or 0 for i in range(doc.page_count)
    )

    page_map: dict[int, int] = {}
    for pdf_index in range(doc.page_count):
        book_page = get_printed_page_number(doc[pdf_index])
        if book_page is not None:
            page_map[book_page] = pdf_index

    raw_paragraphs: list[Paragraph] = []
    merge_start = max(1, start_page - 1)

    for book_page in sorted(page_map):
        if book_page < merge_start or book_page > last_page:
            continue

        for index, text in enumerate(extract_page_blocks(doc, page_map[book_page]), start=1):
            raw_paragraphs.append(
                Paragraph(book_page=book_page, index_on_page=index, text=text)
            )

    doc.close()
    merged = merge_cross_page_paragraphs(raw_paragraphs)
    return [p for p in merged if start_page <= p.book_page <= last_page]


class VoxCPMClient:
    def __init__(
        self,
        space_url: str = VOXCPM_SPACE,
        cfg_value: float = 2.0,
        denoise: bool = False,
        normalize: bool = False,
        ultimate_cloning: bool = False,
        control_instruction: str = "",
        prompt_text: str = "",
    ) -> None:
        self.space_url = space_url.rstrip("/")
        self.cfg_value = cfg_value
        self.denoise = denoise
        self.normalize = normalize
        self.ultimate_cloning = ultimate_cloning
        self.control_instruction = control_instruction
        self.prompt_text = prompt_text
        try:
            import requests

            self.session = requests.Session()
        except Exception:
            # Minimal requests-like shim using urllib for environments
            # where `requests` cannot be installed.
            import urllib.request
            import urllib.parse
            import json as _json
            import io as _io
            import mimetypes as _mimetypes
            import uuid as _uuid

            class _SimpleResponse:
                def __init__(self, resp):
                    self._resp = resp

                def raise_for_status(self):
                    status = getattr(self._resp, 'status', None)
                    if status is None:
                        return
                    if status >= 400:
                        raise RuntimeError(f'HTTP {status}')

                def json(self):
                    data = self._resp.read()
                    try:
                        return _json.loads(data.decode('utf-8'))
                    except Exception:
                        return _json.loads(data)

                def iter_lines(self, decode_unicode=True):
                    # Stream line-by-line (SSE)
                    while True:
                        line = self._resp.readline()
                        if not line:
                            break
                        if decode_unicode:
                            yield line.decode('utf-8', errors='ignore')
                        else:
                            yield line

                @property
                def content(self):
                    return self._resp.read()

            class _SimpleSession:
                def __init__(self):
                    pass

                def _build_multipart(self, files: dict):
                    boundary = '----WebKitFormBoundary' + _uuid.uuid4().hex
                    body = _io.BytesIO()
                    for name, (filename, handle, content_type) in files.items():
                        body.write((f'--{boundary}\r\n').encode('utf-8'))
                        body.write((f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n').encode('utf-8'))
                        body.write((f'Content-Type: {content_type or _mimetypes.guess_type(filename)[0] or "application/octet-stream"}\r\n\r\n').encode('utf-8'))
                        body.write(handle.read())
                        body.write(b"\r\n")
                    body.write((f'--{boundary}--\r\n').encode('utf-8'))
                    return boundary, body.getvalue()

                def post(self, url, files=None, json=None, timeout=None):
                    if files is not None:
                        boundary, data = self._build_multipart(files)
                        req = urllib.request.Request(url, data=data)
                        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
                        resp = urllib.request.urlopen(req, timeout=timeout)
                        return _SimpleResponse(resp)
                    if json is not None:
                        data = _json.dumps(json).encode('utf-8')
                        req = urllib.request.Request(url, data=data)
                        req.add_header('Content-Type', 'application/json')
                        resp = urllib.request.urlopen(req, timeout=timeout)
                        return _SimpleResponse(resp)
                    # fallback
                    req = urllib.request.Request(url)
                    resp = urllib.request.urlopen(req, timeout=timeout)
                    return _SimpleResponse(resp)

                def get(self, url, stream=False, timeout=None):
                    req = urllib.request.Request(url)
                    resp = urllib.request.urlopen(req, timeout=timeout)
                    # resp is a file-like object; wrap to expose .readline and .read
                    return _SimpleResponse(resp)

            self.session = _SimpleSession()
        self._reference_file: Optional[dict] = None

    def upload_reference(self, reference_path: Path) -> dict:
        with reference_path.open("rb") as handle:
            response = self.session.post(
                f"{self.space_url}/gradio_api/upload",
                files={"files": (reference_path.name, handle, "audio/mpeg")},
                timeout=120,
            )
        response.raise_for_status()
        uploaded_path = response.json()[0]
        self._reference_file = {
            "path": uploaded_path,
            "url": f"{self.space_url}/gradio_api/file={uploaded_path}",
            "orig_name": reference_path.name,
            "size": reference_path.stat().st_size,
            "mime_type": "audio/mpeg",
            "meta": {"_type": "gradio.FileData"},
        }
        return self._reference_file

    def generate(self, text: str, timeout_seconds: int = 300) -> dict:
        if self._reference_file is None:
            raise RuntimeError("Referans ses yuklenmedi.")

        payload = {
            "data": [
                text,
                self.control_instruction,
                self._reference_file,
                self.ultimate_cloning,
                self.prompt_text if self.ultimate_cloning else "",
                self.cfg_value,
                self.normalize,
                self.denoise,
            ]
        }

        response = self.session.post(
            f"{self.space_url}/gradio_api/call/generate",
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        event_id = response.json()["event_id"]

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            stream = self.session.get(
                f"{self.space_url}/gradio_api/call/generate/{event_id}",
                stream=True,
                timeout=timeout_seconds,
            )
            stream.raise_for_status()

            event_name = ""
            data_lines: list[str] = []
            for raw_line in stream.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                if raw_line.startswith("event:"):
                    event_name = raw_line.split(":", 1)[1].strip()
                elif raw_line.startswith("data:"):
                    data_lines.append(raw_line.split(":", 1)[1].strip())

            if event_name == "complete":
                if not data_lines:
                    raise RuntimeError("API tamamlandi ama veri donmedi.")
                result = json.loads(data_lines[0])
                if not result:
                    raise RuntimeError("Bos sonuc dondu.")
                return result[0]
            if event_name == "error":
                detail = data_lines[0] if data_lines else "Bilinmeyen API hatasi"
                raise RuntimeError(detail)

            time.sleep(2)

        raise TimeoutError("VoxCPM yanit vermedi.")

    def download_audio(self, file_info: dict, destination: Path) -> None:
        url = file_info.get("url")
        if not url:
            url = f"{self.space_url}/gradio_api/file={file_info['path']}"

        response = self.session.get(url, timeout=120)
        response.raise_for_status()
        destination.write_bytes(response.content)


def group_paragraphs_by_page(paragraphs: list[Paragraph]) -> dict[int, list[Paragraph]]:
    grouped: dict[int, list[Paragraph]] = {}
    for paragraph in paragraphs:
        grouped.setdefault(paragraph.book_page, []).append(paragraph)
    return grouped


def find_ffmpeg() -> Optional[str]:
    for candidate in (
        shutil.which("ffmpeg"),
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ):
        if candidate and Path(candidate).exists():
            return candidate

    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).exists():
            return bundled
    except Exception:
        pass

    return None


def get_silence_file(output_dir: Path, pause_ms: int, ffmpeg: str) -> Path:
    silence_path = output_dir / f".silence_{pause_ms}ms.mp3"
    if silence_path.exists():
        return silence_path

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=mono:sample_rate=48000",
            "-t",
            str(pause_ms / 1000.0),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(silence_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return silence_path


def merge_page_audio(
    output_dir: Path,
    book_page: int,
    page_paragraphs: list[Paragraph],
    pause_ms: int = 1500,
    force: bool = False,
) -> Path:
    paragraph_files = [output_dir / paragraph.filename for paragraph in page_paragraphs]
    missing = [path.name for path in paragraph_files if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Sayfa {book_page} icin eksik dosyalar: {', '.join(missing)}"
        )

    destination = output_dir / f"{book_page}.mp3"
    merge_meta_path = output_dir / f".{book_page}.merge.json"
    merge_meta = {
        "pause_ms": pause_ms,
        "sources": [path.name for path in paragraph_files],
    }
    latest_source_mtime = max(path.stat().st_mtime for path in paragraph_files)

    if not force and destination.exists() and merge_meta_path.exists():
        try:
            saved_meta = json.loads(merge_meta_path.read_text(encoding="utf-8"))
            if (
                saved_meta.get("pause_ms") == pause_ms
                and saved_meta.get("sources") == merge_meta["sources"]
                and destination.stat().st_mtime >= latest_source_mtime
            ):
                return destination
        except (json.JSONDecodeError, OSError):
            pass

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        concat_entries: list[Path] = []
        silence_path: Optional[Path] = None
        if pause_ms > 0:
            silence_path = get_silence_file(output_dir, pause_ms, ffmpeg)

        for index, path in enumerate(paragraph_files):
            concat_entries.append(path)
            if pause_ms > 0 and silence_path and index < len(paragraph_files) - 1:
                concat_entries.append(silence_path)

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            list_path = Path(handle.name)
            for path in concat_entries:
                escaped = str(path.resolve()).replace("'", "'\\''")
                handle.write(f"file '{escaped}'\n")

        try:
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_path),
                    "-c",
                    "copy",
                    str(destination),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        finally:
            list_path.unlink(missing_ok=True)

        merge_meta_path.write_text(
            json.dumps(merge_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    elif pause_ms > 0:
        print(
            f"Uyari: ffmpeg bulunamadi, sayfa {book_page} duraksama olmadan birlestirildi.",
            file=sys.stderr,
        )
        with destination.open("wb") as handle:
            for path in paragraph_files:
                handle.write(path.read_bytes())
    else:
        with destination.open("wb") as handle:
            for path in paragraph_files:
                handle.write(path.read_bytes())

    return destination


def merge_existing_pages(
    output_dir: Path,
    paragraphs: list[Paragraph],
    pause_ms: int = 1500,
    force: bool = False,
) -> None:
    grouped = group_paragraphs_by_page(paragraphs)
    for book_page in sorted(grouped):
        page_paragraphs = grouped[book_page]
        paragraph_files = [output_dir / paragraph.filename for paragraph in page_paragraphs]
        if not all(path.exists() for path in paragraph_files):
            missing = [path.name for path in paragraph_files if not path.exists()]
            print(f"Sayfa {book_page} atlandi, eksik dosyalar: {', '.join(missing)}")
            continue
        merged = merge_page_audio(
            output_dir,
            book_page,
            page_paragraphs,
            pause_ms=pause_ms,
            force=force,
        )
        pause_note = f" ({pause_ms}ms ara)" if pause_ms > 0 else ""
        print(f"Sayfa birlestirildi: {merged.name}{pause_note}")


def load_progress(progress_path: Path) -> set[str]:
    if not progress_path.exists():
        return set()
    data = json.loads(progress_path.read_text(encoding="utf-8"))
    return set(data.get("completed", []))


def save_progress(progress_path: Path, completed: set[str]) -> None:
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(
        json.dumps({"completed": sorted(completed)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PDF kitabi VoxCPM ile paragraf paragraf seslendirir."
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=Path("Dan-Brown-Sirlarin-Sirri.pdf"),
        help="PDF dosya yolu",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=Path("amazon_reference_50s.mp3"),
        help="Referans ses dosyasi",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Ses dosyalarinin kaydedilecegi klasor",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=10,
        help="Kitaptaki baslangic sayfa numarasi",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="Kitaptaki bitis sayfa numarasi (bos = sonuna kadar)",
    )
    parser.add_argument(
        "--cfg",
        type=float,
        default=2.0,
        help="CFG guidance scale (sitedeki varsayilan: 2.0)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Istekler arasi bekleme suresi (saniye)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Hata durumunda yeniden deneme sayisi",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sadece paragraflari listele, ses uretme",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Paragraflari listele ve cik",
    )
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="Mevcut paragraf dosyalarini sayfa bazinda birlestir",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Sayfa birlestirme dosyasi olusturma",
    )
    parser.add_argument(
        "--pause-ms",
        type=int,
        default=1500,
        help="Paragraflar arasi duraksama suresi, milisaniye (varsayilan: 1500 = 1.5 sn)",
    )
    parser.add_argument(
        "--force-merge",
        action="store_true",
        help="Birlestirilmis sayfa dosyalarini yeniden olustur",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.pdf.exists():
        print(f"PDF bulunamadi: {args.pdf}", file=sys.stderr)
        return 1
    if not args.reference.exists() and not args.dry_run and not args.list_only:
        print(f"Referans ses bulunamadi: {args.reference}", file=sys.stderr)
        return 1

    paragraphs = extract_paragraphs(
        args.pdf,
        start_page=args.start_page,
        end_page=args.end_page,
    )
    print(f"Toplam {len(paragraphs)} paragraf bulundu.")

    if args.list_only or args.dry_run:
        for item in paragraphs[:20]:
            preview = item.text[:100].replace("\n", " ")
            print(f"{item.filename}: {preview}...")
        if len(paragraphs) > 20:
            print(f"... ve {len(paragraphs) - 20} paragraf daha")
        return 0

    if args.merge_only:
        args.output.mkdir(parents=True, exist_ok=True)
        merge_existing_pages(
            args.output,
            paragraphs,
            pause_ms=args.pause_ms,
            force=args.force_merge,
        )
        return 0

    args.output.mkdir(parents=True, exist_ok=True)
    progress_path = args.output / "progress.json"
    completed = load_progress(progress_path)
    grouped = group_paragraphs_by_page(paragraphs)

    client = VoxCPMClient(cfg_value=args.cfg)
    print("Referans ses yukleniyor...")
    client.upload_reference(args.reference)

    processed = 0
    total = len(paragraphs)
    for book_page in sorted(grouped):
        page_paragraphs = grouped[book_page]
        for paragraph in page_paragraphs:
            processed += 1
            output_file = args.output / paragraph.filename
            if paragraph.filename in completed or output_file.exists():
                print(f"[{processed}/{total}] Atlaniyor (zaten var): {paragraph.filename}")
                completed.add(paragraph.filename)
                continue

            print(f"[{processed}/{total}] Uretiliyor: {paragraph.filename}")
            print(f"  Metin: {paragraph.text[:90]}...")

            for attempt in range(1, args.max_retries + 1):
                try:
                    result = client.generate(paragraph.text)
                    client.download_audio(result, output_file)
                    completed.add(paragraph.filename)
                    save_progress(progress_path, completed)
                    break
                except Exception as exc:
                    wait_seconds = args.delay * attempt
                    print(f"  Hata (deneme {attempt}/{args.max_retries}): {exc}")
                    if attempt == args.max_retries:
                        print(f"  Birakildi: {paragraph.filename}", file=sys.stderr)
                        return 1
                    print(f"  {wait_seconds:.0f} saniye sonra tekrar denenecek...")
                    time.sleep(wait_seconds)

            time.sleep(args.delay)

        if not args.no_merge:
            page_files = [args.output / paragraph.filename for paragraph in page_paragraphs]
            if all(path.exists() for path in page_files):
                merged = merge_page_audio(
                    args.output,
                    book_page,
                    page_paragraphs,
                    pause_ms=args.pause_ms,
                    force=args.force_merge,
                )
                pause_note = f" ({args.pause_ms}ms ara)" if args.pause_ms > 0 else ""
                print(f"Sayfa {book_page} birlestirildi: {merged.name}{pause_note}")

    print(f"\nTamamlandi. Dosyalar: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
