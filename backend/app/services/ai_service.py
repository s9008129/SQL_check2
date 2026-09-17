"""AI advisory service (PRD §17.4, §20, §22, §23, §25, §46, §47, §56):
wraps a single Ollama `/api/chat` call behind a small, deterministic
pre/post-processing pipeline.

Hard boundaries this module exists to enforce (PRD §13.1, §56 — repeated
here because every function below exists to defend one of these):

- The AI never decides compliance, never decides the improvement score,
  never invents Execution Plan / index / full-table-scan facts, and never
  fabricates a post-improvement Oracle COST. It only explains, advises, and
  optionally proposes one rewrite / one heuristic improvement percentage.
- The AI is never a single point of failure: every failure mode (connection
  refused, timeout, invalid JSON even after one retry, or any unexpected
  bug in this module) degrades to `AiResult(status="unavailable", ...)`
  with the PRD-mandated frontend message — this module's public functions
  never raise.
- `candidate_allowed` / `estimate_improvement_allowed` are computed here,
  deterministically, from rule_engine/sql_parser facts and `app.yaml`'s
  `ai_gate` config — never from anything the model says. Even if the model
  ignores its instructions and returns `suggested_sql.available=true` while
  `candidate_allowed` is false, the server-side override in `_finalize_*`
  forces it back to false before it ever reaches the API response.
- Real literal values (string/date/large-numeric) never reach the model —
  `masking.mask_sql()` runs on the representative statement's SQL text
  before it is ever placed in the prompt, regardless of whether a candidate
  rewrite will be produced (PRD: sanitized_sql is used for explanation too).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.schemas import AdviceItem, AiResult, Finding, SuggestedSql
from app.services import rule_engine
from app.services.masking import mask_sql, unmask_sql
from app.services.rule_engine import GLOBAL_STATEMENT_INDEX
from app.services.sql_parser import ParsedStatement, parse_sql_text, structural_signature
from app.settings import PROMPTS_DIR, Settings

logger = logging.getLogger(__name__)

# PRD-mandated exact frontend copy for any AI failure path (§56).
DEGRADE_MESSAGE = "智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。"

_PROMPT_PATH = PROMPTS_DIR / "sql_review_zh_tw.txt"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

# Ollama serializes requests anyway (PRD §46); this makes it explicit and
# bounds how long a caller waits for the lock itself (see `_request_ai`).
_OLLAMA_SEMAPHORE = asyncio.Semaphore(1)

# Ollama /api/chat `format`: a raw JSON Schema object (not the string
# "json"), matching Pydantic field names in app.schemas exactly, so the
# model is constrained to emit exactly this shape.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "advice": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "example": {"type": "string"},
                    # The original fragment `example` replaces (verbatim),
                    # for a precise per-advice before/after diff in the UI.
                    "before": {"type": "string"},
                    "impact": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                # `example` is required (empty string for prose-only advice):
                # once `before` was added, the model started returning
                # `before` *instead of* `example` (confirmed live), leaving
                # nothing to diff against.
                "required": ["title", "explanation", "example"],
            },
        },
        "suggested_sql": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "reason": {"type": "string"},
                "sql": {"type": "string"},
                # 2026-09-17: the model must say *which kind* of "no rewrite"
                # this is, so the UI never shows the same fixed sentence for
                # "SQL is already fine" and "needs a business assumption".
                "rewrite_outcome": {"type": "string", "enum": ["provided", "not_needed", "advice_only"]},
            },
            "required": ["available", "reason", "rewrite_outcome"],
        },
        "estimated_improvement_pct": {"type": ["integer", "null"]},
    },
    "required": ["summary", "advice", "suggested_sql"],
}


class _RawSuggestedSql(BaseModel):
    """The model's own view of suggested_sql. `rewrite_outcome` is optional
    here (a schema-constrained Ollama reply always has it, but a mocked or
    older reply may not) — `_finalize_suggested_sql` falls back to
    "advice_only", the conservative reading."""

    available: bool
    reason: str
    sql: str | None = None
    rewrite_outcome: str | None = None


class _AiRawResponse(BaseModel):
    """Mirrors RESPONSE_SCHEMA for validating the model's raw JSON reply."""

    summary: str
    advice: list[AdviceItem] = Field(default_factory=list)
    suggested_sql: _RawSuggestedSql
    estimated_improvement_pct: int | None = None


