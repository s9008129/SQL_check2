"""Pydantic request/response models for the three SQLCheck 2.0 endpoints
(PRD §40) plus the shared result shapes used internally by rule_engine.py,
improvement_score.py and ai_service.py.

These models are the contract between backend services and the API layer;
services return these types directly rather than duplicating parallel
"internal" DTOs, per AGENTS.md "smallest change that works".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.cost_utils import normalize_cost

RuleStatus = Literal["PASS", "NOTICE", "BLOCK", "REVIEW", "NA"]
ComplianceStatus = Literal["PASS", "BLOCK", "REVIEW"]
ImprovementLevel = Literal["GOOD", "IMPROVE", "PRIORITY"]
AiStatus = Literal["ok", "pending", "unavailable"]
ImpactLevel = Literal["low", "medium", "high"]


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    ai_available: bool


# ---------------------------------------------------------------------------
# /api/extract-sql
# ---------------------------------------------------------------------------
class ExtractSqlResponse(BaseModel):
    status: Literal["ok"] = "ok"
    filename: str
    sql: str = ""
    statement_count: int = 0
    needs_confirmation: bool = False
    message: str


# ---------------------------------------------------------------------------
# /api/analyze — request
# ---------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    application_no: str = Field(min_length=1, max_length=50)
    cost: str | int
    sql: str = Field(min_length=1)
    include_ai: bool = False

    @field_validator("application_no")
    @classmethod
    def _strip_application_no(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("請輸入申請單號。")
        return v

    @field_validator("cost")
    @classmethod
    def _normalize_cost(cls, v: str | int) -> int:
        return normalize_cost(v)

    @field_validator("sql")
    @classmethod
    def _strip_sql(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("請輸入 SQL。")
        return v


# ---------------------------------------------------------------------------
# /api/analyze — response building blocks
# ---------------------------------------------------------------------------
class Finding(BaseModel):
    """One concrete rule detection, scoped to a single statement."""

    rule_id: str
    status: Literal["NOTICE", "BLOCK", "REVIEW"]
    fact: str
    statement_index: int
    table: str | None = None


class RuleRow(BaseModel):
    """One row of the 中心規則比對 table — aggregated across all statements."""

    rule_id: str
    name: str
    status: RuleStatus
    evidence: str
    note: str


class ComplianceResult(BaseModel):
    status: ComplianceStatus
    label: str
    notice_count: int
    block_count: int


class ImprovementBreakdownItem(BaseModel):
    component: Literal[
        "rule_findings", "structure", "cost_ratio", "ai_adjustment", "block_floor"
    ]
    label: str
    score: float
    # 2026-09-17: one plain-language sentence per component ("目前 COST 約為
    # 門檻的 69%…") so the UI can explain the score without knowing rules.yaml.
    detail: str | None = None


class ImprovementResult(BaseModel):
    score: int
    level: ImprovementLevel
    label: str
    color: Literal["green", "yellow", "red"]
    breakdown: list[ImprovementBreakdownItem]


class StatementSummary(BaseModel):
    index: int
    statement_type: str
    parse_status: Literal["ok", "failed"]
    tables: list[str]


class AdviceItem(BaseModel):
    title: str
    explanation: str
    example: str | None = None
    impact: ImpactLevel | None = None
    # 2026-09-17: the exact original fragment `example` replaces (verbatim
    # from the SQL), so the UI can render a precise before/after diff per
    # advice item instead of only a free-floating snippet. Placeholders are
    # un-masked server-side before the response is returned.
    before: str | None = None


RewriteOutcome = Literal["provided", "not_needed", "advice_only", "gated", "rejected"]


class SuggestedSql(BaseModel):
    available: bool
    reason: str
    sql: str | None = None
    # 2026-09-17: *why* there is (or isn't) a rewrite, so the UI can say
    # different things for genuinely different situations instead of one
    # fixed "declined" sentence:
    #   provided    – a validated rewrite is in `sql`
    #   not_needed  – the model judged the SQL already good; nothing to rewrite
    #   advice_only – improvements exist but an equivalent rewrite needs a
    #                 business assumption (see advice examples)
    #   gated       – server gate (multi-statement / non-SELECT / parse /
    #                 forbidden complexity) — model never asked to rewrite
    #   rejected    – model proposed a rewrite, server re-validation refused it
    outcome: RewriteOutcome = "advice_only"


class AiResult(BaseModel):
    status: AiStatus
    summary: str | None = None
    advice: list[AdviceItem] = Field(default_factory=list)
    suggested_sql: SuggestedSql | None = None
    estimated_improvement_pct: int | None = None
    message: str | None = None


class AnalyzeResponse(BaseModel):
    application_no: str
    cost: int
    compliance: ComplianceResult
    improvement: ImprovementResult
    rules: list[RuleRow]
    findings: list[Finding]
    statements: list[StatementSummary]
    parse_message: str | None = None
    ai: AiResult
