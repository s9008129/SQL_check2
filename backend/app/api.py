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
    ExecutionPlanAnalysis,
    ExtractPlanResponse,
    ExtractSqlResponse,
    HealthResponse,
    StatementSummary,
    VerifiedRewrite,
)
from app.services import (
    ai_service,
    execution_plan,
    file_extract,
    improvement_score,
    pattern_selector,
    performance_evidence,
    rewrite_rules,
    rule_engine,
    sql_archive,
    sql_detect,
)
from app.services.file_extract import AttachmentError
from app.services.sql_parser import parse_sql_text
from app.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

_AI_UNAVAILABLE_MESSAGE = "智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。"
_ANALYZE_FAILED_MESSAGE = "系統暫時無法完成檢核，請稍後再試一次。"
_EXTRACT_FAILED_MESSAGE = "附件內容無法辨識，請確認檔案內容，或直接貼上 SQL。"
_PLAN_EXTRACT_FAILED_MESSAGE = "執行計畫附件無法讀取，請改貼文字，或使用 SQL Developer 匯出的 TXT／CSV。"
_PLAN_UPLOAD_EXTENSIONS = frozenset({".txt", ".csv"})

_VERIFIED_REWRITE_METADATA = {
    "or_eq_to_in": ("R006", "同欄位 OR 改為 IN"),
    "substr_eq_to_like": ("R005", "SUBSTR 比對改為 LIKE"),
}


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


def _find_verified_rewrites(parsed) -> list[VerifiedRewrite]:
    """Build the response-owned deterministic rewrite contract."""
    rewrites: list[VerifiedRewrite] = []
    for statement in parsed.statements:
        if statement.parse_status != "ok" or statement.statement_type != "SELECT":
            continue
        for candidate in rewrite_rules.find_verified_rewrites(statement.raw_sql):
            metadata = _VERIFIED_REWRITE_METADATA.get(candidate.rule)
            if metadata is None:
                continue
            source_rule_id, title = metadata
            rewrites.append(
                VerifiedRewrite(
                    statement_index=statement.index,
                    rule=candidate.rule,
                    source_rule_id=source_rule_id,
                    title=title,
                    before=candidate.before,
                    after=candidate.after,
                )
            )
    return rewrites


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    try:
        available = await ai_service.check_llm_available(settings)
    except Exception as exc:  # noqa: BLE001 - health check must never itself fail
        _log_exception_type_only("check_llm_available raised unexpectedly", exc)
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


@router.post("/extract-plan", response_model=ExtractPlanResponse)
async def extract_plan(file: Annotated[UploadFile, File(...)]) -> ExtractPlanResponse:
    """Extract SQL Developer plan text without trying to interpret it as SQL.

    TXT/CSV are intentionally the only upload formats in v1. SQL Developer
    users can always copy/paste plan text directly; keeping plan uploads
    text-only avoids OCR and ambiguous screenshot parsing.
    """
    settings = get_settings()
    filename = file.filename or "execution-plan.txt"
    if _ext_of(filename) not in _PLAN_UPLOAD_EXTENSIONS:
        await file.close()
        raise HTTPException(
            status_code=400,
            detail="執行計畫附件請使用 SQL Developer 匯出的 TXT 或 CSV，或直接貼上文字。",
        )

    content = await file.read()
    try:
        extracted = file_extract.extract_text(filename, content, settings)
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - never leak uploaded plan text through tracebacks
        _log_exception_type_only("execution-plan attachment extraction failed", exc)
        raise HTTPException(status_code=500, detail=_PLAN_EXTRACT_FAILED_MESSAGE) from None
    finally:
        await file.close()

    message = "已讀取執行計畫文字，可確認內容後開始檢核。"
    if extracted.truncated:
        message = "執行計畫內容較長，已依系統上限截取前段文字；建議改貼單一 SQL 的計畫。"
    return ExtractPlanResponse(
        status="ok",
        filename=filename,
        plan_text=extracted.text,
        truncated=extracted.truncated,
        message=message,
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

    verified_rewrites = _find_verified_rewrites(parsed)

    # Oracle 11g evidence is selected by deterministic facts, never by AI.
    # A registry/configuration defect must not take down the core rule review.
    try:
        selected_patterns = pattern_selector.select_patterns(
            parsed.statements,
            findings,
            settings.rules_config,
        )
        performance_evidence_items = performance_evidence.build_performance_evidence(
            selected_patterns,
            verified_rewrites,
        )
    except Exception as exc:  # noqa: BLE001 - evidence is supplemental, fail safe
        _log_exception_type_only("performance evidence selection failed", exc)
        performance_evidence_items = []

    plan_analysis: ExecutionPlanAnalysis | None = None
    if payload.execution_plan:
        try:
            plan_analysis = execution_plan.analyze(
                payload.execution_plan,
                expected_cost=payload.cost,
                verified_rewrites=verified_rewrites,
            )
        except Exception as exc:  # noqa: BLE001 - plan evidence must never break SQL review
            _log_exception_type_only("execution_plan.analyze raised unexpectedly", exc)
            plan_analysis = execution_plan.unrecognized(
                "執行計畫內容暫時無法解析；SQL 規則檢核仍可正常使用。"
            )

    plan_ai_context = execution_plan.build_ai_context(
        plan_analysis,
        allowed_tables={
            table
            for statement in parsed.statements
            for table in statement.tables
        },
    )

    if payload.include_ai:
        try:
            ai_result: AiResult = await ai_service.get_ai_result(
                sql_text=payload.sql,
                cost=payload.cost,
                compliance_status=compliance.status,
                findings=findings,
                statements=parsed.statements,
                execution_plan_context=plan_ai_context,
                performance_evidence_items=performance_evidence_items,
                settings=settings,
            )
        except Exception as exc:  # noqa: BLE001 - AI must never be a single point of failure (PRD §51)
            _log_exception_type_only("ai_service.get_ai_result raised unexpectedly", exc)
            ai_result = AiResult(status="unavailable", message=_AI_UNAVAILABLE_MESSAGE)
    else:
        ai_result = AiResult(status="pending")

    # 2026-09-17 使用者決策：指數完全由確定性事實計算，AI 建議（數量與 impact）
    # 不得影響分數；因此這裡不再傳入任何 AI 輸出。
    improvement = improvement_score.compute(
        parsed.statements,
        findings,
        payload.cost,
        settings.rules_config,
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

    if payload.include_ai:
        # 2026-09-16: de-identified SQL archive (see sql_archive.py's module
        # docstring for the PRD §6.3 exception this represents). Only
        # recorded on the frontend's second/final /api/analyze call
        # (include_ai=true) so each submission is archived once, with its
        # final AI outcome included — not once per keystroke/attempt.
        # Fully isolated: never allowed to affect this response.
        try:
            sql_archive.record_analysis(
                parsed=parsed,
                compliance=compliance,
                rule_rows=rule_rows,
                findings=findings,
                improvement=improvement,
                ai_result=ai_result,
                cost=payload.cost,
                settings=settings,
                sql_text=payload.sql,
            )
        except Exception as exc:  # noqa: BLE001 - archive must never affect the response
            _log_exception_type_only("sql_archive.record_analysis raised unexpectedly", exc)

    return AnalyzeResponse(
        application_no=payload.application_no,
        cost=payload.cost,
        compliance=compliance,
        improvement=improvement,
        rules=rule_rows,
        findings=findings,
        statements=statements_summary,
        verified_rewrites=verified_rewrites,
        performance_evidence=performance_evidence_items,
        execution_plan=plan_analysis,
        parse_message=parsed.parse_message,
        ai=ai_result,
    )
