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
from app.services.sql_parser import ParsedStatement, parse_sql_text
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
                    "impact": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["title", "explanation"],
            },
        },
        "suggested_sql": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "reason": {"type": "string"},
                "sql": {"type": "string"},
            },
            "required": ["available", "reason"],
        },
        "estimated_improvement_pct": {"type": ["integer", "null"]},
    },
    "required": ["summary", "advice", "suggested_sql"],
}


class _AiRawResponse(BaseModel):
    """Mirrors RESPONSE_SCHEMA for validating the model's raw JSON reply.
    Reuses AdviceItem/SuggestedSql from app.schemas for the nested pieces
    per this module's spec (they already match the schema's required/
    optional fields exactly)."""

    summary: str
    advice: list[AdviceItem] = Field(default_factory=list)
    suggested_sql: SuggestedSql
    estimated_improvement_pct: int | None = None


# ---------------------------------------------------------------------------
# Deterministic gating (PRD §17.4, §25) — never influenced by the model.
# ---------------------------------------------------------------------------
def _compute_gates(
    statements: list[ParsedStatement], findings: list[Finding], ai_gate_cfg: dict[str, Any]
) -> tuple[bool, bool]:
    """candidate_allowed: exactly one statement, SELECT, parsed ok, and none
    of its complexity_flags intersect the configured forbidden set.
    estimate_improvement_allowed: equals candidate_allowed unless
    `ai_gate.estimate_requires_candidate` is false, in which case it is also
    allowed whenever there is at least one finding (both branches per spec).
    """
    forbidden_flags = set(ai_gate_cfg.get("candidate_forbidden_complexity_flags", []))
    candidate_allowed = (
        len(statements) == 1
        and statements[0].statement_type == "SELECT"
        and statements[0].parse_status == "ok"
        and not (statements[0].complexity_flags & forbidden_flags)
    )

    if ai_gate_cfg.get("estimate_requires_candidate", True):
        estimate_allowed = candidate_allowed
    else:
        estimate_allowed = candidate_allowed or bool(findings)

    return candidate_allowed, estimate_allowed


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
) -> dict[str, Any]:
    """Exactly the PRD §20 field set — nothing else, never raw literals,
    never model/Docker/DB connection info."""
    important_table_notices = list(
        dict.fromkeys(f.table for f in findings if f.rule_id == "R007" and f.table)
    )
    return {
        "statement_type": statement_type,
        "sanitized_sql": sanitized_sql,
        "input_cost": cost,
        "compliance": compliance_status,
        "findings": [{"rule_id": f.rule_id, "level": f.status, "fact": f.fact} for f in findings],
        "important_table_notices": important_table_notices,
        "candidate_allowed": candidate_allowed,
        "estimate_improvement_allowed": estimate_improvement_allowed,
    }


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
    advice: list[AdviceItem], forbidden: list[str], vocab: dict[str, str]
) -> list[AdviceItem]:
    kept: list[AdviceItem] = []
    dropped = 0
    for item in advice[:3]:  # RESPONSE_SCHEMA already caps at 3; defensive
        title = _apply_vocabulary(item.title, vocab)
        explanation = _apply_vocabulary(item.explanation, vocab)
        if _contains_forbidden(title, forbidden) or _contains_forbidden(explanation, forbidden):
            dropped += 1
            continue
        kept.append(
            AdviceItem(title=title, explanation=explanation, example=item.example, impact=item.impact)
        )
    if dropped:
        # PRD: log a debug counter on a forbidden-phrase hit, never the
        # content that triggered it.
        logger.debug("ai_service: dropped %d advice item(s) on forbidden-phrase match", dropped)
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


def _select_list_length(tree: Any) -> int | None:
    try:
        return len(tree.expressions)
    except Exception:
        return None


def _revalidate_suggested_sql(
    sql_text: str,
    representative: ParsedStatement,
    original_notice_count: int,
    cost: int,
    rules_config: dict[str, Any],
    important_tables_config: dict[str, Any],
) -> tuple[bool, str | None]:
    """Re-parse and re-run the deterministic rule engine on the model's
    proposed rewrite before it is ever shown to a user (approved plan: "建議
    SQL 必須 sqlglot 可解析、statement type 相同、表集合 ⊆ 原始、SELECT 欄位
    數相同、不引入 hint/ROWNUM、與原始不同、重跑規則引擎不得出現 BLOCK 或更
    多 NOTICE"). The model is never trusted for anything that could change
    query semantics or introduce a new compliance problem — this check is
    the enforcement of that, independent of whatever the model's own
    `reason`/`available` fields claim. Returns (ok, rejection_reason)."""
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
        if not stmt.tables.issubset(representative.tables):
            return False, "建議寫法引用了原始查詢以外的資料表"
        if stmt.hint_evidence is not None:
            return False, "建議寫法不得包含 Hint"
        if "rownum" in stmt.complexity_flags:
            return False, "建議寫法不得包含 ROWNUM"

        if representative.tree is not None and stmt.tree is not None:
            orig_len = _select_list_length(representative.tree)
            new_len = _select_list_length(stmt.tree)
            if orig_len is not None and new_len is not None and orig_len != new_len:
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
    except Exception:
        logger.exception("ai_service: suggested SQL re-validation raised unexpectedly")
        return False, "建議寫法安全性檢查失敗"


