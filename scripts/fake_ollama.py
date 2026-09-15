#!/usr/bin/env python
"""Tiny, dependency-light fake Ollama server for manual/E2E testing of
SQLCheck 2.0's AI advisory path (backend/app/services/ai_service.py).

This is NOT what ai_service.py's own unit tests use — tests/test_ai_service.py
mocks httpx directly with respx, which is faster and needs no real process.
This script is only for a human manually exercising the running backend (or
frontend) against something that behaves like Ollama's /api/tags and
/api/chat endpoints, without needing a real Ollama + Gemma install.

Usage:
    python scripts/fake_ollama.py
    python scripts/fake_ollama.py --mode slow --port 11434
    python scripts/fake_ollama.py --mode bad-json
    python scripts/fake_ollama.py --mode down

Then point the backend at it, e.g.:
    OLLAMA_BASE_URL=http://127.0.0.1:11434 OLLAMA_MODEL=gemma4:31b-it-qat \
        uv run uvicorn app.main:app --reload

Modes (--mode, default "normal"):
    normal    GET /api/tags returns a models list containing the fake model
              name; POST /api/chat returns a valid, schema-shaped JSON
              advice response immediately.
    slow      Same responses as "normal", but POST /api/chat sleeps ~5
              seconds first, so a manual tester can see the frontend's
              "AI 分析中" loading state.
    bad-json  POST /api/chat responds 200 with a message.content string
              that is NOT valid JSON, to exercise ai_service's
              retry-once-then-degrade path.
    down      Does not bind to any port at all and exits immediately, so
              pointing OLLAMA_BASE_URL at this port reproduces a
              "connection refused" scenario.

Port (--port, default 11434) is also overridable.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 11434
FAKE_MODEL_NAME = "gemma4:31b-it-qat"
SLOW_MODE_DELAY_SECONDS = 5


def _advice_payload() -> dict:
    """A valid response matching ai_service.RESPONSE_SCHEMA / _AiRawResponse."""
    return {
        "summary": "（假資料）這段 SQL 條件欄位使用了函數，另有 1 項改善建議。",
        "advice": [
            {
                "title": "（假資料）調整條件寫法",
                "explanation": "此為 fake_ollama.py 產生的固定假資料，僅供本機手動測試前端顯示使用。",
                "example": "A.COL = :STR_001",
                "impact": "medium",
            }
        ],
        "suggested_sql": {
            "available": True,
            "reason": "（假資料）僅示範用途，可提供簡單改寫供參考。",
            "sql": "SELECT * FROM T A WHERE A.COL = :STR_001",
        },
        "estimated_improvement_pct": 25,
    }


def _chat_envelope(content: str) -> dict:
    """Matches Ollama's documented /api/chat non-streaming response shape:
    the reply text lives at message.content as a JSON string."""
    return {
        "model": FAKE_MODEL_NAME,
        "created_at": "2026-01-01T00:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
    }


class _FakeOllamaHandler(BaseHTTPRequestHandler):
    mode = "normal"

    def _write_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _drain_request_body(self) -> None:
        # This fake server ignores the actual prompt/schema and always
        # answers from its own fixed --mode; still drain the body so the
        # client's connection behaves normally.
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

    def do_GET(self):
        if self.path.rstrip("/") == "/api/tags":
            self._write_json(200, {"models": [{"name": FAKE_MODEL_NAME}]})
            return
        self._write_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/api/chat":
            self._write_json(404, {"error": "not found"})
            return

        self._drain_request_body()

        if self.mode == "slow":
            time.sleep(SLOW_MODE_DELAY_SECONDS)
            self._write_json(200, self._chat_envelope_for_mode())
        else:
            self._write_json(200, self._chat_envelope_for_mode())

    def _chat_envelope_for_mode(self) -> dict:
        if self.mode == "bad-json":
            return _chat_envelope("this is not valid JSON {{{ oops")
        return _chat_envelope(json.dumps(_advice_payload(), ensure_ascii=False))

    def log_message(self, log_format: str, *args) -> None:
        sys.stderr.write(f"[fake_ollama] {self.address_string()} - {log_format % args}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tiny fake Ollama server for manual SQLCheck 2.0 testing."
    )
    parser.add_argument(
        "--mode",
        choices=["normal", "slow", "bad-json", "down"],
        default="normal",
        help="Response behavior for POST /api/chat (default: normal).",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Port to bind (default: {DEFAULT_PORT})."
    )
    args = parser.parse_args(argv)

    if args.mode == "down":
        print("[fake_ollama] mode=down -> not binding to any port, exiting immediately.")
        return 0

    _FakeOllamaHandler.mode = args.mode
    server = ThreadingHTTPServer(("0.0.0.0", args.port), _FakeOllamaHandler)
    print(f"[fake_ollama] mode={args.mode} listening on http://0.0.0.0:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