# ---------------------------------------------------------------------------
# Deterministic gating (PRD §17.4, §25) — never influenced by the model.
# ---------------------------------------------------------------------------
def _compute_gates(
    statements: list[ParsedStatement], findings: list[Finding], ai_gate_cfg: dict[str, Any]
) -> tuple[bool, bool, str | None]:
    """candidate_allowed: exactly one statement, SELECT, parsed ok, and none
    of its complexity_flags intersect the configured forbidden set.
    estimate_improvement_allowed: equals candidate_allowed unless
    `ai_gate.estimate_requires_candidate` is false, in which case it is also
    allowed whenever there is at least one finding (both branches per spec).
    decline_code: None when candidate_allowed is True; otherwise the specific
    reason candidate_allowed is False (`multi_statement` / `not_select` /
    `parse_failed` / `complexity:<flag>`) so the reviewer-facing decline
    reason can be specific instead of always the same fixed sentence — see
    `_decline_reason_text`. This is purely explanatory; it never changes
    which SQL is or isn't allowed to be rewritten.
    """
    forbidden_flags = set(ai_gate_cfg.get("candidate_forbidden_complexity_flags", []))

    decline_code: str | None = None
    if len(statements) != 1:
        decline_code = "multi_statement"
    elif statements[0].statement_type != "SELECT":
        decline_code = "not_select"
    elif statements[0].parse_status != "ok":
        decline_code = "parse_failed"
    else:
        hit_flags = statements[0].complexity_flags & forbidden_flags
        if hit_flags:
            # Deterministic pick when more than one forbidden flag is hit.
            decline_code = f"complexity:{sorted(hit_flags)[0]}"

    candidate_allowed = decline_code is None

    if ai_gate_cfg.get("estimate_requires_candidate", True):
        estimate_allowed = candidate_allowed
    else:
        estimate_allowed = candidate_allowed or bool(findings)

    return candidate_allowed, estimate_allowed, decline_code


# Traditional-Chinese labels for complexity flags that can still appear in a
# decline reason (the ones NOT removed from app.yaml's forbidden list on
# 2026-09-16 — outer_join/group_by_aggregate/distinct are gone from there,
# so they never reach this dict via a real decline_code anymore, but a label
# is kept for any of them in case a future config re-adds one).
_COMPLEXITY_FLAG_LABELS: dict[str, str] = {
    "window_function": "視窗函數（Analytic Function）",
    "connect_by": "CONNECT BY 階層查詢",
    "set_operation": "UNION／MINUS／INTERSECT 等集合運算",
    "rownum": "ROWNUM",
    "correlated_subquery": "複雜的相關子查詢（Correlated Subquery）",
    "outer_join": "OUTER JOIN",
    "group_by_aggregate": "GROUP BY／彙總函數",
    "distinct": "DISTINCT",
}

_DECLINE_REASON_TEXT: dict[str, str] = {
    "multi_statement": "本次送出包含多段 SQL，系統設定為不自動改寫多段查詢，本次先提供改善方向，不自動產生建議寫法。",
    "not_select": "此語句不是 SELECT 查詢，系統設定僅對 SELECT 查詢提供建議寫法，本次先提供改善方向，不自動產生建議寫法。",
    "parse_failed": "此 SQL 結構較複雜，系統無法完整解析，本次先提供改善方向，不自動產生建議寫法。",
}


def _decline_reason_text(decline_code: str | None) -> str:
    """Reviewer-facing Chinese explanation for why candidate_allowed is
    False, specific to `decline_code` instead of always the same fixed
    sentence. Falls back to the original fixed PRD §25.4 copy for any
    unrecognized/None code so this can never produce an empty or malformed
    reason."""
    if decline_code is None:
        return _NO_REWRITE_REASON
    if decline_code.startswith("complexity:"):
        flag = decline_code.split(":", 1)[1]
        label = _COMPLEXITY_FLAG_LABELS.get(flag, flag)
        return f"此 SQL 含{label}，系統設定為不自動改寫，本次先提供改善方向，不自動產生建議寫法。"
    return _DECLINE_REASON_TEXT.get(decline_code, _NO_REWRITE_REASON)


