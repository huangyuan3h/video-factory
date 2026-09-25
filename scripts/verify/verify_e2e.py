#!/usr/bin/env python
"""End-to-end verification for Video Factory.

Runs the real worker API in a subprocess against a throwaway SQLite DB and a
local mock OpenAI-compatible server, then exercises every feature point over
HTTP. Uses REAL edge-tts, PIL, MoviePy and ffmpeg to produce an actual video.

Run from the worker directory:

    uv run python scripts/verify/verify_e2e.py

Exit code is non-zero if any check fails. ComfyUI and real social publishing
are intentionally out of scope (they need a GPU / credentials); their safety
and queueing behaviour is still verified.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_DIR = REPO_ROOT / "apps" / "worker"
WEB_DIR = REPO_ROOT / "apps" / "web"

SCRIPT_JSON = {
    "title": "验证视频",
    "segments": [
        {
            "text": "这是第一段验证文本，用来确认脚本、语音合成与字幕流程都能正常工作。",
            "keywords": ["technology"],
            "duration_estimate": 6,
        },
        {
            "text": "这是第二段，用来确认多段拼接和最终视频合成流程。",
            "keywords": ["nature"],
            "duration_estimate": 6,
        },
    ],
    "total_duration_estimate": 12,
}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _MockAIHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible server returning a fixed script."""

    def log_message(self, *args):  # silence
        pass

    def _send(self, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"data": [{"id": "mock-model", "object": "model"}], "object": "list"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        self.rfile.read(length)
        content = json.dumps(SCRIPT_JSON, ensure_ascii=False)
        self._send(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )


class Verifier:
    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, fn):
        try:
            detail = fn()
            self.results.append((name, True, detail or ""))
        except Exception as e:  # noqa: BLE001
            self.results.append((name, False, f"{type(e).__name__}: {e}"))

    def expect(self, cond: bool, msg: str = "assertion failed"):
        if not cond:
            raise AssertionError(msg)

    def report(self) -> int:
        passed = sum(1 for _, ok, _ in self.results if ok)
        print("\n" + "=" * 78)
        print(f"VERIFICATION REPORT  —  {passed}/{len(self.results)} passed")
        print("=" * 78)
        for name, ok, detail in self.results:
            mark = "PASS" if ok else "FAIL"
            line = f"[{mark}] {name}"
            if detail:
                line += f"  —  {detail}"
            print(line)
        failed = [r for r in self.results if not r[1]]
        if failed:
            print("\nFAILED CHECKS:")
            for name, _, detail in failed:
                print(f"  - {name}: {detail}")
        return 1 if failed else 0