def _finalize_suggested_sql(
    raw: SuggestedSql,
    reverse_map: dict[str, str],
    candidate_allowed: bool,
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

    if raw.available and not candidate_allowed:
        # The model's own `reason` was almost certainly written to justify
        # *providing* a rewrite (available=true), so surfacing it verbatim
        # once we flip available to false would read as self-contradictory.
        # Replace it with the PRD's fixed "declined to rewrite" copy instead.
        reason = _NO_REWRITE_REASON

    if _contains_forbidden(reason, forbidden):
        logger.debug("ai_service: suggested_sql.reason discarded on forbidden-phrase match")
        available = False
        reason = "建議寫法說明暫不提供。"

    sql: str | None = None
    if available and raw.sql:
        unmasked = unmask_sql(raw.sql, reverse_map)
        if unmasked and representative is not None:
            ok, rejection = _revalidate_suggested_sql(
                unmasked, representative, original_notice_count, cost, rules_config, important_tables_config
            )
            if ok:
                sql = unmasked
            else:
                logger.debug("ai_service: suggested_sql rejected on re-validation: %s", rejection)
                available = False
                reason = _NO_REWRITE_REASON
        else:
            # No representative statement to validate against, or nothing
            # left after unmasking — conservative: decline rather than show
            # an unvalidated rewrite.
            available = False
            reason = _NO_REWRITE_REASON

    return SuggestedSql(available=available, reason=reason, sql=sql)


def _finalize(
    raw: _AiRawResponse,
    reverse_map: dict[str, str],
    candidate_allowed: bool,
    estimate_allowed: bool,
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
        logger.debug("ai_service: summary discarded on forbidden-phrase match")
        summary = None

    advice = _filter_advice(raw.advice, forbidden, vocab)
    suggested_sql = _finalize_suggested_sql(
        raw.suggested_sql,
        reverse_map,
        candidate_allowed,
        forbidden,
        vocab,
        representative,
        original_notice_count,
        cost,
        rules_config,
        important_tables_config,
    )
    pct = _clamp_round_pct(raw.estimated_improvement_pct, estimate_allowed)

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


async def _one_attempt(client: httpx.AsyncClient, settings: Settings, payload: dict[str, Any]) -> _AiRawResponse:
    """Exactly one POST + parse + validate. Raises on any problem; the
    caller decides retry-once (invalid JSON/shape) vs immediate-fail
    (connection/timeout/HTTP-status) based on the exception type."""
    resp = await client.post(
        f"{settings.ollama.base_url}/api/chat",
        json=_chat_request_body(settings, payload),
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["message"]["content"]  # Ollama's documented chat shape
    raw = json.loads(content)
    return _AiRawResponse.model_validate(raw)


async def _request_ai(settings: Settings, payload: dict[str, Any]) -> _AiRawResponse | None:
    """Returns a validated raw response, or None on any failure. Connection
    and timeout errors fail immediately (never retried — retrying would just
    double the wall-clock wait for no benefit). Invalid JSON / schema
    validation failures are retried exactly once."""
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
            except (json.JSONDecodeError, ValidationError, KeyError, TypeError):
                pass  # retry exactly once below

            try:
                return await _one_attempt(client, settings, payload)
            except (httpx.RequestError, httpx.HTTPStatusError):
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
        candidate_allowed, estimate_allowed = _compute_gates(statements, findings, settings.ai_gate)

        representative = _pick_representative(statements, findings)
        if representative is not None:
            statement_type = representative.statement_type
            mask_result = mask_sql(representative.raw_sql)
        else:
            statement_type = "UNKNOWN"
            mask_result = mask_sql(sql_text)

        payload = _build_payload(
            statement_type=statement_type,
            sanitized_sql=mask_result.masked_sql,
            cost=cost,
            compliance_status=compliance_status,
            findings=findings,
            candidate_allowed=candidate_allowed,
            estimate_improvement_allowed=estimate_allowed,
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
            settings.ai_guard,
            representative,
            original_notice_count,
            cost,
            settings.rules_config,
            settings.important_tables_config,
        )
    except Exception:
        logger.exception("ai_service.get_ai_result: unexpected failure, degrading to unavailable")
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