def _pick_representative(
    statements: list[ParsedStatement], findings: list[Finding]
) -> ParsedStatement | None:
    """Choose which statement's SQL becomes `sanitized_sql`/`statement_type`
    for multi-statement input (PRD §20's payload only carries one
    representative statement). We rank each statement by (a) whether any of
    its findings is BLOCK-severity, then (b) how many findings it has —
    i.e. "worst, then most findings" — so the model's explanation focuses on
    the segment a reviewer most needs help with. Global-scoped findings
    (COST, statement_index == GLOBAL_STATEMENT_INDEX) aren't tied to any one
    statement and are excluded from this ranking. Ties keep the earliest
    statement: `max()` only replaces the current best on a strictly greater
    key, and `statements` is already in ascending index order.
    """
    if not statements:
        return None
    if len(statements) == 1:
        return statements[0]

    counts: Counter[int] = Counter()
    blocked: set[int] = set()
    for f in findings:
        if f.statement_index == GLOBAL_STATEMENT_INDEX:
            continue
        counts[f.statement_index] += 1
        if f.status == "BLOCK":
            blocked.add(f.statement_index)

    def _rank(stmt: ParsedStatement) -> tuple[bool, int]:
        return (stmt.index in blocked, counts.get(stmt.index, 0))

    return max(statements, key=_rank)


def _build_payload(
    *,
    statement_type: str,
    sanitized_sql: str,
    cost: int,
    compliance_status: str,
    findings: list[Finding],
    candidate_allowed: bool,
    estimate_improvement_allowed: bool,
    literal_hints: dict[str, dict[str, Any]] | None = None,
    where_evidence: dict[str, str] | None = None,
    structure_flags: list[str] | None = None,
) -> dict[str, Any]:
    """PRD §20's field set plus two additive, non-sensitive fields (2026-09-
    16): `literal_hints` (placeholder -> shape/length/wildcard, never the
    actual value — lets the model reason about e.g. "this is a trailing-
    wildcard LIKE pattern" without seeing real text) and `where_evidence`
    (why R002 did not BLOCK a SELECT with no top-level WHERE, when
    applicable). Never raw literals, never model/Docker/DB connection info.
    """
    important_table_notices = list(
        dict.fromkeys(f.table for f in findings if f.rule_id == "R007" and f.table)
    )
    payload: dict[str, Any] = {
        "statement_type": statement_type,
        "sanitized_sql": sanitized_sql,
        "input_cost": cost,
        "compliance": compliance_status,
        "findings": [{"rule_id": f.rule_id, "level": f.status, "fact": f.fact} for f in findings],
        "important_table_notices": important_table_notices,
        "candidate_allowed": candidate_allowed,
        "estimate_improvement_allowed": estimate_improvement_allowed,
        "literal_hints": literal_hints or {},
        # Deterministic structural facts from sql_parser (2026-09-17): the
        # model kept declaring a NOT IN subquery "already good" because
        # nothing told it the pattern was there; findings only carry rule
        # hits, and complexity flags were never in the payload.
        "structure_flags": sorted(structure_flags or []),
    }
    if where_evidence is not None:
        payload["where_evidence"] = where_evidence
    return payload


# ---------------------------------------------------------------------------
# Output guardrails (PRD §17.4, §22, §23, §56) — post-process, never trust
# the model's own restraint even though the prompt also asks for all of this.
# ---------------------------------------------------------------------------
def _apply_vocabulary(text: str, replacements: dict[str, str]) -> str:
    """PRD §22 terminology replacement for AI prose fields only. Iterates
    `replacements` in the order app.yaml defines them — that file
    deliberately lists longer/more specific phrases (e.g. "優化SQL") before
    their shorter substrings (e.g. "優化") so the specific mapping wins;
    reordering this iteration (e.g. sorting keys) would break that."""
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _contains_forbidden(text: str, forbidden: list[str]) -> bool:
    if not text:
        return False
    return any(phrase in text for phrase in forbidden)