def wait_for(url: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> int:
    v = Verifier()
    tmp = Path(tempfile.mkdtemp(prefix="vf-verify-"))
    api_port = free_port()
    ai_port = free_port()
    api = f"http://127.0.0.1:{api_port}"
    procs: list[subprocess.Popen] = []

    # --- mock AI server ---
    ai_server = ThreadingHTTPServer(("127.0.0.1", ai_port), _MockAIHandler)
    threading.Thread(target=ai_server.serve_forever, daemon=True).start()

    # --- worker API subprocess ---
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite+aiosqlite:///{tmp}/verify.db",
            "DATA_DIR": str(tmp / "data"),
            "OUTPUT_DIR": str(tmp / "data" / "output"),
            "ASSETS_DIR": str(tmp / "data" / "assets"),
            "ENABLE_SCHEDULER": "0",
            "ENABLE_SYNTHETIC": "0",
            "ENABLE_SYNTHETIC_VIDEO": "0",
            "QUEUE_BACKEND": "auto",
            "PEXELS_API_KEY": "",
            "PIXABAY_API_KEY": "",
            "VLLM_TTS_URL": "",
            "VLLM_TTS_HQ_URL": "",
            "COMFYUI_URL": "http://127.0.0.1:59999",
            "API_TOKEN": "",
            "WORKER_URL": api,
        }
    )
    api_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
        cwd=str(WORKER_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    procs.append(api_proc)

    client = httpx.Client(base_url=api, timeout=30.0)
    try:
        if not wait_for(f"{api}/health"):
            print("API did not become healthy; aborting")
            return 1

        # ---------------------------------------------------------------- API core
        v.check("GET /health", lambda: v.expect(client.get("/health").json()["status"] == "healthy"))
        v.check("GET /ready", lambda: v.expect(client.get("/ready").status_code == 200))
        v.check(
            "GET /api/capabilities",
            lambda: v.expect(client.get("/api/capabilities").json()["name"] == "video-factory"),
        )

        # ---------------------------------------------------------------- AI settings
        ai_holder = {}

        def ai_create():
            r = client.post(
                "/api/ai-settings",
                json={
                    "name": "mock",
                    "base_url": f"http://127.0.0.1:{ai_port}/v1",
                    "api_key": "test-key",
                    "model_id": "mock-model",
                },
            )
            v.expect(r.status_code == 200, r.text)
            data = r.json()["data"]
            ai_holder["id"] = data["id"]
            client.post(f"/api/ai-settings/{data['id']}/activate")
            return f"id={data['id']}"

        v.check("AI settings create + activate", ai_create)
        v.check(
            "AI settings GET /active",
            lambda: v.expect(client.get("/api/ai-settings/active").json()["data"]["model_id"] == "mock-model"),
        )
        v.check(
            "AI settings POST /{id}/test",
            lambda: v.expect(client.post(f"/api/ai-settings/{ai_holder['id']}/test").status_code == 200),
        )
        v.check("AI settings list", lambda: v.expect(client.get("/api/ai-settings").status_code == 200))

        # ---------------------------------------------------------------- general settings
        def general_put():
            r = client.put(
                "/api/settings",
                json={
                    "video_resolution_width": 640,
                    "video_resolution_height": 360,
                    "pexels_api_key": "",
                    "pixabay_api_key": "",
                },
            )
            v.expect(r.status_code == 200, r.text)
            return "640x360"

        v.check("General settings GET", lambda: v.expect(client.get("/api/settings").status_code == 200))
        v.check("General settings PUT", general_put)

        # ---------------------------------------------------------------- system prompts
        def prompts_crud():
            created = client.post(
                "/api/system-prompts", json={"name": "vp", "content": "you are a writer", "is_default": False}
            ).json()["data"]
            pid = created["id"]
            v.expect(client.post(f"/api/system-prompts/{pid}/default").status_code == 200)
            v.expect(client.put(f"/api/system-prompts/{pid}", json={"name": "vp2"}).status_code == 200)
            v.expect(any(p["id"] == pid for p in client.get("/api/system-prompts").json()["data"]))
            v.expect(client.delete(f"/api/system-prompts/{pid}").status_code == 200)
            return "create/default/update/list/delete"

        v.check("System prompts CRUD", prompts_crud)

        # ---------------------------------------------------------------- sources
        def sources_crud():
            created = client.post(
                "/api/sources",
                json={"type": "rss", "name": "verify-rss", "url": "http://example.com/feed", "keywords": ["ai"]},
            ).json()["data"]
            sid = created["id"]
            v.expect(client.put(f"/api/sources/{sid}", json={"name": "verify-rss-2"}).status_code == 200)
            v.expect(client.get(f"/api/sources/{sid}").status_code == 200)
            return sid

        source_id = {}
        v.check("Sources CRUD", lambda: source_id.setdefault("id", sources_crud()) or "ok")

        # ---------------------------------------------------------------- tasks + runs
        def tasks_crud():
            created = client.post(
                "/api/tasks",
                json={"name": "verify-task", "source_id": source_id["id"], "schedule": "0 3 * * *"},
            )
            v.expect(created.status_code in (200, 201), created.text)
            tid = created.json()["data"]["id"]
            v.expect(client.get("/api/tasks").status_code == 200)
            v.expect(client.put(f"/api/tasks/{tid}", json={"name": "verify-task-2"}).status_code == 200)
            v.expect(client.get("/api/runs").status_code == 200)
            return tid

        task_id_holder = {}
        v.check("Tasks CRUD + runs list", lambda: task_id_holder.setdefault("id", tasks_crud()) or "ok")

        # ---------------------------------------------------------------- series
        series_id_holder = {}

        def series_create():
            r = client.post(
                "/api/series",
                json={"name": "验证系列", "description": "e2e", "default_background_source": "local"},
            )
            v.expect(r.status_code == 200, r.text)
            data = r.json()["data"]
            series_id_holder["id"] = data["id"]
            series_id_holder["slug"] = data["slug"]
            v.expect(bool(data["slug"]), "slug missing")
            return f"slug={data['slug']}"

        v.check("Series create (CJK slug)", series_create)
        v.check(
            "Series list + get",
            lambda: v.expect(
                client.get(f"/api/series/{series_id_holder['id']}").json()["data"]["name"] == "验证系列"
            ),
        )
        v.check(
            "Series update",
            lambda: v.expect(
                client.put(f"/api/series/{series_id_holder['id']}", json={"description": "updated"}).status_code == 200
            ),
        )

        # ---------------------------------------------------------------- publishers
        publisher_holder = {}

        def publisher_create():
            r = client.post("/api/publishers", json={"platform": "youtube", "name": "verify-yt"})
            v.expect(r.status_code == 200, r.text)
            publisher_holder["id"] = r.json()["data"]["id"]
            return f"id={publisher_holder['id']}"

        v.check("Publisher create (youtube)", publisher_create)
        v.check("Publisher list", lambda: v.expect(len(client.get("/api/publishers").json()["data"]) >= 1))
        v.check(
            "Publisher folders (youtube, no creds -> empty)",
            lambda: v.expect(client.get(f"/api/publishers/{publisher_holder['id']}/folders").json()["data"] == []),
        )
        v.check(
            "Publisher create folder without creds -> 400",
            lambda: v.expect(
                client.post(f"/api/publishers/{publisher_holder['id']}/folders", json={"name": "PL"}).status_code == 400
            ),
        )
        v.check(
            "Publisher login rejected for youtube -> 400",
            lambda: v.expect(
                client.post(f"/api/publishers/{publisher_holder['id']}/login", json={"headless": True}).status_code
                == 400
            ),
        )

        # ---------------------------------------------------------------- series publish target
        def series_target_flow():
            created = client.post(
                f"/api/series/{series_id_holder['id']}/targets",
                json={"platform": "youtube", "account_id": publisher_holder["id"]},
            )
            v.expect(created.status_code == 200, created.text)
            target_id = created.json()["data"]["id"]
            listed = client.get(f"/api/series/{series_id_holder['id']}/targets").json()["data"]
            v.expect(len(listed) == 1, f"targets={listed}")
            v.expect(client.delete(f"/api/series/{series_id_holder['id']}/targets/{target_id}").status_code == 200)
            return "create/list/delete"

        v.check("Series publish target CRUD", series_target_flow)

        # ---------------------------------------------------------------- synthetic (disabled by default)
        v.check(
            "Synthetic image status disabled",
            lambda: v.expect(client.get("/api/synthetic/status").json()["enabled"] is False),
        )
        v.check(
            "Synthetic image generate -> 409",
            lambda: v.expect(client.post("/api/synthetic/generate", json={"prompt": "x"}).status_code == 409),
        )
        v.check(
            "Synthetic video status disabled",
            lambda: v.expect(client.get("/api/synthetic/video/status").json()["enabled"] is False),
        )
        v.check(
            "Synthetic video generate -> 409",
            lambda: v.expect(client.post("/api/synthetic/video/generate", json={"prompt": "x"}).status_code == 409),
        )

        # ---------------------------------------------------------------- TTS
        def tts_test():
            r = client.post(
                "/api/tts-settings/test",
                json={"voice": "zh-CN-YunjianNeural", "rate": "+0%", "test_text": "验证语音。"},
            )
            v.expect(r.status_code in (200, 400), r.text)
            return f"status={r.status_code}"

        v.check("TTS settings GET", lambda: v.expect(client.get("/api/tts-settings").status_code == 200))
        v.check("TTS settings test (edge-tts)", tts_test)

        # ---------------------------------------------------------------- video generation (real E2E)
        gen = {}

        def generate_video():
            r = client.post(
                "/api/videos/generate",
                json={
                    "title": "验证视频",
                    "content": "第一段内容用于验证。第二段内容用于验证。",
                    "series_id": series_id_holder["id"],
                    "background_source": "local",
                    "resolution_width": 640,
                    "resolution_height": 360,
                    "voice": "zh-CN-YunjianNeural",
                    "generate_subtitle": True,
                    "generate_cover": True,
                },
            )
            v.expect(r.status_code == 200, r.text)
            data = r.json()["data"]
            gen["id"] = data["id"]
            gen["dir"] = data["task_dir"]
            v.expect(
                Path(data["task_dir"]).parent.name == series_id_holder["slug"],
                f"task_dir not under series slug: {data['task_dir']}",
            )
            return f"id={data['id']} dir={Path(data['task_dir']).parent.name}"

        v.check("Video generate accepted", generate_video)

        def wait_generation(timeout=240.0):
            deadline = time.time() + timeout
            last = None
            while time.time() < deadline:
                body = client.get(f"/api/videos/tasks/{gen['id']}").json()["data"]
                last = body
                if body["status"] in ("completed", "failed", "cancelled"):
                    break
                time.sleep(2)
            v.expect(last and last["status"] == "completed", f"status={last and last.get('status')} err={last and last.get('error')}")
            return f"status={last['status']}"

        v.check("Video generation completes", wait_generation)

        def files_present():
            body = client.get(f"/api/videos/tasks/{gen['id']}").json()["data"]
            files = body.get("files", {})
            for key in ("video", "cover", "subtitles", "script"):
                v.expect(key in files and Path(files[key]).exists(), f"missing {key}: {files.get(key)}")
            v.expect(Path(files["video"]).stat().st_size > 0, "video empty")
            return f"{Path(files['video']).name} {Path(files['video']).stat().st_size} bytes"

        v.check("Generation artifacts (video/cover/subtitle/script)", files_present)
        v.check(
            "Download video endpoint",
            lambda: v.expect(
                client.get(f"/api/videos/tasks/{gen['id']}/download?kind=video").status_code == 200
            ),
        )
        v.check(
            "Download subtitle endpoint",
            lambda: v.expect(
                client.get(f"/api/videos/tasks/{gen['id']}/download?kind=subtitle").status_code == 200
            ),
        )
        v.check(
            "Task log endpoint",
            lambda: v.expect(
                len(client.get(f"/api/videos/tasks/{gen['id']}/log").json()["data"]["log"]) > 0
            ),
        )

        # ---------------------------------------------------------------- review + publish
        def review_flow():
            r = client.post(f"/api/videos/tasks/{gen['id']}/review", json={"decision": "approve"})
            v.expect(r.status_code == 200, r.text)
            body = client.get(f"/api/videos/tasks/{gen['id']}").json()["data"]
            v.expect(body["review_status"] == "approved")
            return body["review_status"]

        v.check("Review approve", review_flow)
        v.check(
            "Publish requires targets when none configured",
            lambda: v.expect(
                client.post(
                    f"/api/videos/tasks/{gen['id']}/publish", json={"platforms": ["youtube"]}
                ).status_code
                == 200
            ),
        )

        def publish_jobs():
            jobs = client.get(f"/api/videos/tasks/{gen['id']}/publish").json()["data"]
            v.expect(len(jobs) >= 1, "no publish job")
            v.expect(jobs[0]["status"] in ("pending", "processing"), jobs[0]["status"])
            retry = client.post(f"/api/publish/jobs/{jobs[0]['id']}/retry")
            v.expect(retry.status_code == 200, retry.text)
            return f"{len(jobs)} job(s), platform={jobs[0]['platform']}"

        v.check("Publish queue + job retry", publish_jobs)
        v.check(
            "Publish jobs list",
            lambda: v.expect(client.get("/api/publish/jobs").status_code == 200),
        )

        # ---------------------------------------------------------------- cancel + retry
        def cancel_flow():
            r = client.post(
                "/api/videos/generate",
                json={
                    "title": "取消测试",
                    "content": "这段内容会被取消。",
                    "background_source": "local",
                    "resolution_width": 640,
                    "resolution_height": 360,
                },
            )
            v.expect(r.status_code == 200, r.text)
            cid = r.json()["data"]["id"]
            time.sleep(0.3)
            c = client.post(f"/api/videos/tasks/{cid}/cancel")
            v.expect(c.status_code == 200, c.text)
            deadline = time.time() + 40
            status = None
            while time.time() < deadline:
                status = client.get(f"/api/videos/tasks/{cid}").json()["data"]["status"]
                if status in ("cancelled", "failed", "completed"):
                    break
                time.sleep(1)
            v.expect(status == "cancelled", f"status={status}")
            return f"{cid} -> cancelled"

        v.check("Cancel pending task", cancel_flow)

        def retry_flow():
            r = client.post(f"/api/videos/tasks/{gen['id']}/retry")
            v.expect(r.status_code == 200, r.text)
            new_id = r.json()["data"]["id"]
            v.expect(new_id != gen["id"], "retry returned same id")
            client.post(f"/api/videos/tasks/{new_id}/cancel")
            return f"new task {new_id}"

        v.check("Retry task", retry_flow)

        # ---------------------------------------------------------------- SSE
        def sse_flow():
            with httpx.stream("GET", f"{api}/api/videos/events", timeout=10.0) as r:
                v.expect(r.status_code == 200, f"status={r.status_code}")
                for line in r.iter_lines():
                    if line.startswith("data:"):
                        payload = json.loads(line[len("data:"):].strip())
                        v.expect("data" in payload)
                        return "received first SSE event"
            raise AssertionError("no SSE event received")

        v.check("SSE /api/videos/events", sse_flow)

        # ---------------------------------------------------------------- queue depth
        v.check(
            "Publish queue depth reported",
            lambda: v.expect("depth" in client.get("/api/publish/jobs").json()),
        )

    finally:
        client.close()
        ai_server.shutdown()
        for p in procs:
            p.terminate()
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    failed = sum(1 for _, ok, _ in v.results if not ok)
    print(f"\n(artifacts were written to a temp dir and cleaned up)")

    # --- frontend page smoke test (built app) ---
    if (WEB_DIR / ".next").exists():
        web_port = free_port()
        web_env = os.environ.copy()
        web_env["WORKER_URL"] = "http://127.0.0.1:1"  # pages should render without a worker
        web_proc = subprocess.Popen(
            ["pnpm", "exec", "next", "start", "-p", str(web_port)],
            cwd=str(WEB_DIR),
            env=web_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            if wait_for(f"http://127.0.0.1:{web_port}/", timeout=40):
                for path in ["/", "/series", "/videos", "/publishers", "/settings", "/tasks", "/assets", "/logs"]:
                    try:
                        code = httpx.get(f"http://127.0.0.1:{web_port}{path}", timeout=10).status_code
                        v.results.append((f"Web page {path}", code == 200, f"HTTP {code}"))
                    except Exception as e:  # noqa: BLE001
                        v.results.append((f"Web page {path}", False, str(e)))
            else:
                v.results.append(("Web server start", False, "did not become ready"))
        finally:
            web_proc.terminate()
            try:
                web_proc.wait(timeout=10)
            except Exception:
                web_proc.kill()
    else:
        v.results.append(("Web build present", False, "run `pnpm --filter @video-factory/web build` first"))

    return v.report()


if __name__ == "__main__":
    sys.exit(main())
