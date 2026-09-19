"""AI advisory service (PRD §17.4, §20, §22, §23, §25, §46, §47, §56):
wraps a selectable LLM provider behind a small, deterministic pre/post-
processing pipeline. Vendor HTTP details live in services/llm_provider.py.

Hard boundaries this module exists to enforce (PRD §13.1, §56 — repeated
here because every function below exists to defend one of these):

- The AI never decides compliance, never decides the improvement score,
  never invents Execution Plan / index / full-table-scan facts, and never
  fabricates a post-improvement Oracle COST. It only explains, advises, and
  optionally proposes one rewrite (which the server re-validates).
- The improvement-potential level is derived server-side from verified
  evidence only (`improvement_potential`): the model's own impact rating is
  reference material for the advice card and can never raise the level.
- The AI is never a single point of failure: every failure mode (connection
  refused, timeout, invalid JSON even after one retry, or any unexpected
  bug in this module) degrades to `AiResult(status="unavailable", ...)`
  with the PRD-mandated frontend message — this module's public functions
  never raise.
- `candidate_allowed` is computed here, deterministically, from
  rule_engine/sql_parser facts and `app.yaml`'s `ai_gate` config — never
  from anything the model says. Even if the model ignores its instructions
  and returns `suggested_sql.available=true` while `candidate_allowed` is
  false, the server-side override in `_finalize_*` forces it back to false
  before it ever reaches the API response.
- Real literal values (string/date/large-numeric) never reach the model —
  `masking.mask_sql()` runs on the representative statement's SQL text
  before it is ever placed in the prompt, regardless of whether a candidate
  rewrite will be produced (PRD: sanitized_sql is used for explanation too).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlglot import exp, parse_one

from app.schemas import AdviceItem, AiResult, Finding, SuggestedSql
from app.services import context_adapter, llm_provider, pattern_selector, rewrite_rules, rule_engine
from app.services.masking import mask_sql, scrub_invented_placeholders, unmask_sql
from app.services.rule_engine import GLOBAL_STATEMENT_INDEX
from app.services.sql_parser import ParsedStatement, parse_sql_text, structural_signature
from app.settings import PROMPTS_DIR, Settings

logger = logging.getLogger(__name__)

# PRD-mandated exact frontend copy for any AI failure path (§56).
DEGRADE_MESSAGE = "智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。"

_VERIFIED = {"verified", "corrected"}

# 2026-09-17: rule ids whose findings are about the SQL *writing* itself
# (they describe a concrete, checkable statement pattern). R007 (重要資料表)
# is deliberately NOT one of them: it is a governance reminder about the data
# being touched, not evidence about how the SQL is written.
_WRITE_STYLE_RULE_IDS = frozenset({"R004", "R005", "R006"})

# Last provider call's diagnostics only (latency + token counts), for the
# golden runner. Deliberately contains no prompt, SQL, API key or model text.
# Compatibility keys (num_ctx/eval_count/prompt_eval_count) are kept so older
# evidence tooling still works when the active provider is Ollama.
LAST_CALL_STATS: dict[str, Any] = {}


def improvement_potential(result: AiResult, findings: list[Finding]) -> tuple[str | None, list[str]]:
    """2026-09-17 user decision (tightened by the round-1 third-party review):
    the level is derived ONLY from facts the server can observe for itself.
    The model's own `impact` rating is a self-assessment — it has no Oracle
    execution plan, no real index, no statistics and no cardinality — so it
    is shown on the advice card for reference but can never raise (or lower)
    this level. The old percentage was never measured, and the old "any
    NOTICE => medium" rule wrongly promoted pure governance reminders.

      high          — two or more server-verified improvement evidences (a
                      full validated rewrite counts as one of them);
      medium        — exactly one server-verified improvement evidence;
      low           — a BLOCK finding, concrete SQL-writing findings
                      (R004/R005/R006) or advisory prose, with no verified
                      rewrite to back it. A BLOCK is deterministic
                      non-compliance and is already shown by the 中心規範
                      verdict and the 改善優先指數; on its own it is *not*
                      proof that an improved SQL writing exists, so it must
                      not promote the potential to high;
      "notice_only" — only governance reminders (e.g. R007 重要資料表): worth
                      a human look, but no concrete SQL-writing improvement
                      point was confirmed. The UI must NOT render this as
                      「目前寫法良好」;
      None          — nothing was found at all (UI says 「目前未發現需要調整的地方」).

    A "server-verified improvement evidence" is one of:
      * an advice fragment whose before→example change the system re-validated
        as result-preserving (`verification` is verified/corrected);
      * a full suggested rewrite that passed the same re-validation
        (`suggested_sql.outcome == "provided"`).
    Returns (level, basis lines) so the UI can show what it was derived from.
    """
    if result.status != "ok":
        return None, []

    blocks = sum(1 for f in findings if f.status == "BLOCK")
    notices = [f for f in findings if f.status == "NOTICE"]
    write_style_notices = [f for f in notices if f.rule_id in _WRITE_STYLE_RULE_IDS]
    governance_notices = [f for f in notices if f.rule_id not in _WRITE_STYLE_RULE_IDS]
    provided = bool(result.suggested_sql and result.suggested_sql.outcome == "provided")
    verified_advice = [a for a in result.advice if a.verification in _VERIFIED]
    evidence_count = len(verified_advice) + (1 if provided else 0)

    basis: list[str] = []
    if blocks or notices:
        parts = []
        if blocks:
            parts.append(f"{blocks} 項不符合")
        if notices:
            parts.append(f"{len(notices)} 項提醒")
        basis.append("規則檢核：" + "、".join(parts))
    if provided:
        basis.append("已提供整段建議寫法，系統已確認查詢結果不變")
    if verified_advice:
        basis.append(f"系統已驗證 {len(verified_advice)} 項建議片段可保留原查詢結果")
    # 2026-09-17 user request: the per-advice impact/verification breakdown
    # is NOT listed here (the advice cards already carry it).

    # Order matters: the potential never exceeds what the *server* verified.
    # A BLOCK (or any unverified advice) can only ever justify "low": it stays
    # visible through the compliance verdict / 改善優先指數 instead.
    if evidence_count >= 2:
        return "high", basis
    if evidence_count == 1:
        return "medium", basis
    if blocks or write_style_notices or result.advice:
        return "low", basis
    if governance_notices:
        return "notice_only", basis
    return None, basis


_PROMPT_PATH = PROMPTS_DIR / "sql_review_zh_tw.txt"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

# Keep one in-flight model request per SQLCheck process. This matches the
# formal-host Ollama constraint and also prevents a Mac dev session from
# accidentally fanning out paid Gemini requests.
_LLM_SEMAPHORE = asyncio.Semaphore(1)

# Provider-neutral JSON Schema. Ollama receives it as `format`; Gemini
# receives it as generationConfig.responseJsonSchema.
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


# ---------------------------------------------------------------------------
# Deterministic gating (PRD §17.4, §25) — never influenced by the model.
# ---------------------------------------------------------------------------
def _compute_gates(
    statements: list[ParsedStatement],
    ai_gate_cfg: dict[str, Any],
    *,
    sql_tokens: int = 0,
    num_predict: int = 0,
) -> tuple[bool, str | None]:
    """candidate_allowed: exactly one statement, SELECT, parsed ok, and none
    of its complexity_flags intersect the configured forbidden set.
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
        elif num_predict > 0 and _rewrite_would_not_fit(sql_tokens, num_predict, ai_gate_cfg):
            # 2026-09-17 production DOCX: a ~6,000-char SQL cannot be
            # rewritten inside num_predict=3072 tokens. Asking the model to
            # try anyway made it overrun the output limit, which cut the JSON
            # mid-way and threw the summary/advice away with it. Length is a
            # deterministic fact, so it is a gate, not a model decision.
            decline_code = "too_long_for_rewrite"

    candidate_allowed = decline_code is None
    return candidate_allowed, decline_code