def _filter_advice(
    advice: list[AdviceItem],
    forbidden: list[str],
    vocab: dict[str, str],
    reverse_map: dict[str, str] | None = None,
) -> list[AdviceItem]:
    kept: list[AdviceItem] = []
    dropped = 0
    for item in advice[:3]:  # RESPONSE_SCHEMA already caps at 3; defensive
        title = _apply_vocabulary(item.title, vocab)
        explanation = _apply_vocabulary(item.explanation, vocab)
        if _contains_forbidden(title, forbidden) or _contains_forbidden(explanation, forbidden):
            dropped += 1
            continue
        # 2026-09-17: code fragments are shown to the reviewer who owns the
        # data, so restore masked literals there too (previously `:STR_002`
        # leaked through into the advice card — confirmed in a production
        # printout). Prose fields are never un-masked.
        example = unmask_sql(item.example, reverse_map or {}) if item.example else None
        before = unmask_sql(item.before, reverse_map or {}) if item.before else None
        if before and not example:
            # A "before" with nothing to compare against is useless to the
            # diff view and misleading in the card — drop it.
            before = None
        kept.append(
            AdviceItem(title=title, explanation=explanation, example=example, impact=item.impact, before=before)
        )
    if dropped:
        # PRD: log a counter on a forbidden-phrase hit, never the content
        # that triggered it. INFO (not debug) so this decision is visible in
        # production logs without needing debug-level logging enabled — see
        # tasks/lessons.md "決策 log 用 debug 等於沒有 log".
        logger.info("ai_service: dropped %d advice item(s) on forbidden-phrase match", dropped)
    return kept


def _clamp_round_pct(value: int | None, estimate_allowed: bool) -> int | None:
    """Clamp to [0, 100], round to the nearest 5, and force null whenever
    there is nothing to estimate — never let the raw model value through
    unmodified."""
    if not estimate_allowed or value is None:
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    v = max(0, min(100, v))
    return round(v / 5) * 5


# PRD §25.4's exact fixed copy for "declined to auto-rewrite" — used
# whenever the server (not the model) is the one deciding no rewrite will be
# shown.
_NO_REWRITE_REASON = "為避免改變原本查詢內容，本次先提供改善方向，不自動產生建議寫法。"


_STRUCTURE_CLASS_FLAGS = frozenset(
    {
        "not_in_subquery",
        "correlated_subquery",
        "set_operation",
        "distinct",
        "distinct_or_union",
        "outer_join",
        "cartesian_join",
        "window_function",
        "connect_by",
        "group_by_aggregate",
    }
)


