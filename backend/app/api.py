"""HTTP layer for the three PRD §40 endpoints.

This module only orchestrates: sql_parser -> rule_engine -> improvement_score
-> (optionally) ai_service. It never re-implements any of their judgment —
compliance and the improvement score come entirely from rule_engine.py /
improvement_score.py, never from this layer or from the AI (PRD §13.1).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas import (
    AiResult,
    AnalyzeRequest,
    AnalyzeResponse,
    ExtractSqlResponse,
    HealthResponse,
    StatementSummary,
)
from app.services import ai_service, file_extract, improvement_score, rule_engine, sql_detect
from app.services.file_extract import AttachmentError
from app.services.sql_parser import parse_sql_text
from app.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

_AI_UNAVAILABLE_MESSAGE = "智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。"
_ANALYZE_FAILED_MESSAGE = "系統暫時無法完成檢核，請稍後再試一次。"
_EXTRACT_FAILED_MESSAGE = "附件內容無法辨識，請確認檔案內容，或直接貼上 SQL。"


def _log_exception_type_only(message: str, exc: Exception) -> None:
    """PRD §50.4 allows logging an exception's *type*, never its message or
    a traceback — several exception types reachable from this module
    (confirmed: sqlglot's ParseError) embed a raw snippet of the SQL/literal
    text that triggered them in `str(exc)`. Deliberately uses `logger.error`
    with only `type(exc).__name__`, never `logger.exception`/`exc_info=True`,
    so this stays true even if some future exception type also embeds
    sensitive text — safety does not depend on auditing every call site by
    hand each time the code changes."""
    logger.error("%s: %s", message, type(exc).__name__)


def _ext_of(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx >= 0 else ""


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    try:
        available = await ai_service.check_ollama_available(settings)
    except Exception as exc:  # noqa: BLE001 - health check must never itself fail
        _log_exception_type_only("check_ollama_available raised unexpectedly", exc)
        available = False
    return HealthResponse(status="ok", ai_available=available)


@router.post("/extract-sql", response_model=ExtractSqlResponse)
async def extract_sql(file: Annotated[UploadFile, File(...)]) -> ExtractSqlResponse:
    settings = get_settings()
    filename = file.filename or "upload"
    content = await file.read()
    try:
        extracted = file_extract.extract_text(filename, content, settings)
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()

    try:
        detected = sql_detect.detect_sql(extracted.text, _ext_of(filename))
    except Exception as exc:  # noqa: BLE001 - defense-in-depth: sql_parser internally
        # guards its own sqlglot calls, but never let an unexpected failure
        # here fall through to FastAPI's default handler, whose traceback
        # could otherwise embed raw SQL text (sqlglot ParseError does).
        _log_exception_type_only("sql_detect.detect_sql raised unexpectedly", exc)
        raise HTTPException(status_code=500, detail=_EXTRACT_FAILED_MESSAGE) from None

    return ExtractSqlResponse(
        status="ok",
        filename=filename,
        sql=detected.sql,
        statement_count=detected.statement_count,
        needs_confirmation=detected.needs_confirmation,
        message=detected.message,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    settings = get_settings()
    try:
        parsed = parse_sql_text(payload.sql)
        compliance, rule_rows, findings = rule_engine.evaluate(
            parsed, payload.cost, settings.rules_config, settings.important_tables_config
        )
    except Exception as exc:  # noqa: BLE001 - defense-in-depth: both functions already
        # guard their own sqlglot calls internally, but never let an
        # unexpected failure fall through to FastAPI's default handler,
        # whose traceback could otherwise embed raw SQL text (sqlglot
        # ParseError does) — the deterministic rule check must fail safely,
        # never silently return a fabricated PASS (PRD §15).
        _log_exception_type_only("sql_parser/rule_engine raised unexpectedly", exc)
        raise HTTPException(status_code=500, detail=_ANALYZE_FAILED_MESSAGE) from None

    if payload.include_ai:
        try:
            ai_result: AiResult = await ai_service.get_ai_result(
                sql_text=payload.sql,
                cost=payload.cost,
                compliance_status=compliance.status,
                findings=findings,
                statements=parsed.statements,
                settings=settings,
            )
        except Exception as exc:  # noqa: BLE001 - AI must never be a single point of failure (PRD §51)
            _log_exception_type_only("ai_service.get_ai_result raised unexpectedly", exc)
            ai_result = AiResult(status="unavailable", message=_AI_UNAVAILABLE_MESSAGE)
    else:
        ai_result = AiResult(status="pending")

    improvement = improvement_score.compute(
        parsed.statements,
        findings,
        payload.cost,
        settings.rules_config,
        ai_advice=ai_result.advice if ai_result.status == "ok" else None,
    )

    statements_summary = [
        StatementSummary(
            index=s.index,
            statement_type=s.statement_type,
            parse_status=s.parse_status,
            tables=sorted(s.tables),
        )
        for s in parsed.statements
    ]

    return AnalyzeResponse(
        application_no=payload.application_no,
        cost=payload.cost,
        compliance=compliance,
        improvement=improvement,
        rules=rule_rows,
        findings=findings,
        statements=statements_summary,
        parse_message=parsed.parse_message,
        ai=ai_result,
    )