def _rewrite_would_not_fit(sql_tokens: int, num_predict: int, ai_gate_cfg: dict[str, Any]) -> bool:
    """A full rewrite echoes roughly the whole SQL (× `rewrite_token_ratio`)
    on top of the summary + advice the reply always carries
    (`rewrite_reply_overhead_tokens`). Both knobs live in app.yaml `ai_gate`."""
    ratio = float(ai_gate_cfg.get("rewrite_token_ratio", 1.2))
    overhead = int(ai_gate_cfg.get("rewrite_reply_overhead_tokens", 900))
    return sql_tokens * ratio + overhead > num_predict


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
    # 2026-09-17 wording: say what the reviewer WILL get (per-segment
    # suggestions right below), not only what they will not — the old
    # "不自動產生建議寫法" read as if nothing followed.
    "too_long_for_rewrite": "這份 SQL 較長，AI 不整段重寫，改為針對可改善的地方逐段提供建議寫法。",
    "rewrite_truncated": "AI 嘗試整段重寫時超出回覆長度上限，改為針對可改善的地方逐段提供建議寫法。",
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
    literal_hints: dict[str, dict[str, Any]] | None = None,
    where_evidence: dict[str, str] | None = None,
    structure_flags: list[str] | None = None,
    knowledge_context: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build the de-identified <SQL_DATA> object sent to Gemma.

    Besides the PRD core fields this includes non-sensitive deterministic
    metadata: literal shape hints, WHERE-restriction evidence, parser structure
    flags, and a bounded exact-only Pattern Catalog knowledge context. The
    knowledge context contains static catalog prose only — never raw literals,
    table names, model output, or DB/Docker connection information.
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
        "literal_hints": literal_hints or {},
        # Deterministic structural facts from sql_parser (2026-09-17): the
        # model kept declaring a NOT IN subquery "already good" because
        # nothing told it the pattern was there; findings only carry rule
        # hits, and complexity flags were never in the payload.
        "structure_flags": sorted(structure_flags or []),
        # Phase 3 compact context: exact Pattern Selector matches only. The
        # adapter already removes family signals / OUT_OF_SCOPE and enforces
        # top-N + character budgets. Values are static catalog guidance, never
        # user SQL or literals.
        "knowledge_context": knowledge_context or [],
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


_INTERNAL_PLACEHOLDER_RE = re.compile(r":(?P<kind>STR|NUM)_\d+", re.IGNORECASE)
_UNOBSERVABLE_DB_CLAIM_RE = re.compile(
    r"(?:Full\s+Table\s+Scan|全(?:資料)?表掃描|Execution\s+Plan|執行計畫(?:顯示)?|"
    r"排序特性|(?:使用|利用|採用|走|命中|失效|建立|新增|調整).{0,12}(?:索引|\bindex\b)|"
    r"(?:索引|\bindex\b).{0,12}(?:使用|利用|採用|走|命中|失效|建立|新增|調整)|無隱含型別轉換)",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])")
_TYPED_LITERAL_RE = re.compile(
    r"\b(?P<kind>DATE|TIMESTAMP)\s*(?P<literal>'(?:[^']|'')*')",
    re.IGNORECASE,
)