def _revalidate_suggested_sql(
    sql_text: str,
    representative: ParsedStatement,
    original_notice_count: int,
    cost: int,
    rules_config: dict[str, Any],
    important_tables_config: dict[str, Any],
) -> tuple[bool, str | None]:
    """Re-parse and re-run the deterministic rule engine on the model's
    proposed rewrite before it is ever shown to a user. The model is never
    trusted for anything that could change query semantics or introduce a
    new compliance problem — this check is the enforcement of that,
    independent of whatever the model's own `reason`/`available` fields
    claim. Returns (ok, rejection_reason).

    2026-09-16: strengthened alongside relaxing app.yaml's
    candidate_forbidden_complexity_flags (LEFT JOIN / GROUP BY / DISTINCT
    are no longer blanket-forbidden) — the table check is now *equality*
    (not subset: a rewrite that quietly drops a table changes which rows can
    match, e.g. turning an INNER JOIN's implicit filtering into a LEFT JOIN
    by omission), and `structural_signature` compares JOIN kinds *and order*,
    GROUP BY/HAVING/DISTINCT/aggregate functions, ORDER BY, and column count
    — replacing the old column-count-only check, which was the only
    structural safeguard when these flags were simply banned outright.
    """
    try:
        normalized_original = " ".join(representative.raw_sql.split())
        normalized_suggested = " ".join(sql_text.split())
        if normalized_suggested == normalized_original:
            return False, "建議寫法與原始 SQL 相同"

        parsed = parse_sql_text(sql_text)
        if len(parsed.statements) != 1:
            return False, "建議寫法不是單一語句"
        stmt = parsed.statements[0]
        if stmt.parse_status != "ok":
            return False, "建議寫法無法解析"
        if stmt.statement_type != representative.statement_type:
            return False, "建議寫法語句類型與原始不同"
        if stmt.tables != representative.tables:
            return False, "建議寫法引用的資料表與原始查詢不同"
        if stmt.hint_evidence is not None:
            return False, "建議寫法不得包含 Hint"
        if "rownum" in stmt.complexity_flags:
            return False, "建議寫法不得包含 ROWNUM"
        # 2026-09-17: structure-class flags must be identical. Catches
        # NOT IN -> NOT EXISTS (not_in_subquery disappears, correlated_subquery
        # appears; results differ when the subquery column has NULLs), added/
        # removed subqueries or set operations, and DISTINCT/outer-join changes
        # — none of which the column/join/group checks below can see.
        orig_struct = representative.complexity_flags & _STRUCTURE_CLASS_FLAGS
        new_struct = stmt.complexity_flags & _STRUCTURE_CLASS_FLAGS
        if orig_struct != new_struct:
            return False, "建議寫法改變了查詢結構（子查詢／集合運算／DISTINCT／JOIN 型態）"

        if representative.tree is None or stmt.tree is None:
            return False, "建議寫法結構複核失敗，無法比對"

        orig_sig = structural_signature(representative.tree)
        new_sig = structural_signature(stmt.tree)
        if not orig_sig or not new_sig:
            # Empty means "could not compute" (e.g. non-SELECT branch shape),
            # never "structurally equal" — reject conservatively.
            return False, "建議寫法結構複核失敗，無法比對"
        if orig_sig["join_sides"] != new_sig["join_sides"]:
            return False, "建議寫法的 JOIN 種類或順序與原始不同"
        if orig_sig["group_by_count"] != new_sig["group_by_count"] or orig_sig["having"] != new_sig["having"]:
            return False, "建議寫法的 GROUP BY 與原始不同"
        if orig_sig["distinct"] != new_sig["distinct"]:
            return False, "建議寫法的 DISTINCT 與原始不同"
        if orig_sig["agg_funcs"] != new_sig["agg_funcs"]:
            return False, "建議寫法使用的彙總函數與原始不同"
        if orig_sig["order_by"] != new_sig["order_by"]:
            return False, "建議寫法的 ORDER BY 與原始不同"
        if orig_sig["select_count"] != new_sig["select_count"]:
            return False, "建議寫法的查詢欄位數與原始不同"

        _compliance, _rows, new_findings = rule_engine.evaluate(
            parsed, cost, rules_config, important_tables_config
        )
        if any(f.status == "BLOCK" for f in new_findings):
            return False, "建議寫法本身會觸發不符合中心規範項目"
        new_notice_count = sum(1 for f in new_findings if f.status == "NOTICE")
        if new_notice_count > original_notice_count:
            return False, "建議寫法的提醒項目多於原始 SQL"

        return True, None
    except Exception as exc:
        # PRD §50.4: log the exception *type* only, never str(exc)/a
        # traceback — sqlglot's ParseError.__str__() embeds a raw snippet of
        # the surrounding SQL (confirmed), and this re-validation path runs
        # on the model's *unmasked* rewrite, i.e. real literal values.
        logger.error("ai_service: suggested SQL re-validation raised unexpectedly: %s", type(exc).__name__)
        return False, "建議寫法安全性檢查失敗"


