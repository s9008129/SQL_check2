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


class VerifiedRewrite(BaseModel):
    """A server-derived, result-preserving predicate rewrite."""

    statement_index: int
    rule: str
    source_rule_id: str
    title: str
    before: str
    after: str


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
    component: Literal["rule_findings", "structure", "cost_ratio", "structure_floor", "block_floor"]
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
    # 2026-09-17: what the server could prove about before→example.
    #   verified   — the model's fragment matches a rule-derived equivalent
    #   corrected  — it did not; `example` now holds the system's equivalent
    #   unverified — no rule covers this change; concrete example/before are
    #                stripped before the API response, so the UI shows prose only
    #   None       — no fragment
    verification: Literal["verified", "corrected", "unverified"] | None = None
    # Caveat under which the rule's equivalence holds (e.g. bind is a date
    # without time), when any.
    assumption: str | None = None


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
    # Kept for the archive/analytics only; the UI no longer shows a
    # percentage (2026-09-17 user decision: the number was never measured).
    estimated_improvement_pct: int | None = None
    # 2026-09-17: deterministic improvement-potential level derived by the
    # server from server-observable facts only (rule findings, whether a
    # fragment was revalidated as result-preserving, whether a full rewrite
    # passed re-validation) — see ai_service.improvement_potential. The
    # model's own `impact` never sets this level.
    #   high/medium/low — confirmed improvement evidence exists
    #   "notice_only"   — only governance reminders (e.g. R007 重要資料表)
    #                     with no confirmed SQL-writing improvement point;
    #                     the UI must NOT say 「目前寫法良好」 for this
    #   None            — nothing was found at all
    improvement_potential: Literal["high", "medium", "low", "notice_only"] | None = None
    # Plain-language lines explaining what the level was derived from.
    improvement_potential_basis: list[str] = Field(default_factory=list)
    message: str | None = None
    # 2026-09-17: why status is "unavailable" (output_truncated /
    # prompt_truncated / timeout / connection / http / invalid_response).
    # Diagnostic only; `message` already carries the reviewer-facing text.
    degrade_code: str | None = None


class AnalyzeResponse(BaseModel):
    application_no: str
    cost: int
    compliance: ComplianceResult
    improvement: ImprovementResult
    rules: list[RuleRow]
    findings: list[Finding]
    statements: list[StatementSummary]
    verified_rewrites: list[VerifiedRewrite] = Field(default_factory=list)
    parse_message: str | None = None
    ai: AiResult
