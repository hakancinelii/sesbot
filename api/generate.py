from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
from urllib.error import HTTPError, URLError

VOXCPM_SPACE = "https://openbmb-voxcpm-demo.hf.space"

import os
import time
import requests

from lib.supabase_storage import is_configured, upload_bytes

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            text = data.get('text', '').strip()
            
            if not text:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No text provided")
                return

            ref_path = os.path.join(os.path.dirname(__file__), "..", "amazon_reference_50s.mp3")
            session = requests.Session()
            
            with open(ref_path, "rb") as handle:
                upload_resp = session.post(
                    f"{VOXCPM_SPACE}/gradio_api/upload",
                    files={"files": ("amazon_reference_50s.mp3", handle, "audio/mpeg")},
                    timeout=30
                )
            upload_resp.raise_for_status()
            uploaded_path = upload_resp.json()[0]
            
            reference_file = {
                "path": uploaded_path,
                "url": f"{VOXCPM_SPACE}/gradio_api/file={uploaded_path}",
                "orig_name": "amazon_reference_50s.mp3",
                "size": os.path.getsize(ref_path),
                "mime_type": "audio/mpeg",
                "meta": {"_type": "gradio.FileData"},
            }

            payload = {
                "data": [
                    text,
                    "", # control instruction
                    reference_file,
                    False, # ultimate cloning
                    "", # prompt text
                    2.0, # cfg
                    False, # normalize
                    False, # denoise
                ]
            }

            gen_resp = session.post(
                f"{VOXCPM_SPACE}/gradio_api/call/generate",
                json=payload,
                timeout=30
            )
            gen_resp.raise_for_status()
            event_id = gen_resp.json()["event_id"]

            audio_url = None
            deadline = time.time() + 60
            while time.time() < deadline:
                stream = session.get(
                    f"{VOXCPM_SPACE}/gradio_api/call/generate/{event_id}",
                    stream=True,
                    timeout=30
                )
                stream.raise_for_status()
                
                event_name = ""
                data_lines = []
                for raw_line in stream.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    if raw_line.startswith("event:"):
                        event_name = raw_line.split(":", 1)[1].strip()
                    elif raw_line.startswith("data:"):
                        data_lines.append(raw_line.split(":", 1)[1].strip())

                if event_name == "complete":
                    result = json.loads(data_lines[0])
                    file_info = result[0]
                    audio_url = file_info.get("url")
                    if not audio_url:
                        audio_url = f"{VOXCPM_SPACE}/gradio_api/file={file_info['path']}"
                    break
                elif event_name == "error":
                    raise Exception(f"Generation error: {data_lines[0] if data_lines else 'Unknown'}")
                
                time.sleep(2)

            if not audio_url:
                raise Exception("Timeout waiting for audio generation")

            audio_resp = session.get(audio_url, timeout=30)
            audio_resp.raise_for_status()

            audio_bytes = audio_resp.content
            supabase_url = None
            page = data.get("page")
            paragraph_index = data.get("paragraphIndex")
            if page is not None and isinstance(paragraph_index, int) and is_configured():
                key = f"audio/pages/{str(page).replace('/', '_')}_{paragraph_index + 1}.mp3"
                try:
                    supabase_url = upload_bytes(key, audio_bytes)
                    print(f"Supabase'e yuklendi: {key}")
                except Exception as exc:
                    print(f"Supabase yukleme hatasi (atlandi): {exc}")

            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(audio_bytes)))
            if supabase_url:
                self.send_header("X-Supabase-Audio-Url", supabase_url)
            self.end_headers()
            self.wfile.write(audio_bytes)
            
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            error_msg = json.dumps({"error": str(e)})
            self.wfile.write(error_msg.encode('utf-8'))