def _finalize_suggested_sql(
    raw: _RawSuggestedSql,
    reverse_map: dict[str, str],
    candidate_allowed: bool,
    decline_code: str | None,
    forbidden: list[str],
    vocab: dict[str, str],
    representative: ParsedStatement | None,
    original_notice_count: int,
    cost: int,
    rules_config: dict[str, Any],
    important_tables_config: dict[str, Any],
) -> SuggestedSql:
    reason = _apply_vocabulary(raw.reason, vocab)
    # Server-side override (never trust the model on this): candidate_allowed
    # is computed deterministically and wins regardless of what the model
    # claims.
    available = bool(raw.available) and candidate_allowed

    # Outcome classification (see schemas.RewriteOutcome). The model only
    # chooses between not_needed / advice_only; gated / rejected / provided
    # are decided here from facts it cannot influence.
    outcome: str = "advice_only"
    if raw.rewrite_outcome == "not_needed" and not raw.available:
        outcome = "not_needed"

    if not candidate_allowed:
        outcome = "gated"
        if raw.available:
            # The model's own `reason` was almost certainly written to
            # justify *providing* a rewrite (available=true), so surfacing it
            # verbatim once we flip available to false would read as
            # self-contradictory. Replace it with a reason specific to *why*
            # candidate_allowed is false (decline_code).
            reason = _decline_reason_text(decline_code)

    if _contains_forbidden(reason, forbidden):
        logger.info("ai_service: suggested_sql.reason discarded on forbidden-phrase match")
        available = False
        reason = "建議寫法說明暫不提供。"
        if outcome == "not_needed":
            outcome = "advice_only"

    sql: str | None = None
    if available and raw.sql:
        unmasked = unmask_sql(raw.sql, reverse_map)
        if unmasked and representative is not None:
            ok, rejection = _revalidate_suggested_sql(
                unmasked, representative, original_notice_count, cost, rules_config, important_tables_config
            )
            if ok:
                sql = unmasked
                outcome = "provided"
                logger.info("ai_service: revalidation ok")
            else:
                # Rejection reasons are all fixed, structure-only Chinese
                # phrases (see `_revalidate_suggested_sql`) — never contain
                # SQL text or literal values — so both surfacing this to the
                # reviewer and logging it at INFO are safe.
                logger.info("ai_service: revalidation rejected: %s", rejection)
                available = False
                outcome = "rejected"
                reason = (
                    f"AI 提出的建議寫法未通過系統安全複核（{rejection}），"
                    "為避免改變原本查詢內容，本次不顯示建議寫法。"
                )
        else:
            # No representative statement to validate against, or nothing
            # left after unmasking — conservative: decline rather than show
            # an unvalidated rewrite.
            available = False
            outcome = "rejected"
            reason = _NO_REWRITE_REASON
    elif available and not raw.sql:
        # Model said available=true but sent no SQL — nothing to show.
        available = False
        outcome = "advice_only"

    logger.info("ai_service: rewrite outcome=%s", outcome)
    return SuggestedSql(available=available, reason=reason, sql=sql, outcome=outcome)


def _finalize(
    raw: _AiRawResponse,
    reverse_map: dict[str, str],
    candidate_allowed: bool,
    estimate_allowed: bool,
    decline_code: str | None,
    ai_guard_cfg: dict[str, Any],
    representative: ParsedStatement | None,
    original_notice_count: int,
    cost: int,
    rules_config: dict[str, Any],
    important_tables_config: dict[str, Any],
) -> AiResult:
    forbidden = ai_guard_cfg.get("forbidden_phrases", [])
    vocab = ai_guard_cfg.get("vocabulary_replacements", {})

    summary: str | None = _apply_vocabulary(raw.summary, vocab)
    if _contains_forbidden(summary, forbidden):
        logger.info("ai_service: summary discarded on forbidden-phrase match")
        summary = None

    advice = _filter_advice(raw.advice, forbidden, vocab, reverse_map)
    suggested_sql = _finalize_suggested_sql(
        raw.suggested_sql,
        reverse_map,
        candidate_allowed,
        decline_code,
        forbidden,
        vocab,
        representative,
        original_notice_count,
        cost,
        rules_config,
        important_tables_config,
    )
    pct = _clamp_round_pct(raw.estimated_improvement_pct, estimate_allowed)

    logger.info(
        "ai_service: model available=%s advice=%d pct=%s",
        suggested_sql.available,
        len(advice),
        pct,
    )

    # Still "ok" even if advice ended up empty after filtering — the model
    # did respond and validate; there is no separate "degraded but ok" state.
    return AiResult(status="ok", summary=summary, advice=advice, suggested_sql=suggested_sql, estimated_improvement_pct=pct)


