"""De-identified SQL archive (2026-09-16, user-requested): a simple JSON
Lines store of every SQL checked through `/api/analyze`, kept so the data
can later be handed to an AI (or a human) for offline analysis, statistics,
and optimization pattern-mining across many submissions.

This is a deliberate, user-approved exception to PRD §6.3's "never persist
the application number / original SQL / COST / AI advice / suggested
rewrite" list — see app.yaml's `archive` section comment and
`sqlcheck2-decisions` memory for the decision record. To keep that exception
as narrow as possible, this module:

- Never stores the application number, the original (non-deidentified) SQL
  text, any `masking.py` reverse_map, the uploaded attachment's filename, or
  any user/IP/request metadata.
- Runs every piece of SQL text through `masking.deidentify_sql` (stricter
  than the AI-request-path `mask_sql`: also strips free-text comments and
  sweeps for ID-number/email/long-digit shapes) before it is ever written.
- Is fully additive and best-effort: any failure here (disk full,
  permission denied, directory missing) is logged (exception type only,
  PRD §50.4) and silently dropped — this module must never affect the
  /api/analyze response or raise into api.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.schemas import AiResult, ComplianceResult, Finding, ImprovementResult, RuleRow
from app.services.masking import deidentify_sql
from app.services.sql_parser import ParsedSql
from app.settings import Settings

logger = logging.getLogger(__name__)

# Taiwan local-tax deployment: timestamps are recorded in local (UTC+8) time
# rather than UTC, for direct readability by staff reviewing the archive.
_TAIWAN_TZ = timezone(timedelta(hours=8))

# Serializes appends across concurrent requests within this process. A
# single `open(..., "a")` write is already atomic for one line on both
# POSIX and Windows for writes below the filesystem's pipe/buffer size, but
# the lock also protects the one-file-per-month path resolution from a
# theoretical race right at a month boundary.
_write_lock = threading.Lock()


def _sql_fingerprint(deidentified_sql: str) -> str:
    """First 16 hex chars of a SHA-256 over the de-identified, whitespace-
    normalized SQL — lets later analysis group repeated submissions of
    (structurally) the same query without ever being reversible to the
    original text."""
    normalized = " ".join(deidentified_sql.split()).upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def build_record(
    *,
    parsed: ParsedSql,
    compliance: ComplianceResult,
    rule_rows: list[RuleRow],
    findings: list[Finding],
    improvement: ImprovementResult,
    ai_result: AiResult,
    cost: int,
) -> dict[str, Any]:
    """Pure function (no I/O) that builds one JSON-serializable archive
    record from the same objects api.py already has in scope after calling
    sql_parser/rule_engine/improvement_score/ai_service. Never raises on
    reasonable input; the caller (`record_analysis`) still wraps this in a
    try/except as defense in depth."""
    original_sql_text = "\n".join(s.raw_sql for s in parsed.statements) if parsed.statements else ""
    sql_deidentified = deidentify_sql(original_sql_text)

    statements = [
        {
            "index": s.index,
            "type": s.statement_type,
            "parse_status": s.parse_status,
            "tables": sorted(s.tables),
            "complexity_flags": sorted(s.complexity_flags),
            "restriction_kind": s.restriction_kind,
        }
        for s in parsed.statements
    ]

    suggested_sql_deidentified = None
    if ai_result.suggested_sql and ai_result.suggested_sql.available and ai_result.suggested_sql.sql:
        suggested_sql_deidentified = deidentify_sql(ai_result.suggested_sql.sql)

    return {
        "schema_version": 1,
        "id": str(uuid.uuid4()),
        "ts": datetime.now(_TAIWAN_TZ).isoformat(),
        "sql_deidentified": sql_deidentified,
        "sql_fingerprint": _sql_fingerprint(sql_deidentified),
        "sql_chars": len(original_sql_text),
        "statement_count": len(parsed.statements),
        "statements": statements,
        "cost": cost,
        "compliance": {
            "status": compliance.status,
            "notice_count": compliance.notice_count,
            "block_count": compliance.block_count,
        },
        "rules": [{"rule_id": r.rule_id, "status": r.status} for r in rule_rows],
        "findings": [
            {"rule_id": f.rule_id, "status": f.status, "statement_index": f.statement_index} for f in findings
        ],
        "improvement": {"score": improvement.score, "level": improvement.level},
        "ai": {
            "status": ai_result.status,
            "advice": [
                {"title": a.title, "explanation": a.explanation, "impact": a.impact} for a in ai_result.advice
            ],
            "suggested_available": bool(ai_result.suggested_sql and ai_result.suggested_sql.available),
            "suggested_sql_deidentified": suggested_sql_deidentified,
            "estimated_improvement_pct": ai_result.estimated_improvement_pct,
        },
    }


def _resolve_archive_path(settings: Settings) -> Path:
    now = datetime.now(_TAIWAN_TZ)
    return settings.archive.dir / f"sql_archive-{now.strftime('%Y-%m')}.jsonl"


def append_record(record: dict[str, Any], settings: Settings) -> None:
    """Append one record as a single JSON Line to this month's archive
    file, creating the directory if needed. Never raises: any failure is
    logged (exception type only) and dropped — the archive is a best-effort
    analytics aid, never allowed to affect the user-facing response."""
    if not settings.archive.enabled:
        return
    try:
        path = _resolve_archive_path(settings)
        line = json.dumps(record, ensure_ascii=False)
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:
        logger.error("sql_archive.append_record: failed to write archive record: %s", type(exc).__name__)


def record_analysis(
    *,
    parsed: ParsedSql,
    compliance: ComplianceResult,
    rule_rows: list[RuleRow],
    findings: list[Finding],
    improvement: ImprovementResult,
    ai_result: AiResult,
    cost: int,
    settings: Settings,
) -> None:
    """The one entrypoint api.py calls: build + append, both fully guarded.
    Never raises, regardless of `settings.archive.enabled`."""
    if not settings.archive.enabled:
        return
    try:
        record = build_record(
            parsed=parsed,
            compliance=compliance,
            rule_rows=rule_rows,
            findings=findings,
            improvement=improvement,
            ai_result=ai_result,
            cost=cost,
        )
    except Exception as exc:
        logger.error("sql_archive.record_analysis: failed to build archive record: %s", type(exc).__name__)
        return
    append_record(record, settings)
