"""API-layer tests (PRD §40's three endpoints), via httpx's ASGI transport
(no real network, no real Ollama). ai_service is monkeypatched at the
`app.api.ai_service` binding so these tests do not depend on Ollama being
reachable — see tests/test_ai_service.py for ai_service.py's own unit tests.
"""

from __future__ import annotations

import os
import tempfile

import httpx
import pytest

from app import api as api_module
from app.main import app
from app.schemas import AdviceItem, AiResult, SuggestedSql
from tests import make_fixtures as fx


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def _default_ai_stubs(monkeypatch):
    async def _fake_check(_settings):
        return True

    monkeypatch.setattr(api_module.ai_service, "check_ollama_available", _fake_check)


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------
async def test_health_ok_when_ai_available(client, monkeypatch):
    async def _true(_settings):
        return True

    monkeypatch.setattr(api_module.ai_service, "check_ollama_available", _true)
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "ai_available": True}


async def test_health_ok_when_ai_unavailable(client, monkeypatch):
    async def _false(_settings):
        return False

    monkeypatch.setattr(api_module.ai_service, "check_ollama_available", _false)
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ai_available"] is False


async def test_health_survives_ai_check_raising(client, monkeypatch):
    async def _raise(_settings):
        raise RuntimeError("boom")

    monkeypatch.setattr(api_module.ai_service, "check_ollama_available", _raise)
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ai_available"] is False


# ---------------------------------------------------------------------------
# /api/analyze
# ---------------------------------------------------------------------------
async def test_analyze_clean_sql_passes_without_ai(client):
    body = {
        "application_no": "115000218",
        "cost": "68,420",
        "sql": "SELECT A.X FROM T A WHERE A.Y = 1",
        "include_ai": False,
    }
    resp = await client.post("/api/analyze", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["compliance"]["status"] == "PASS"
    assert data["cost"] == 68420
    assert data["ai"]["status"] == "pending"


async def test_analyze_cost_accepts_comma_string(client):
    resp = await client.post(
        "/api/analyze",
        json={"application_no": "A1", "cost": "1,000", "sql": "SELECT 1 FROM DUAL", "include_ai": False},
    )
    assert resp.status_code == 200
    assert resp.json()["cost"] == 1000


@pytest.mark.parametrize("bad_cost", ["-1", "abc", "", "  "])
async def test_analyze_rejects_invalid_cost(client, bad_cost):
    resp = await client.post(
        "/api/analyze",
        json={"application_no": "A1", "cost": bad_cost, "sql": "SELECT 1 FROM DUAL", "include_ai": False},
    )
    assert resp.status_code == 422


async def test_analyze_rejects_missing_application_no(client):
    resp = await client.post(
        "/api/analyze", json={"application_no": "  ", "cost": 1000, "sql": "SELECT 1 FROM DUAL", "include_ai": False}
    )
    assert resp.status_code == 422


async def test_analyze_missing_where_is_block(client):
    resp = await client.post(
        "/api/analyze",
        json={"application_no": "A1", "cost": 1000, "sql": "SELECT * FROM T A", "include_ai": False},
    )
    assert resp.status_code == 200
    assert resp.json()["compliance"]["status"] == "BLOCK"


async def test_analyze_with_ai_true_calls_ai_service_and_recomputes_score(client, monkeypatch):
    async def _fake_ai(**kwargs):
        return AiResult(
            status="ok",
            summary="測試摘要",
            advice=[AdviceItem(title="t", explanation="e", impact="high")],
            suggested_sql=SuggestedSql(available=False, reason="測試"),
            estimated_improvement_pct=45,
        )

    monkeypatch.setattr(api_module.ai_service, "get_ai_result", _fake_ai)
    resp = await client.post(
        "/api/analyze",
        json={
            "application_no": "A1",
            "cost": 68420,
            "sql": "SELECT A.X FROM HOUT120 A WHERE TRUNC(A.TXN_DATE) = :D",
            "include_ai": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ai"]["status"] == "ok"
    assert data["ai"]["estimated_improvement_pct"] == 45
    ai_component = next(b for b in data["improvement"]["breakdown"] if b["component"] == "ai_adjustment")
    assert ai_component["score"] > 0


async def test_analyze_degrades_gracefully_when_ai_service_raises(client, monkeypatch):
    async def _raise(**kwargs):
        raise RuntimeError("ollama exploded")

    monkeypatch.setattr(api_module.ai_service, "get_ai_result", _raise)
    resp = await client.post(
        "/api/analyze",
        json={"application_no": "A1", "cost": 1000, "sql": "SELECT 1 FROM DUAL", "include_ai": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ai"]["status"] == "unavailable"
    assert "暫時無法使用" in data["ai"]["message"]
    # deterministic rule checking must still be intact (PRD §51: AI is never
    # a single point of failure for the rest of the system).
    assert data["compliance"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# /api/extract-sql
# ---------------------------------------------------------------------------
async def test_extract_sql_from_sql_file(client):
    files = {"file": ("q.sql", b"SELECT A.X FROM T A WHERE A.Y=1", "application/octet-stream")}
    resp = await client.post("/api/extract-sql", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "SELECT A.X" in data["sql"]
    assert data["needs_confirmation"] is True


async def test_extract_sql_no_sql_found_returns_200_with_message(client):
    files = {"file": ("note.txt", "這是一份普通的文件，沒有任何 SQL 內容。".encode(), "text/plain")}
    resp = await client.post("/api/extract-sql", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["needs_confirmation"] is False
    assert "未辨識到可檢核的 SQL" in data["message"]


async def test_extract_sql_disallowed_extension_rejected(client):
    files = {"file": ("virus.exe", b"MZ\x90\x00", "application/octet-stream")}
    resp = await client.post("/api/extract-sql", files=files)
    assert resp.status_code == 400
    assert "detail" in resp.json()


async def test_extract_sql_oversized_file_rejected(client):
    big = b"x" * (11 * 1024 * 1024)  # default limit is 10 MB
    files = {"file": ("big.txt", big, "text/plain")}
    resp = await client.post("/api/extract-sql", files=files)
    assert resp.status_code == 400


async def test_extract_sql_docx_roundtrip(client):
    content = fx.build_docx_bytes(paragraphs=["SELECT A.X FROM T A WHERE A.Y=1"])
    files = {"file": ("report.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    resp = await client.post("/api/extract-sql", files=files)
    assert resp.status_code == 200
    assert "SELECT A.X" in resp.json()["sql"]


async def test_extract_sql_does_not_write_any_temp_file(client):
    tmp_dir = tempfile.gettempdir()
    before = set(os.listdir(tmp_dir))
    content = fx.build_docx_bytes(paragraphs=["SELECT A.X FROM T A WHERE A.Y=1"])
    files = {"file": ("report.docx", content, "application/octet-stream")}
    resp = await client.post("/api/extract-sql", files=files)
    assert resp.status_code == 200
    after = set(os.listdir(tmp_dir))
    assert after == before, f"extract-sql left new files in {tmp_dir}: {after - before}"