def _unavailable() -> AiResult:
    return AiResult(status="unavailable", message=DEGRADE_MESSAGE)


# ---------------------------------------------------------------------------
# Ollama network call
# ---------------------------------------------------------------------------
def _chat_request_body(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    user_content = "<SQL_DATA>\n" + json.dumps(payload, ensure_ascii=False) + "\n</SQL_DATA>"
    return {
        "model": settings.ollama.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "format": RESPONSE_SCHEMA,
        "stream": False,
        # Gemma4 thinks by default; for a schema-constrained JSON reply the
        # thinking only burns num_predict (confirmed: 3072 tokens of thinking,
        # empty content, done_reason=length -> "unavailable"). See app.yaml.
        "think": settings.ollama.think,
        "options": {
            "temperature": settings.ollama.temperature,
            "num_ctx": settings.ollama.num_ctx,
            # Config-driven rather than a hardcoded 1024: OllamaSettings
            # already carries num_predict (default 1024, same value) for
            # exactly this purpose.
            "num_predict": settings.ollama.num_predict,
        },
        "keep_alive": settings.ollama.keep_alive,
    }


class _TruncatedResponseError(Exception):
    """Raised when Ollama reports `done_reason == "length"` — the model hit
    `num_predict` before finishing its JSON output. Distinguished from a
    generic JSON-decode failure so `_request_ai` can degrade immediately
    with a specific log line instead of silently retrying with the exact
    same parameters (which would very likely truncate the same way again —
    the fix for a truncation is raising `ollama.num_predict` in app.yaml,
    not retrying)."""

    def __init__(self, eval_count: int | None):
        super().__init__("truncated")
        self.eval_count = eval_count


async def _one_attempt(client: httpx.AsyncClient, settings: Settings, payload: dict[str, Any]) -> _AiRawResponse:
    """Exactly one POST + parse + validate. Raises on any problem; the
    caller decides retry-once (invalid JSON/shape) vs immediate-fail
    (connection/timeout/HTTP-status/truncation) based on the exception type.
    """
    resp = await client.post(
        f"{settings.ollama.base_url}/api/chat",
        json=_chat_request_body(settings, payload),
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("done_reason") == "length":
        thinking_chars = len((data.get("message") or {}).get("thinking") or "")
        if thinking_chars:
            logger.info(
                "ai_service: truncated while thinking (thinking_chars=%d) — model thinking mode is on; "
                "set ollama.think_default=false / OLLAMA_THINK=false",
                thinking_chars,
            )
        raise _TruncatedResponseError(data.get("eval_count"))
    content = data["message"]["content"]  # Ollama's documented chat shape
    raw = json.loads(content)
    parsed = _AiRawResponse.model_validate(raw)
    # INFO, never DEBUG: this is the only place the actual model latency and
    # token counts are observable, and none of these fields can ever embed
    # SQL text or prompt content.
    logger.info(
        "ai_service: ollama response done_reason=%s eval_count=%s prompt_eval_count=%s total_duration_ms=%s thinking_chars=%d",
        data.get("done_reason"),
        data.get("eval_count"),
        data.get("prompt_eval_count"),
        (data.get("total_duration") or 0) // 1_000_000,
        len(data["message"].get("thinking") or ""),
    )
    return parsed


async def _request_ai(settings: Settings, payload: dict[str, Any]) -> _AiRawResponse | None:
    """Returns a validated raw response, or None on any failure. Connection
    and timeout errors fail immediately (never retried — retrying would just
    double the wall-clock wait for no benefit). A truncated response
    (`done_reason=length`) also fails immediately, for the same reason —
    see `_TruncatedResponseError`. Invalid JSON / schema validation failures
    are retried exactly once."""
    try:
        await asyncio.wait_for(_OLLAMA_SEMAPHORE.acquire(), timeout=settings.ollama.timeout_seconds)
    except TimeoutError:
        return None

    try:
        async with httpx.AsyncClient(timeout=settings.ollama.timeout_seconds) as client:
            try:
                return await _one_attempt(client, settings, payload)
            except (httpx.RequestError, httpx.HTTPStatusError):
                return None
            except _TruncatedResponseError as exc:
                logger.info(
                    "ai_service: model output truncated (done_reason=length, eval_count=%s) — "
                    "degrading without retry; consider raising ollama.num_predict",
                    exc.eval_count,
                )
                return None
            except (json.JSONDecodeError, ValidationError, KeyError, TypeError):
                pass  # retry exactly once below

            try:
                return await _one_attempt(client, settings, payload)
            except (httpx.RequestError, httpx.HTTPStatusError):
                return None
            except _TruncatedResponseError as exc:
                logger.info(
                    "ai_service: model output truncated again on retry (done_reason=length, eval_count=%s) — degrading",
                    exc.eval_count,
                )
                return None
            except (json.JSONDecodeError, ValidationError, KeyError, TypeError):
                return None
    finally:
        _OLLAMA_SEMAPHORE.release()


# ---------------------------------------------------------------------------
# Public API (api.py calls these two)
# ---------------------------------------------------------------------------
async def get_ai_result(
    *,
    sql_text: str,
    cost: int,
    compliance_status: str,
    findings: list[Finding],
    statements: list[ParsedStatement],
    settings: Settings,
) -> AiResult:
    """Never raises — any failure anywhere in this path (Ollama down,
    invalid response, or an unexpected bug in this module itself) degrades
    to the PRD-mandated "unavailable" result rather than propagating."""
    try:
        candidate_allowed, estimate_allowed, decline_code = _compute_gates(statements, findings, settings.ai_gate)

        representative = _pick_representative(statements, findings)
        if representative is not None:
            statement_type = representative.statement_type
            mask_result = mask_sql(representative.raw_sql, settings.masking.keep_short_ascii_literal_max_len)
        else:
            statement_type = "UNKNOWN"
            mask_result = mask_sql(sql_text, settings.masking.keep_short_ascii_literal_max_len)

        where_evidence = None
        if representative is not None and representative.restriction_kind is not None:
            where_evidence = {
                "kind": representative.restriction_kind,
                "detail": representative.restriction_detail,
            }

        logger.info(
            "ai_service: gate candidate=%s estimate=%s decline_code=%s stmt_type=%s flags=%s where_kind=%s",
            candidate_allowed,
            estimate_allowed,
            decline_code,
            statement_type,
            sorted(representative.complexity_flags) if representative else [],
            representative.restriction_kind if representative else None,
        )

        payload = _build_payload(
            statement_type=statement_type,
            sanitized_sql=mask_result.masked_sql,
            cost=cost,
            compliance_status=compliance_status,
            findings=findings,
            candidate_allowed=candidate_allowed,
            estimate_improvement_allowed=estimate_allowed,
            literal_hints=mask_result.literal_hints,
            where_evidence=where_evidence,
            structure_flags=sorted(representative.complexity_flags) if representative else [],
        )

        raw = await _request_ai(settings, payload)
        if raw is None:
            return _unavailable()

        original_notice_count = 0
        if representative is not None:
            original_notice_count = sum(
                1 for f in findings if f.status == "NOTICE" and f.statement_index == representative.index
            )

        return _finalize(
            raw,
            mask_result.reverse_map,
            candidate_allowed,
            estimate_allowed,
            decline_code,
            settings.ai_guard,
            representative,
            original_notice_count,
            cost,
            settings.rules_config,
            settings.important_tables_config,
        )
    except Exception as exc:
        # PRD §50.4: exception type only, never a message/traceback that
        # could embed SQL text (see _revalidate_suggested_sql's comment).
        logger.error(
            "ai_service.get_ai_result: unexpected failure, degrading to unavailable: %s", type(exc).__name__
        )
        return _unavailable()


async def check_ollama_available(settings: Settings) -> bool:
    """Backs /api/health. Must stay fast and never raise: GET /api/tags,
    true iff HTTP 200 and settings.ollama.model appears in models[].name."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama.base_url}/api/tags")
        if resp.status_code != 200:
            return False
        data = resp.json()
        names = {m.get("name") for m in data.get("models", [])}
        return settings.ollama.model in names
    except Exception:
        return False
