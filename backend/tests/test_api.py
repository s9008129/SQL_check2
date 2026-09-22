"""API-layer tests (PRD §40's three endpoints), via httpx's ASGI transport
(no real network, no real Ollama). ai_service is monkeypatched at the
`app.api.ai_service` binding so these tests do not depend on Ollama being
reachable — see tests/test_ai_service.py for ai_service.py's own unit tests.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import tempfile

import httpx
import pytest

from app import api as api_module
from app.main import app
from app.schemas import AdviceItem, AiResult, SuggestedSql
from app.settings import get_settings
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

    monkeypatch.setattr(api_module.ai_service, "check_llm_available", _fake_check)


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------
async def test_health_ok_when_ai_available(client, monkeypatch):
    async def _true(_settings):
        return True

    monkeypatch.setattr(api_module.ai_service, "check_llm_available", _true)
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "ai_available": True}


async def test_health_ok_when_ai_unavailable(client, monkeypatch):
    async def _false(_settings):
        return False

    monkeypatch.setattr(api_module.ai_service, "check_llm_available", _false)
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ai_available"] is False


async def test_health_survives_ai_check_raising(client, monkeypatch):
    async def _raise(_settings):
        raise RuntimeError("boom")

    monkeypatch.setattr(api_module.ai_service, "check_llm_available", _raise)
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ai_available"] is False


# ---------------------------------------------------------------------------
# /api/analyze
# ---------------------------------------------------------------------------
ESTIMATED_PLAN_TEXT = """
Plan hash value: 77
---------------------------------------------------------------
| Id | Operation          | Name | Rows | Cost (%CPU) | Time     |
---------------------------------------------------------------
|  0 | SELECT STATEMENT   |      |   10 |    68 (0)   | 00:00:01 |
|* 1 | TABLE ACCESS FULL  | T    |   10 |    68 (0)   | 00:00:01 |
---------------------------------------------------------------
Predicate Information (identified by operation id):
---------------------------------------------------
   1 - filter("A"."Y"=1)