def _humanize_internal_placeholders(
    text: str,
    literal_hints: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Masking tokens are implementation details, never user vocabulary.

    Prose deliberately does *not* unmask to the original literal because
    summaries/reasons may be printed or archived. SQL code fields keep using
    the existing reversible mask/unmask path.
    """

    hints = literal_hints or {}

    def repl(match: re.Match[str]) -> str:
        placeholder = match.group(0)
        hint = hints.get(placeholder) or hints.get(placeholder.upper()) or {}
        oracle_type = str(hint.get("oracle_literal_type", "")).lower()
        if oracle_type == "date":
            return "原查詢中的日期值"
        if oracle_type == "timestamp":
            return "原查詢中的日期時間值"
        return "原查詢中的文字值" if match.group("kind").upper() == "STR" else "原查詢中的數值"

    return _INTERNAL_PLACEHOLDER_RE.sub(repl, text)


def _sanitize_unobservable_db_claims(text: str) -> str:
    """Remove sentences that claim database behavior SQLCheck cannot observe.

    SQLCheck has no Oracle plan/index/statistics metadata. Keeping useful
    neighboring sentences is better than dropping the whole advice item when
    Gemma adds one unsupported index/plan assertion.
    """
    if not text:
        return text
    pieces = [p for p in _SENTENCE_SPLIT_RE.split(text) if p]
    kept = [p for p in pieces if not _UNOBSERVABLE_DB_CLAIM_RE.search(p)]
    if kept:
        return "".join(kept).strip()
    return "這項建議是依 SQL 寫法本身提出，實際效能仍需於測試環境確認。"


def _sanitize_user_prose(
    text: str,
    vocab: dict[str, str],
    literal_hints: dict[str, dict[str, Any]] | None = None,
) -> str:
    text = _apply_vocabulary(text, vocab)
    text = _humanize_internal_placeholders(text, literal_hints)
    return _sanitize_unobservable_db_claims(text)


_ADVICE_ONLY_PROSE_GUARDS: tuple[tuple[str, re.Pattern[str], re.Pattern[str], str], ...] = (
    (
        "leading_wildcard_like",
        re.compile(r"\bLIKE\s+N?'[%_]", re.IGNORECASE),
        re.compile(r"\bLIKE\b|萬用字元|前置|比對(?:開頭|結尾)?", re.IGNORECASE),
        "目前使用前置萬用字元。若業務需求允許縮小比對範圍，可評估其他比對方式；調整前請先確認實際比對需求。",
    ),
    (
        "trunc_condition",
        re.compile(r"\bTRUNC\s*\(", re.IGNORECASE),
        re.compile(
            r"\bTRUNC\b|日期欄位|日期比對|日期範圍|時間成分|包含時間|大於|小於|>=|<=",
            re.IGNORECASE,
        ),
        "目前條件先用 TRUNC() 處理欄位再比對。若確認是日期欄位，可評估改用日期範圍；調整前請先確認欄位型態與比對值是否包含時間。",
    ),
    (
        "to_char_condition",
        re.compile(r"\bTO_CHAR\s*\(", re.IGNORECASE),
        re.compile(r"\bTO_CHAR\b|日期|年度|年份|範圍|大於|小於|>=|<=", re.IGNORECASE),
        "目前條件先用 TO_CHAR() 轉成文字再比對。可評估改用原欄位型態直接比對；調整前請先確認欄位型態與實際比對需求。",
    ),
    (
        "nvl_condition",
        re.compile(r"\bNVL\s*\(", re.IGNORECASE),
        re.compile(r"\bNVL\b|空值|NULL|IS\s+NULL|\bOR\b", re.IGNORECASE),
        "目前條件用 NVL() 處理空值。可評估改成分開判斷欄位值與空值；調整前請先確認欄位型態與原本的空值規則。",
    ),
    (
        "distinct_removal",
        re.compile(r"\bDISTINCT\b", re.IGNORECASE),
        re.compile(r"\bDISTINCT\b|去重|重複", re.IGNORECASE),
        "移除 DISTINCT 前，請先確認 JOIN 後是否仍可能出現重複資料；如果會，就不要移除。",
    ),
)

_COPYABLE_SQL_IN_PROSE_RE = re.compile(
    r"(?:\b[A-Z_][A-Z0-9_$#]*\.)?[A-Z_][A-Z0-9_$#]*\s*"
    r"(?:=|<>|!=|>=|<=|>|<|\bLIKE\b|\bIN\s*\(|\bIS\s+(?:NOT\s+)?NULL\b)",
    re.IGNORECASE,
)
_DATE_LITERAL_IN_PROSE_RE = re.compile(r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")
_CROSS_COLUMN_OR_ADVICE_RE = re.compile(
    r"\bOR\b|跨欄位|不同欄位|拆分|拆開|分支|UNION|重複列|重複資料|條件是否",
    re.IGNORECASE,
)
_NO_MAIN_WHERE_INVENTED_FIELD_RE = re.compile(
    r"(?:增加|新增|加入|補上|限制條件)[^。；，,]{0,30}"
    r"(?:日期|狀態|年度|年份|類別|date|status|year|category)|"
    r"(?:日期|狀態|年度|年份|類別|date|status|year|category)[^。；，,]{0,30}"
    r"(?:增加|新增|加入|補上|限制條件)",
    re.IGNORECASE,
)

_CROSS_COLUMN_OR_SAFE_COPY = (
    "這段 OR 連接不同欄位。若要拆開查詢，請先確認兩個條件是否可能同時成立，以及重複資料要如何處理；"
    "未確認前不建議改寫。"
)
_NO_MAIN_WHERE_SAFE_COPY = "建議確認是否需要增加限制條件，以縮小查詢範圍。"


def _source_has_no_main_where(source_sql: str) -> bool:
    """Detect the parsed main SELECT without treating JOIN ON as WHERE."""
    try:
        parsed = parse_sql_text(source_sql)
        statement = next((s for s in parsed.statements if s.parse_status == "ok"), None)
        return bool(
            statement
            and statement.statement_type == "SELECT"
            and statement.where_applicable
            and statement.has_where is False
        )
    except Exception:
        return False


def _guard_unverified_advice_prose(source_sql: str, title: str, explanation: str) -> tuple[str, str | None]:
    """Keep ADVICE_ONLY content useful without leaking copy-paste SQL.

    Prompt rules are guidance; this function is enforcement. Known semantic
    traps get short server-owned wording. Any remaining unverified prose that
    still contains a copyable predicate or an invented date literal is
    replaced by a generic confirmation-first sentence.
    """
    if not explanation:
        return explanation, None

    combined = f"{title}\n{explanation}"
    if rewrite_rules.has_cross_column_or(source_sql) and _CROSS_COLUMN_OR_ADVICE_RE.search(combined):
        return _CROSS_COLUMN_OR_SAFE_COPY, "cross_column_or"

    if _source_has_no_main_where(source_sql) and _NO_MAIN_WHERE_INVENTED_FIELD_RE.search(combined):
        return _NO_MAIN_WHERE_SAFE_COPY, "no_main_where_invented_field"

    for guard_id, source_re, advice_re, safe_copy in _ADVICE_ONLY_PROSE_GUARDS:
        if source_re.search(source_sql) and advice_re.search(combined):
            return safe_copy, guard_id

    if _COPYABLE_SQL_IN_PROSE_RE.search(explanation) or _DATE_LITERAL_IN_PROSE_RE.search(explanation):
        return "這個改善方向可能改變查詢結果。請先確認業務條件後，再決定是否調整。", "generic_unverified_sql"

    return explanation, None


def _parse_sql_or_fragment(text: str) -> exp.Expression | None:
    if not text or not text.strip():
        return None
    stripped = text.strip().rstrip(";")

    # A leading WHERE/ON is a fragment wrapper, not a standalone Oracle
    # statement. sqlglot may still accept some such text into a partial AST,
    # which would silently hide its literals/columns from provenance checks.
    # Normalize the wrapper *before* trying a standalone parse.
    if re.match(r"^\s*(?:WHERE|ON)\b", stripped, flags=re.IGNORECASE):
        predicate = re.sub(r"^\s*(?:WHERE|ON)\b", "", stripped, flags=re.IGNORECASE).strip()
        if not predicate:
            return None
        try:
            return parse_one(f"SELECT NULL FROM DUAL WHERE {predicate}", read="oracle")
        except Exception:
            return None

    try:
        return parse_one(stripped, read="oracle")
    except Exception:
        # Bare predicate fragments (without WHERE/ON) get one conservative
        # wrapper so identifier/literal provenance can still be inspected.
        try:
            return parse_one(f"SELECT NULL FROM DUAL WHERE {stripped}", read="oracle")
        except Exception:
            return None


def _identifier_facts(text: str) -> tuple[set[tuple[str | None, str]], set[str], set[str]] | None:
    """Return (qualified columns, tables, aliases) for SQL or a predicate.

    The guard intentionally reasons only from identifiers actually visible in
    the original SQL. It never consults schema metadata.
    """
    tree = _parse_sql_or_fragment(text)
    if tree is None:
        return None

    columns: set[tuple[str | None, str]] = set()
    for col in tree.find_all(exp.Column):
        name = (col.name or "").upper()
        if not name:
            continue
        qualifier = (col.table or "").upper() or None
        columns.add((qualifier, name))

    tables: set[str] = set()
    aliases: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = (table.name or "").upper()
        if name and name != "DUAL":
            tables.add(name)
        alias = (table.alias or "").upper()
        if alias:
            aliases.add(alias)

    return columns, tables, aliases


def _introduces_unknown_identifiers(source_sql: str, example: str) -> bool:
    source = _identifier_facts(source_sql)
    proposed = _identifier_facts(example)
    if source is None or proposed is None:
        return True

    source_columns, source_tables, source_aliases = source
    proposed_columns, proposed_tables, _ = proposed
    if not proposed_tables.issubset(source_tables):
        return True

    source_names = {name for _, name in source_columns}
    for qualifier, name in proposed_columns:
        if qualifier is None:
            if name not in source_names:
                return True
            continue
        if (qualifier, name) in source_columns:
            continue
        # Allow qualification of an originally-unqualified column only when
        # the qualifier itself is an alias/table already present in source.
        if (None, name) in source_columns and (qualifier in source_aliases or qualifier in source_tables):
            continue
        return True
    return False


def _loses_typed_literal_wrapper(before: str | None, example: str) -> bool:
    if not before:
        return False
    for match in _TYPED_LITERAL_RE.finditer(before):
        kind = match.group("kind")
        literal = match.group("literal")
        if literal not in example:
            continue
        required = re.compile(rf"\b{re.escape(kind)}\s*{re.escape(literal)}", re.IGNORECASE)
        if required.search(example) is None:
            return True
    return False


def _literal_facts(text: str) -> tuple[set[str], set[str]] | None:
    """Return (string literal contents, numeric literal contents).

    This is a provenance check only; it does not try to infer datatypes.
    """
    tree = _parse_sql_or_fragment(text)
    if tree is None:
        return None
    strings: set[str] = set()
    numbers: set[str] = set()
    for literal in tree.find_all(exp.Literal):
        value = str(literal.this)
        if literal.is_string:
            strings.add(value)
        else:
            numbers.add(value)
    return strings, numbers


def _wildcard_core(value: str) -> str:
    return value.strip("%_")


def _introduces_unknown_literals(source_sql: str, example: str) -> bool:
    """Reject business constants invented by the model.

    Exact source literals are allowed. String examples may add/move LIKE
    wildcard characters around the same non-empty literal core so the
    deterministic SUBSTR→LIKE rule can work without authorizing new business
    values. Unverified LIKE-direction examples are removed later by
    _filter_advice and never reach the API.
    """
    source = _literal_facts(source_sql)
    proposed = _literal_facts(example)
    if source is None or proposed is None:
        return True
    source_strings, source_numbers = source
    proposed_strings, proposed_numbers = proposed

    source_cores = {_wildcard_core(v) for v in source_strings if _wildcard_core(v)}
    for value in proposed_strings:
        if value in source_strings:
            continue
        core = _wildcard_core(value)
        if core and core in source_cores:
            continue
        return True

    return not proposed_numbers.issubset(source_numbers)


def _advice_example_safety_issue(source_sql: str, before: str | None, example: str) -> str | None:
    # Production supplies the representative SQL. Existing unit-level
    # rewrite-evidence helpers may intentionally call _filter_advice without
    # a whole statement, so provenance enforcement is conditional here.
    if source_sql:
        if _introduces_unknown_identifiers(source_sql, example):
            return "unknown_identifier"
        if _introduces_unknown_literals(source_sql, example):
            return "unknown_literal"
    if _loses_typed_literal_wrapper(before, example):
        return "typed_literal"
    return None


def _advice_example_is_safe(source_sql: str, before: str | None, example: str) -> bool:
    return _advice_example_safety_issue(source_sql, before, example) is None


def _filter_advice(
    advice: list[AdviceItem],
    forbidden: list[str],
    vocab: dict[str, str],
    reverse_map: dict[str, str] | None = None,
    *,
    source_sql: str = "",
    literal_hints: dict[str, dict[str, Any]] | None = None,
) -> list[AdviceItem]:
    kept: list[AdviceItem] = []
    dropped = 0
    for item in advice[:3]:  # RESPONSE_SCHEMA already caps at 3; defensive
        # Keep the established hard-drop behavior for explicit forbidden
        # phrases before the sentence-level sanitizer removes softer
        # unsupported database-behavior claims.
        raw_title = _apply_vocabulary(item.title, vocab)
        raw_explanation = _apply_vocabulary(item.explanation, vocab)
        if _contains_forbidden(raw_title, forbidden) or _contains_forbidden(raw_explanation, forbidden):
            dropped += 1
            continue
        title = _sanitize_user_prose(raw_title, {}, literal_hints)
        explanation = _sanitize_user_prose(raw_explanation, {}, literal_hints)
        # Keep the sanitized model wording for pattern classification even if
        # a lower safety layer later replaces the user-facing text.
        guard_title = title
        guard_explanation = explanation
        # 2026-09-17: code fragments are shown to the reviewer who owns the
        # data, so restore masked literals there too (previously `:STR_002`
        # leaked through into the advice card — confirmed in a production
        # printout). Prose fields are never un-masked.
        example = unmask_sql(item.example, reverse_map or {}) if item.example else None
        before = unmask_sql(item.before, reverse_map or {}) if item.before else None
        verification: str | None = None
        assumption: str | None = None
        safety_issue = _advice_example_safety_issue(source_sql, before, example) if example else None
        if safety_issue is not None:
            logger.info("ai_service: advice SQL example hidden by deterministic safety guard: %s", safety_issue)
            example = None
            before = None
            verification = "unverified"
            # Once the model has demonstrated that this advice depends on an
            # invented identifier/value or lost typed-literal context, do not
            # keep its accompanying prose: the same hallucinated detail may
            # be repeated there. Replace it with a server-owned, useful
            # business instruction instead of merely appending a warning.
            if safety_issue == "unknown_identifier":
                title = "請先確認查詢條件或資料表關聯"
                explanation = (
                    "這個改善方向需要原 SQL 未提供的欄位或關聯資訊。"
                    "請先確認實際查詢範圍或正確的資料表關聯欄位，系統不會自行猜測。"
                )
            elif safety_issue == "unknown_literal":
                title = "請先確認業務條件"
                explanation = (
                    "這個改善方向需要原 SQL 未提供的業務值或切分規則。"
                    "請先確認實際條件，系統不會自行編造可直接套用的值。"
                )
            else:
                title = "請先確認日期或時間條件"
                explanation = (
                    "這個改善方向涉及日期／時間常數的型態前提。"
                    "系統目前無法確認可採用的改寫，因此只保留方向提醒。"
                )
        elif example:
            if before:
                # Concrete SQL is a privilege, not a warning label. Only a
                # deterministic verified/corrected rewrite may reach the API
                # as copyable SQL.
                v = rewrite_rules.verify_fragment(before, example)
                verification, assumption = v.status, v.assumption
                if v.status == "corrected":
                    logger.info("ai_service: advice fragment corrected by rule %s", v.rule)
                    example = v.example
                elif v.status == "unverified":
                    logger.info("ai_service: unverified advice SQL hidden; prose-only guidance kept")
                    example = None
                    before = None
                    assumption = None
            else:
                logger.info("ai_service: advice SQL without original fragment hidden; cannot verify safely")
                example = None
                verification = "unverified"

        if before and not example:
            before = None

        if verification not in _VERIFIED:
            guarded_explanation, prose_guard = _guard_unverified_advice_prose(
                source_sql,
                guard_title,
                guard_explanation,
            )
            if prose_guard is not None:
                explanation = guarded_explanation
                verification = "unverified"
                logger.info("ai_service: advice-only prose normalized by guard: %s", prose_guard)
        kept.append(
            AdviceItem(
                title=title,
                explanation=explanation,
                example=example,
                impact=item.impact,
                before=before,
                verification=verification,
                assumption=assumption,
            )
        )
    if dropped:
        # PRD: log a counter on a forbidden-phrase hit, never the content
        # that triggered it. INFO (not debug) so this decision is visible in
        # production logs without needing debug-level logging enabled — see
        # tasks/lessons.md "決策 log 用 debug 等於沒有 log".
        logger.info("ai_service: dropped %d advice item(s) on forbidden-phrase match", dropped)
    return kept


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

        # Current VERIFIED_REWRITE authority is predicate-only. Make a
        # WHERE-shell change explicit before the generic skeleton comparison:
        # dropping an existing filter is a condition change, not a
        # "non-condition structure" change.
        orig_where = representative.tree.args.get("where")
        new_where = stmt.tree.args.get("where")
        if (orig_where is None) != (new_where is None):
            return False, "建議寫法新增或移除了 WHERE 查詢條件，可能改變查詢結果"

        # The detailed checks above retain specific user-facing reasons for
        # obvious structure changes; this final skeleton equality closes
        # same-count holes such as changing SELECT/GROUP BY/ORDER BY
        # expressions. Predicate equivalence is checked separately below.
        if rewrite_rules.query_skeleton_without_conditions(
            representative.tree
        ) != rewrite_rules.query_skeleton_without_conditions(stmt.tree):
            return False, "建議寫法改動了查詢欄位、分組、排序或其他非條件結構"

        _compliance, _rows, new_findings = rule_engine.evaluate(
            parsed, cost, rules_config, important_tables_config
        )
        if any(f.status == "BLOCK" for f in new_findings):
            return False, "建議寫法本身會觸發不符合中心規範項目"
        new_notice_count = sum(1 for f in new_findings if f.status == "NOTICE")
        if new_notice_count > original_notice_count:
            return False, "建議寫法的提醒項目多於原始 SQL"

        # 2026-09-17: structure being identical says nothing about the
        # conditions inside it. Every condition the model changed must be a
        # rewrite the system can derive itself (rewrite_rules); anything else
        # is an unproven semantic change and is rejected. Runs last so the
        # more specific compliance/structure reasons above win when they apply.
        ok, why = rewrite_rules.verify_predicate_changes(representative.tree, stmt.tree)
        if not ok:
            return False, why or rewrite_rules.REASON_UNVERIFIABLE_CHANGE

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
    literal_hints: dict[str, dict[str, Any]] | None = None,
) -> SuggestedSql:
    reason = _sanitize_user_prose(raw.reason, vocab, literal_hints)
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
        # Length-based gates are facts the server knows and the model does
        # not; the model's own reason (often the generic PRD sentence it
        # copied from the prompt) must not hide them.
        length_gate = decline_code in ("too_long_for_rewrite", "rewrite_truncated")
        if raw.available or length_gate or reason.strip() == _NO_REWRITE_REASON:
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

    if outcome == "advice_only":
        reason = _tidy_advice_only_reason(reason)

    logger.info("ai_service: rewrite outcome=%s", outcome)
    return SuggestedSql(available=available, reason=reason, sql=sql, outcome=outcome)


# 2026-09-17 user feedback: the advice_only reason must state the business
# fact to confirm, not end in a "therefore no rewrite" clause — the UI already
# says the rewrite was not produced. The prompt asks the model not to write
# it; this regex is the deterministic safety net for when it does anyway.
_NO_REWRITE_TAIL_RE = re.compile(
    r"[，,；;、\s]*(?:故|因此|所以|因而)?(?:本次|此次|這次)?(?:先)?"
    r"(?:不|未|無法|暫不)(?:自動)?(?:產生|提供|給出|進行|做)?(?:完整)?(?:的)?"
    r"(?:建議寫法|改寫結果|改寫|SQL\s*改寫)[。.！!]?\s*$"
)


def _tidy_advice_only_reason(reason: str) -> str:
    """Strip a trailing 「…，故不自動產生建議寫法。」 style clause from a
    model-written advice_only reason. Returns the input unchanged when the
    clause is absent or when stripping would leave nothing."""
    stripped = _NO_REWRITE_TAIL_RE.sub("", reason).strip()
    if not stripped or stripped == reason.strip():
        return reason
    if stripped[-1] not in "。.！!？?":
        stripped += "。"
    return stripped


def _finalize(
    raw: _AiRawResponse,
    reverse_map: dict[str, str],
    candidate_allowed: bool,
    decline_code: str | None,
    ai_guard_cfg: dict[str, Any],
    representative: ParsedStatement | None,
    original_notice_count: int,
    cost: int,
    rules_config: dict[str, Any],
    important_tables_config: dict[str, Any],
    *,
    original_sql: str = "",
    literal_hints: dict[str, dict[str, Any]] | None = None,
) -> AiResult:
    forbidden = ai_guard_cfg.get("forbidden_phrases", [])
    vocab = ai_guard_cfg.get("vocabulary_replacements", {})

    summary: str | None = _sanitize_user_prose(raw.summary, vocab, literal_hints)
    if _contains_forbidden(summary, forbidden):
        logger.info("ai_service: summary discarded on forbidden-phrase match")
        summary = None

    advice = _filter_advice(
        raw.advice,
        forbidden,
        vocab,
        reverse_map,
        source_sql=representative.raw_sql if representative is not None else original_sql,
        literal_hints=literal_hints,
    )
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
        literal_hints,
    )
    # Improvement percentages were never measured Oracle results. The API
    # field remains for wire compatibility, but live and mocked model values
    # are deliberately ignored.
    pct = None

    # 2026-09-17: a `:STR_001` the model made up (not in the reverse map, not
    # in the user's SQL) must not reach the reviewer — see masking.py.
    advice = [
        item.model_copy(
            update={
                "example": scrub_invented_placeholders(item.example, original_sql),
                "before": scrub_invented_placeholders(item.before, original_sql),
            }
        )
        for item in advice
    ]
    if suggested_sql.sql:
        suggested_sql = suggested_sql.model_copy(update={"sql": scrub_invented_placeholders(suggested_sql.sql, original_sql)})

    logger.info(
        "ai_service: model available=%s advice=%d pct=%s",
        suggested_sql.available,
        len(advice),
        pct,
    )

    # Still "ok" even if advice ended up empty after filtering — the model
    # did respond and validate; there is no separate "degraded but ok" state.
    return AiResult(
        status="ok",
        summary=summary,
        advice=advice,
        suggested_sql=suggested_sql,
        estimated_improvement_pct=pct,
    )


# 2026-09-17: one fixed, SQL-free sentence per failure class so the reviewer
# (and whoever reads the printout later) can tell a timeout from a cut-off
# reply without opening the container log. Unknown kinds fall back to the
# PRD §56 sentence.
DEGRADE_MESSAGES: dict[str, str] = {
    "output_truncated": "SQL 內容較長，AI 回覆超出長度上限，本次未能完成分析；可縮短或拆分 SQL 後再試。",
    "prompt_truncated": "SQL 內容過長，超出 AI 可處理範圍，請拆分後再試。",
    "timeout": "AI 分析逾時（SQL 較長時約需 2～3 分鐘），請稍後再試一次。",
    "connection": "無法連線 AI 服務，仍可依上方規則檢核結果進行確認。",
    "configuration": "AI 服務尚未完成連線設定，仍可先使用規則檢核結果。",
    "http": "AI 服務回應異常，仍可依上方規則檢核結果進行確認。",
    "invalid_response": DEGRADE_MESSAGE,
}


def _unavailable(kind: str | None = None) -> AiResult:
    if kind:
        logger.info("ai_service: degraded kind=%s", kind)
    return AiResult(status="unavailable", message=DEGRADE_MESSAGES.get(kind or "", DEGRADE_MESSAGE), degrade_code=kind)


# ---------------------------------------------------------------------------
# LLM provider call
# ---------------------------------------------------------------------------
_CJK_RE = re.compile(r"[㐀-鿿]")


def _estimate_tokens(text: str) -> int:
    """Pessimistic tokenizer-independent estimate used only for local
    context sizing and the full-rewrite output gate.

    The exact provider token count is recorded from the response when the
    provider exposes it; this estimate never claims to be a billing count.
    """
    cjk = len(_CJK_RE.findall(text))
    return int(cjk + (len(text) - cjk) / 4) + 1


def _num_ctx_for(settings: Settings, system_prompt: str, user_content: str) -> int:
    """Choose a context tier.

    Ollama needs an explicit num_ctx and can silently truncate a prompt, so
    SQLCheck doubles the configured tier up to context_window_max. Cloud
    providers such as Gemini manage their own model context; the adapter
    ignores this value, but returning a stable value keeps diagnostics and
    tests provider-neutral.
    """
    needed = (
        _estimate_tokens(system_prompt)
        + _estimate_tokens(user_content)
        + settings.llm.max_output_tokens
        + 512
    )
    tier = settings.llm.context_window
    while tier < needed and tier * 2 <= settings.llm.context_window_max:
        tier *= 2
    return tier


def _chat_request_body(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    """Compatibility helper for Ollama-focused unit tests/debugging.

    Runtime requests go through llm_provider.generate_structured_json().
    """
    user_content = "<SQL_DATA>\n" + json.dumps(payload, ensure_ascii=False) + "\n</SQL_DATA>"
    num_ctx = _num_ctx_for(settings, SYSTEM_PROMPT, user_content)
    return llm_provider._ollama_body(  # noqa: SLF001 - same package compatibility hook
        settings.llm,
        system_prompt=SYSTEM_PROMPT,
        user_content=user_content,
        response_schema=RESPONSE_SCHEMA,
        context_window=num_ctx,
    )


def _record_call_stats(settings: Settings, reply: llm_provider.ProviderReply) -> None:
    """Publish whitelisted diagnostics only; never prompt/SQL/model output."""
    try:
        LAST_CALL_STATS.clear()
        LAST_CALL_STATS.update(
            {
                "provider": reply.provider,
                "model": reply.model,
                "num_ctx": reply.context_window,
                "num_predict": settings.llm.max_output_tokens,
                "think": reply.think,
                "done_reason": reply.finish_reason,
                "eval_count": reply.output_tokens,
                "prompt_eval_count": reply.prompt_tokens,
                "total_tokens": reply.total_tokens,
                "total_duration_ms": reply.total_duration_ms,
            }
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must never break analysis
        logger.debug("ai_service: could not record call stats: %s", type(exc).__name__)


class _NonChineseResponseError(ValueError):
    """The prompt mandates Traditional Chinese; a long summary with no CJK
    character at all is treated as invalid and retried once."""


_MIN_SUMMARY_LEN_FOR_LANGUAGE_CHECK = 20


async def _one_attempt(
    client: httpx.AsyncClient,
    settings: Settings,
    payload: dict[str, Any],
) -> _AiRawResponse:
    """Exactly one provider POST + JSON parse + Pydantic validation."""
    user_content = "<SQL_DATA>\n" + json.dumps(payload, ensure_ascii=False) + "\n</SQL_DATA>"
    num_ctx = _num_ctx_for(settings, SYSTEM_PROMPT, user_content)
    if settings.llm.provider_type == "ollama" and num_ctx > settings.llm.context_window:
        logger.info(
            "ai_service: num_ctx raised to %d for a long prompt (default %d)",
            num_ctx,
            settings.llm.context_window,
        )

    reply = await llm_provider.generate_structured_json(
        client,
        settings.llm,
        system_prompt=SYSTEM_PROMPT,
        user_content=user_content,
        response_schema=RESPONSE_SCHEMA,
        context_window=num_ctx,
    )

    raw = json.loads(reply.content)
    parsed = _AiRawResponse.model_validate(raw)
    summary = parsed.summary or ""
    if len(summary) >= _MIN_SUMMARY_LEN_FOR_LANGUAGE_CHECK and not _CJK_RE.search(summary):
        raise _NonChineseResponseError("summary contains no Chinese")

    logger.info(
        "ai_service: provider=%s model=%s done_reason=%s "
        "eval_count=%s prompt_eval_count=%s total_duration_ms=%s",
        reply.provider,
        reply.model,
        reply.finish_reason,
        reply.output_tokens,
        reply.prompt_tokens,
        reply.total_duration_ms,
    )
    _record_call_stats(settings, reply)
    return parsed


# A second attempt only makes sense if the provider still has time to answer.
_MIN_RETRY_BUDGET_SECONDS = 60.0


def _transport_failure_kind(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return "http"
    if isinstance(exc, llm_provider.LLMConfigurationError):
        return "configuration"
    return "connection"


async def _request_ai(
    settings: Settings,
    payload: dict[str, Any],
    *,
    deadline: float,
    retry_payload: dict[str, Any] | None = None,
) -> tuple[_AiRawResponse | None, str | None, bool]:
    """Returns (raw, failure_kind, used_retry_payload).

    One overall deadline bounds the whole provider call, including retry.
    Transport/configuration failures fail immediately. A provider-reported
    output-token truncation may retry once in advice-only mode. Invalid JSON,
    schema, or non-Chinese output may retry once with the same payload.
    """

    def remaining() -> float:
        return deadline - time.monotonic()

    try:
        await asyncio.wait_for(_LLM_SEMAPHORE.acquire(), timeout=max(remaining(), 0.0))
    except TimeoutError:
        return None, "timeout", False

    try:
        async with httpx.AsyncClient(timeout=max(remaining(), 1.0)) as client:
            second_payload = payload
            used_retry = False
            try:
                return await _one_attempt(client, settings, payload), None, False
            except (httpx.RequestError, httpx.HTTPStatusError, llm_provider.LLMConfigurationError) as exc:
                return None, _transport_failure_kind(exc), False
            except llm_provider.LLMPromptTruncatedError as exc:
                logger.info(
                    "ai_service: prompt truncated by provider "
                    "(prompt_tokens=%d >= context_window=%d) — degrading without retry",
                    exc.prompt_tokens,
                    exc.context_window,
                )
                return None, "prompt_truncated", False
            except llm_provider.LLMOutputTruncatedError as exc:
                if exc.thinking_chars:
                    logger.info(
                        "ai_service: truncated while thinking (thinking_chars=%d) — "
                        "disable provider thinking for schema-constrained JSON output",
                        exc.thinking_chars,
                    )
                if retry_payload is None or remaining() < _MIN_RETRY_BUDGET_SECONDS:
                    logger.info(
                        "ai_service: provider output truncated (output_tokens=%s) — "
                        "degrading (retry_payload=%s, remaining=%.0fs)",
                        exc.output_tokens,
                        retry_payload is not None,
                        remaining(),
                    )
                    return None, "output_truncated", False
                logger.info(
                    "ai_service: provider output truncated (output_tokens=%s) — "
                    "retrying once in advice-only mode (remaining=%.0fs)",
                    exc.output_tokens,
                    remaining(),
                )
                second_payload = retry_payload
                used_retry = True
            except _NonChineseResponseError:
                logger.info("ai_service: response not in Chinese — retrying once")
            except (json.JSONDecodeError, ValidationError, KeyError, TypeError):
                pass

            if settings.llm.max_retries_on_invalid_json <= 0 and not used_retry:
                return None, "invalid_response", False
            if remaining() <= 0:
                return None, "timeout", used_retry

            client.timeout = httpx.Timeout(max(remaining(), 1.0))
            try:
                return await _one_attempt(client, settings, second_payload), None, used_retry
            except (httpx.RequestError, httpx.HTTPStatusError, llm_provider.LLMConfigurationError) as exc:
                return None, _transport_failure_kind(exc), used_retry
            except llm_provider.LLMPromptTruncatedError:
                return None, "prompt_truncated", used_retry
            except llm_provider.LLMOutputTruncatedError as exc:
                logger.info(
                    "ai_service: provider output truncated again on retry (output_tokens=%s) — degrading",
                    exc.output_tokens,
                )
                return None, "output_truncated", used_retry
            except _NonChineseResponseError:
                logger.info("ai_service: response not in Chinese again on retry — degrading")
                return None, "invalid_response", used_retry
            except (json.JSONDecodeError, ValidationError, KeyError, TypeError):
                return None, "invalid_response", used_retry
    finally:
        _LLM_SEMAPHORE.release()


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
    """Never raises — any failure anywhere in this path (provider down,
    invalid response, missing cloud credential, or an unexpected bug) degrades
    to the PRD-mandated "unavailable" result rather than propagating."""
    LAST_CALL_STATS.clear()

    deadline = time.monotonic() + settings.llm.timeout_seconds
    try:
        representative = _pick_representative(statements, findings)
        if representative is not None:
            statement_type = representative.statement_type
            mask_result = mask_sql(
                representative.raw_sql,
                settings.masking.keep_short_ascii_literal_max_len
                if settings.llm.allow_short_ascii_literals
                else 0,
            )
        else:
            statement_type = "UNKNOWN"
            mask_result = mask_sql(
                sql_text,
                settings.masking.keep_short_ascii_literal_max_len
                if settings.llm.allow_short_ascii_literals
                else 0,
            )

        sql_tokens = _estimate_tokens(mask_result.masked_sql)
        candidate_allowed, decline_code = _compute_gates(
            statements, settings.ai_gate, sql_tokens=sql_tokens, num_predict=settings.llm.max_output_tokens
        )

        # Pattern Selector stays fail-open: a catalog/selector problem must
        # never make the existing AI path unavailable. Phase 3 additionally
        # compiles a *bounded exact-only* context for the representative
        # statement. Family signals and OUT_OF_SCOPE entries never reach Gemma.
        selection = pattern_selector.PatternSelection()
        try:
            selection = pattern_selector.select_patterns(statements, findings, settings.rules_config)
            shadow = selection.log_fields()
            logger.info(
                "ai_service: pattern_selector exact=%s family=%s",
                shadow["exact_ids"],
                shadow["family_signal_ids"],
            )
        except Exception as exc:  # noqa: BLE001 - knowledge diagnostics cannot break analysis
            logger.warning("ai_service: pattern_selector failed: %s", type(exc).__name__)

        knowledge_context: list[dict[str, str]] = []
        try:
            knowledge_context = context_adapter.build_knowledge_context(
                selection,
                settings.knowledge_context,
                statement_index=representative.index if representative is not None else None,
            )
            logger.info(
                "ai_service: knowledge_context ids=%s",
                context_adapter.context_ids(knowledge_context),
            )
        except Exception as exc:  # noqa: BLE001 - context is advisory and fail-open
            logger.warning("ai_service: knowledge_context failed: %s", type(exc).__name__)

        where_evidence = None
        if representative is not None and representative.restriction_kind is not None:
            where_evidence = {
                "kind": representative.restriction_kind,
                "detail": representative.restriction_detail,
            }

        logger.info(
            "ai_service: gate candidate=%s decline_code=%s stmt_type=%s flags=%s where_kind=%s sql_tokens=%d",
            candidate_allowed,
            decline_code,
            statement_type,
            sorted(representative.complexity_flags) if representative else [],
            representative.restriction_kind if representative else None,
            sql_tokens,
        )

        def build(candidate: bool) -> dict[str, Any]:
            return _build_payload(
                statement_type=statement_type,
                sanitized_sql=mask_result.masked_sql,
                cost=cost,
                compliance_status=compliance_status,
                findings=findings,
                candidate_allowed=candidate,
                literal_hints=mask_result.literal_hints,
                where_evidence=where_evidence,
                structure_flags=sorted(representative.complexity_flags) if representative else [],
                knowledge_context=knowledge_context,
            )

        payload = build(candidate_allowed)
        # Fallback for an output-truncated first attempt: same request, but
        # advice-only (see `_request_ai`). Only meaningful when a rewrite was
        # allowed in the first place.
        retry_payload = build(False) if candidate_allowed else None

        raw, failure_kind, used_retry = await _request_ai(settings, payload, deadline=deadline, retry_payload=retry_payload)
        if raw is None:
            return _unavailable(failure_kind)
        if used_retry:
            candidate_allowed = False
            decline_code = "rewrite_truncated"

        original_notice_count = 0
        if representative is not None:
            original_notice_count = sum(
                1 for f in findings if f.status == "NOTICE" and f.statement_index == representative.index
            )

        result = _finalize(
            raw,
            mask_result.reverse_map,
            candidate_allowed,
            decline_code,
            settings.ai_guard,
            representative,
            original_notice_count,
            cost,
            settings.rules_config,
            settings.important_tables_config,
            original_sql=sql_text,
            literal_hints=mask_result.literal_hints,
        )
        level, basis = improvement_potential(result, findings)
        return result.model_copy(update={"improvement_potential": level, "improvement_potential_basis": basis})
    except Exception as exc:
        # PRD §50.4: exception type only, never a message/traceback that
        # could embed SQL text (see _revalidate_suggested_sql's comment).
        logger.error(
            "ai_service.get_ai_result: unexpected failure, degrading to unavailable: %s", type(exc).__name__
        )
        return _unavailable()


async def check_llm_available(settings: Settings) -> bool:
    """Backs /api/health for whichever provider is active."""
    return await llm_provider.check_available(settings.llm)


async def check_ollama_available(settings: Settings) -> bool:
    """Backward-compatible alias for older callers/tests."""
    return await check_llm_available(settings)
