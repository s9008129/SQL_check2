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


def _ext_of(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx >= 0 else ""


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    try:
        available = await ai_service.check_ollama_available(settings)
    except Exception:  # noqa: BLE001 - health check must never itself fail
        logger.exception("check_ollama_available raised unexpectedly")
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

    detected = sql_detect.detect_sql(extracted.text, _ext_of(filename))

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
    parsed = parse_sql_text(payload.sql)

    compliance, rule_rows, findings = rule_engine.evaluate(
        parsed, payload.cost, settings.rules_config, settings.important_tables_config
    )

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
        except Exception:  # noqa: BLE001 - AI must never be a single point of failure (PRD §51)
            logger.exception("ai_service.get_ai_result raised unexpectedly")
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