"""


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
    assert data["execution_plan"] is None


async def test_analyze_accepts_sql_developer_plan_without_changing_compliance_or_score(client):
    body = {
        "application_no": "115000218",
        "cost": 68,
        "sql": "SELECT A.X FROM T A WHERE A.Y = 1",
        "execution_plan": ESTIMATED_PLAN_TEXT,
        "include_ai": False,
    }
    with_plan = await client.post("/api/analyze", json=body)
    without_plan = await client.post("/api/analyze", json={**body, "execution_plan": None})
    assert with_plan.status_code == 200
    data = with_plan.json()
    assert data["execution_plan"]["recognized"] is True
    assert data["execution_plan"]["source"] == "estimated"
    assert data["execution_plan"]["plan_hash_value"] == "77"
    assert data["execution_plan"]["cost_matches_input"] is True
    assert data["compliance"] == without_plan.json()["compliance"]
    assert data["improvement"] == without_plan.json()["improvement"]


async def test_analyze_unrecognized_plan_keeps_sql_review_available(client):
    resp = await client.post(
        "/api/analyze",
        json={
            "application_no": "A1",
            "cost": 1000,
            "sql": "SELECT 1 FROM DUAL",
            "execution_plan": "not a plan",
            "include_ai": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_plan"]["recognized"] is False
    assert data["compliance"]["status"] == "PASS"


async def test_analyze_without_ai_returns_deterministic_verified_rewrites(client):
    resp = await client.post(
        "/api/analyze",
        json={
            "application_no": "A1",
            "cost": 1000,
            "sql": "SELECT A.X FROM T A WHERE A.C = '1' OR A.C = '2'",
            "include_ai": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ai"]["status"] == "pending"
    assert data["verified_rewrites"] == [
        {
            "statement_index": 0,
            "rule": "or_eq_to_in",
            "source_rule_id": "R006",
            "title": "同欄位 OR 改為 IN",
            "before": "A.C = '1' OR A.C = '2'",
            "after": "A.C IN ('1', '2')",
        }
    ]


async def test_analyze_verified_rewrites_are_identical_with_or_without_ai(client, monkeypatch):
    async def _unavailable(**_kwargs):
        return AiResult(status="unavailable", message="暫時無法使用")

    monkeypatch.setattr(api_module.ai_service, "get_ai_result", _unavailable)
    body = {
        "application_no": "A1",
        "cost": 1000,
        "sql": "SELECT A.X FROM T A WHERE SUBSTR(A.CODE, 6, 3) = '551'",
    }
    without_ai = await client.post("/api/analyze", json={**body, "include_ai": False})
    with_ai = await client.post("/api/analyze", json={**body, "include_ai": True})
    assert without_ai.status_code == 200
    assert with_ai.status_code == 200
    assert without_ai.json()["verified_rewrites"] == with_ai.json()["verified_rewrites"]
    assert with_ai.json()["ai"]["status"] == "unavailable"
    assert with_ai.json()["verified_rewrites"][0]["source_rule_id"] == "R005"


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


async def test_analyze_ai_advice_never_moves_the_improvement_index(client, monkeypatch):
    # 2026-09-17 user decision: the 0-100 index is deterministic. Even with a
    # full AI response whose advice is all marked impact=high, /api/analyze
    # must return exactly the same score / level / breakdown as the same
    # request run with include_ai=false.
    async def _fake_ai(**kwargs):
        return AiResult(
            status="ok",
            summary="測試摘要",
            advice=[AdviceItem(title="t", explanation="e", impact="high") for _ in range(3)],
            suggested_sql=SuggestedSql(available=False, reason="測試"),
            estimated_improvement_pct=45,
        )

    monkeypatch.setattr(api_module.ai_service, "get_ai_result", _fake_ai)
    body = {
        "application_no": "A1",
        "cost": 68420,
        "sql": "SELECT A.X FROM HOUT120 A WHERE TRUNC(A.TXN_DATE) = :D",
    }
    without_ai = await client.post("/api/analyze", json={**body, "include_ai": False})
    with_ai = await client.post("/api/analyze", json={**body, "include_ai": True})
    assert without_ai.status_code == 200
    assert with_ai.status_code == 200

    data = with_ai.json()
    assert data["ai"]["status"] == "ok"
    assert data["ai"]["estimated_improvement_pct"] == 45

    baseline = without_ai.json()["improvement"]
    assert data["improvement"]["score"] == baseline["score"]
    assert data["improvement"]["level"] == baseline["level"]
    assert [b["component"] for b in data["improvement"]["breakdown"]] == [
        b["component"] for b in baseline["breakdown"]
    ]
    assert "ai_adjustment" not in {b["component"] for b in data["improvement"]["breakdown"]}


async def test_analyze_returns_safe_500_when_rule_pipeline_raises_unexpectedly(client, monkeypatch):
    # Defense-in-depth (PRD §50.4): an unexpected failure in the
    # deterministic pipeline itself must never fall through to FastAPI's
    # default handler (whose traceback could embed raw SQL — sqlglot's
    # ParseError does) and must never silently report a fabricated PASS.
    def _boom(_sql):
        raise RuntimeError("simulated sql_parser failure")

    monkeypatch.setattr(api_module, "parse_sql_text", _boom)
    resp = await client.post(
        "/api/analyze",
        json={"application_no": "A1", "cost": 1000, "sql": "SELECT 1 FROM DUAL", "include_ai": False},
    )
    assert resp.status_code == 500
    assert resp.json()["detail"] == api_module._ANALYZE_FAILED_MESSAGE


async def test_analyze_degrades_gracefully_when_ai_service_raises(client, monkeypatch):
    async def _raise(**kwargs):
        raise RuntimeError("ollama exploded")

    monkeypatch.setattr(api_module.ai_service, "get_ai_result", _raise)
    resp = await client.post(
        "/api/analyze",
        json={
            "application_no": "A1",
            "cost": 1000,
            "sql": "SELECT A.X FROM T A WHERE A.C = '1' OR A.C = '2'",
            "include_ai": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ai"]["status"] == "unavailable"
    assert "暫時無法使用" in data["ai"]["message"]
    # deterministic rule checking must still be intact (PRD §51: AI is never
    # a single point of failure for the rest of the system).
    assert data["compliance"]["status"] == "PASS"
    assert data["verified_rewrites"][0]["source_rule_id"] == "R006"


# ---------------------------------------------------------------------------
# SQL archive wiring (2026-09-16): recorded only on the include_ai=true call,
# and never allowed to affect the response.
# ---------------------------------------------------------------------------
async def test_analyze_with_ai_true_records_to_archive(client, monkeypatch):
    calls = []
    monkeypatch.setattr(api_module.sql_archive, "record_analysis", lambda **kwargs: calls.append(kwargs))
    resp = await client.post(
        "/api/analyze",
        json={"application_no": "A1", "cost": 1000, "sql": "SELECT 1 FROM DUAL", "include_ai": True},
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0]["cost"] == 1000


async def test_analyze_with_ai_false_does_not_record_to_archive(client, monkeypatch):
    calls = []
    monkeypatch.setattr(api_module.sql_archive, "record_analysis", lambda **kwargs: calls.append(kwargs))
    resp = await client.post(
        "/api/analyze",
        json={"application_no": "A1", "cost": 1000, "sql": "SELECT 1 FROM DUAL", "include_ai": False},
    )
    assert resp.status_code == 200
    assert calls == []


async def test_analyze_archive_failure_does_not_affect_response(client, monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(api_module.sql_archive, "record_analysis", _boom)
    resp = await client.post(
        "/api/analyze",
        json={"application_no": "A1", "cost": 1000, "sql": "SELECT 1 FROM DUAL", "include_ai": True},
    )
    assert resp.status_code == 200
    assert resp.json()["compliance"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# SQL Developer execution-plan evidence: privacy / authority boundaries
# (2026-09-22). Plan text is test-environment evidence only: it must stay out
# of the cloud-model call, out of the SQL archive, and out of logs even when
# the deterministic parser raises. It must never change compliance either.
# ---------------------------------------------------------------------------
PLAN_SENTINEL = "SUPER_SECRET_PLAN_SENTINEL"

SENTINEL_PLAN_TEXT = f"""
Plan hash value: 77
---------------------------------------------------------------
| Id | Operation          | Name | Rows | Cost (%CPU) | Time     |
---------------------------------------------------------------
|  0 | SELECT STATEMENT   |      |   10 |    68 (0)   | 00:00:01 |
|* 1 | TABLE ACCESS FULL  | T    |   10 |    68 (0)   | 00:00:01 |
---------------------------------------------------------------
Predicate Information (identified by operation id):
---------------------------------------------------
   1 - filter("A"."NAME"='{PLAN_SENTINEL}')
"""


async def test_analyze_never_sends_raw_execution_plan_to_ai(client, monkeypatch):
    captured: list[dict] = []

    async def _spy(**kwargs):
        captured.append(kwargs)
        return AiResult(status="unavailable", message="測試用")

    monkeypatch.setattr(api_module.ai_service, "get_ai_result", _spy)
    resp = await client.post(
        "/api/analyze",
        json={
            "application_no": "A1",
            "cost": 68,
            "sql": "SELECT A.X FROM T A WHERE A.NAME = 'TEST'",
            "execution_plan": SENTINEL_PLAN_TEXT,
            "include_ai": True,
        },
    )
    assert resp.status_code == 200
    assert len(captured) == 1

    # Every keyword the AI service received — including findings and parsed
    # statements — must be free of the raw plan text.
    serialized_call = json.dumps(captured[0], default=str, ensure_ascii=False)
    assert PLAN_SENTINEL not in serialized_call
    assert "Plan hash value" not in serialized_call
    assert "TABLE ACCESS FULL" not in serialized_call

    # ...and so must the AI section the frontend renders.
    serialized_ai = json.dumps(resp.json()["ai"], default=str, ensure_ascii=False)
    assert PLAN_SENTINEL not in serialized_ai
    assert "Plan hash value" not in serialized_ai


async def test_analyze_never_archives_raw_execution_plan(client, monkeypatch, tmp_path):
    settings = get_settings()
    archived_settings = dataclasses.replace(
        settings,
        archive=dataclasses.replace(settings.archive, enabled=True, dir=tmp_path / "archive"),
    )
    monkeypatch.setattr(api_module, "get_settings", lambda: archived_settings)

    async def _ai_stub(**_kwargs):
        return AiResult(status="unavailable", message="測試用")

    monkeypatch.setattr(api_module.ai_service, "get_ai_result", _ai_stub)
    resp = await client.post(
        "/api/analyze",
        json={
            "application_no": "A1",
            "cost": 68,
            "sql": "SELECT A.X FROM PLAN_ARCHIVE_PROOF_TABLE A WHERE A.Y = 1",
            "execution_plan": SENTINEL_PLAN_TEXT,
            "include_ai": True,
        },
    )
    assert resp.status_code == 200

    files = list((tmp_path / "archive").glob("*.jsonl"))
    assert files, "the include_ai=true pass must still write the de-identified record"
    archived = files[0].read_text(encoding="utf-8")
    # Control value first: the record really was written for this analysis.
    assert "PLAN_ARCHIVE_PROOF_TABLE" in archived
    assert PLAN_SENTINEL not in archived
    assert "Plan hash value" not in archived
    assert "TABLE ACCESS FULL" not in archived


async def test_unexpected_plan_parser_failure_never_leaks_plan_text_or_breaks_sql_review(
    client, monkeypatch, caplog
):
    def _boom(_text, **_kwargs):
        raise RuntimeError(f"simulated parser failure carrying {PLAN_SENTINEL}")

    monkeypatch.setattr(api_module.execution_plan, "analyze", _boom)
    caplog.set_level(logging.DEBUG)
    resp = await client.post(
        "/api/analyze",
        json={
            "application_no": "A1",
            "cost": 68,
            "sql": "SELECT A.X FROM T A WHERE A.Y = 1",
            "execution_plan": SENTINEL_PLAN_TEXT,
            "include_ai": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_plan"]["recognized"] is False
    assert data["execution_plan"]["steps"] == []
    assert "執行計畫內容暫時無法解析" in data["execution_plan"]["message"]

    assert PLAN_SENTINEL not in resp.text
    assert "simulated parser failure" not in caplog.text
    assert PLAN_SENTINEL not in caplog.text
    # Only the exception *type* may be logged (PRD §50.4).
    assert "execution_plan.analyze raised unexpectedly: RuntimeError" in caplog.text

    # The deterministic SQL review itself is untouched by the plan failure.
    assert data["compliance"]["status"] == "PASS"
    assert data["improvement"]["score"] >= 0


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


async def test_extract_sql_returns_safe_500_when_sql_detect_raises_unexpectedly(client, monkeypatch):
    def _boom(_text, _ext):
        raise RuntimeError("simulated sql_detect failure")

    monkeypatch.setattr(api_module.sql_detect, "detect_sql", _boom)
    files = {"file": ("q.sql", b"SELECT 1 FROM DUAL", "application/octet-stream")}
    resp = await client.post("/api/extract-sql", files=files)
    assert resp.status_code == 500
    assert resp.json()["detail"] == api_module._EXTRACT_FAILED_MESSAGE


async def test_extract_sql_does_not_write_any_temp_file(client):
    tmp_dir = tempfile.gettempdir()
    before = set(os.listdir(tmp_dir))
    content = fx.build_docx_bytes(paragraphs=["SELECT A.X FROM T A WHERE A.Y=1"])
    files = {"file": ("report.docx", content, "application/octet-stream")}
    resp = await client.post("/api/extract-sql", files=files)
    assert resp.status_code == 200
    after = set(os.listdir(tmp_dir))
    assert after == before, f"extract-sql left new files in {tmp_dir}: {after - before}"


# ---------------------------------------------------------------------------
# /api/extract-plan
# ---------------------------------------------------------------------------
async def test_extract_plan_reads_sql_developer_txt_without_sql_detection(client):
    files = {"file": ("plan.txt", ESTIMATED_PLAN_TEXT.encode(), "text/plain")}
    resp = await client.post("/api/extract-plan", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "TABLE ACCESS FULL" in data["plan_text"]
    assert data["truncated"] is False


async def test_extract_plan_accepts_csv_export(client):
    files = {"file": ("plan.csv", b"Id,Operation,Name\n0,SELECT STATEMENT,", "text/csv")}
    resp = await client.post("/api/extract-plan", files=files)
    assert resp.status_code == 200
    assert "SELECT STATEMENT" in resp.json()["plan_text"]


async def test_extract_plan_rejects_non_text_export(client):
    files = {"file": ("plan.pdf", b"%PDF-1.4", "application/pdf")}
    resp = await client.post("/api/extract-plan", files=files)
    assert resp.status_code == 400
    assert "TXT" in resp.json()["detail"]


async def test_extract_plan_rejects_empty_upload(client):
    files = {"file": ("plan.txt", b"", "text/plain")}
    resp = await client.post("/api/extract-plan", files=files)
    assert resp.status_code == 400
    assert "檔案內容為空" in resp.json()["detail"]


async def test_extract_plan_rejects_oversized_upload(client):
    big = b"x" * (11 * 1024 * 1024)  # default limit is 10 MB
    files = {"file": ("plan.txt", big, "text/plain")}
    resp = await client.post("/api/extract-plan", files=files)
    assert resp.status_code == 400
    assert "超過允許大小" in resp.json()["detail"]


async def test_extract_plan_rejects_executable_content_disguised_as_txt(client):
    files = {"file": ("plan.txt", b"MZ\x90\x00", "text/plain")}
    resp = await client.post("/api/extract-plan", files=files)
    assert resp.status_code == 400
    assert "可執行檔" in resp.json()["detail"]


async def test_extract_plan_reports_truncation_without_failing(client, monkeypatch):
    settings = get_settings()
    limited = dataclasses.replace(
        settings,
        upload=dataclasses.replace(settings.upload, max_extracted_chars=50),
    )
    monkeypatch.setattr(api_module, "get_settings", lambda: limited)

    long_plan = ("| Id | Operation | Name |\n" + "|  1 | TABLE ACCESS FULL | T |\n" * 20).encode()
    files = {"file": ("plan.txt", long_plan, "text/plain")}
    resp = await client.post("/api/extract-plan", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["truncated"] is True
    assert len(data["plan_text"]) == 50
    assert "截取" in data["message"]


async def test_extract_plan_does_not_write_any_temp_file(client):
    tmp_dir = tempfile.gettempdir()
    before = set(os.listdir(tmp_dir))
    files = {"file": ("plan.txt", ESTIMATED_PLAN_TEXT.encode(), "text/plain")}
    resp = await client.post("/api/extract-plan", files=files)
    assert resp.status_code == 200
    after = set(os.listdir(tmp_dir))
    assert after == before, f"extract-plan left new files in {tmp_dir}: {after - before}"


async def test_upload_then_analyze_keeps_plan_evidence_deterministic_and_additive(client):
    """Synthetic API-level END-TO-END for the UI flow (upload → analyze):
    plan.csv → /api/extract-plan → /api/analyze → structured plan evidence.

    No browser E2E infrastructure exists for this project (see AGENTS.md's
    manual-evidence policy), so this test plus the frontend component tests
    are the executable deterministic flow."""
    csv_plan = (
        "Id,Operation,Options,Object_Name,Cardinality,Cost,Filter_Predicates\n"
        "0,SELECT STATEMENT,,,25,14,\n"
        "1,TABLE ACCESS,FULL,TAX_CASE,25,14,TRUNC(A.CASE_DATE)=DATE_VALUE"
    )
    upload = await client.post(
        "/api/extract-plan",
        files={"file": ("plan.csv", csv_plan.encode(), "text/csv")},
    )
    assert upload.status_code == 200
    upload_data = upload.json()
    assert upload_data["truncated"] is False

    body = {
        "application_no": "115000218",
        "cost": 14,
        "sql": "SELECT A.X FROM TAX_CASE A WHERE TRUNC(A.CASE_DATE) = :D",
    }
    with_plan = await client.post(
        "/api/analyze",
        json={**body, "execution_plan": upload_data["plan_text"], "include_ai": False},
    )
    without_plan = await client.post(
        "/api/analyze", json={**body, "execution_plan": None, "include_ai": False}
    )
    assert with_plan.status_code == 200

    data = with_plan.json()
    evidence = data["execution_plan"]
    assert evidence["recognized"] is True
    assert evidence["source"] == "estimated"
    assert evidence["source_label"] == "測試機預估執行計畫"
    assert evidence["cost_matches_input"] is True
    step1 = next(step for step in evidence["steps"] if step["id"] == 1)
    assert step1["operation"] == "TABLE ACCESS"
    assert step1["options"] == "FULL"
    assert any(item["code"] == "TABLE_ACCESS_FULL" for item in evidence["observations"])

    # Plan evidence is additive only: the deterministic verdict and the
    # 改善指數 are byte-for-byte the same as the same SQL without a plan.
    assert data["compliance"] == without_plan.json()["compliance"]
    assert data["improvement"] == without_plan.json()["improvement"]
    assert data["rules"] == without_plan.json()["rules"]
