"""Compact, deterministic Pattern Catalog context for Gemma.

This is the first runtime consumer of Pattern Selector output that reaches the
model. The safety contract is intentionally narrow:

- only selector ``exact`` matches are eligible;
- ``family_signal`` is never injected;
- ``OUT_OF_SCOPE`` is never injected;
- only static catalog guidance is injected, never SQL text, literals, table
  names, findings text, or model output;
- the number of items and total character budget are bounded;
- items are never truncated mid-guidance: if a whole item does not fit, it is
  skipped;
- priority is fixed by governance class:
  VERIFIED_REWRITE > ADVICE_ONLY > INFORMATIONAL.

The adapter never changes compliance, scoring, rewrite verification, or
candidate gating. It only provides compact explanatory context to Gemma.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.pattern_selector import PatternSelection, get_catalog_pattern

_CLASS_PRIORITY = {
    "VERIFIED_REWRITE": 0,
    "ADVICE_ONLY": 1,
    "INFORMATIONAL": 2,
}

_DEFAULT_MAX_PATTERNS = 4
_DEFAULT_MAX_TOTAL_CHARS = 1800
_HARD_MAX_PATTERNS = 8
_HARD_MAX_TOTAL_CHARS = 6000


def _positive_int(value: object, default: int, hard_max: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0:
        return 0
    return min(parsed, hard_max)


def _compact_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def build_knowledge_context(
    selection: PatternSelection,
    config: Mapping[str, Any] | None,
    *,
    statement_index: int | None,
) -> list[dict[str, str]]:
    """Build bounded model context from exact catalog matches only.

    ``statement_index`` limits context to the statement actually shown to the
    model. This matters for multi-statement input: Pattern Selector observes all
    parsed statements, while ``ai_service`` sends only one representative SQL
    statement to Gemma.
    """
    cfg = config or {}
    if statement_index is None or not bool(cfg.get("enabled", True)):
        return []

    max_patterns = _positive_int(cfg.get("max_patterns"), _DEFAULT_MAX_PATTERNS, _HARD_MAX_PATTERNS)
    max_total_chars = _positive_int(
        cfg.get("max_total_chars"), _DEFAULT_MAX_TOTAL_CHARS, _HARD_MAX_TOTAL_CHARS
    )
    if max_patterns == 0 or max_total_chars == 0:
        return []

    candidates: list[tuple[int, int, dict[str, str]]] = []

    for catalog_order, match in enumerate(selection.exact):
        if match.classification == "OUT_OF_SCOPE":
            continue
        if statement_index is not None and statement_index not in match.statement_indexes:
            continue

        pattern = get_catalog_pattern(match.pattern_id)
        if pattern is None:
            raise ValueError(f"catalog entry missing for exact pattern {match.pattern_id}")

        classification = str(pattern.get("classification") or "")
        if classification != match.classification:
            raise ValueError(f"classification drift for exact pattern {match.pattern_id}")
        if classification not in _CLASS_PRIORITY:
            # OUT_OF_SCOPE was already excluded; any future class must be
            # deliberately supported rather than silently injected.
            continue

        guidance = _compact_text(pattern.get("model_guidance_zh_tw"))
        name = _compact_text(pattern.get("name_zh_tw"))
        if not guidance or not name:
            raise ValueError(f"model guidance missing for exact pattern {match.pattern_id}")

        item = {
            "pattern_id": match.pattern_id,
            "classification": classification,
            "name_zh_tw": name,
            "guidance_zh_tw": guidance,
        }
        candidates.append((_CLASS_PRIORITY[classification], catalog_order, item))

    candidates.sort(key=lambda row: (row[0], row[1]))

    selected: list[dict[str, str]] = []
    used_chars = 0
    for _, _, item in candidates:
        if len(selected) >= max_patterns:
            break
        # Count only values because JSON punctuation/key names are fixed and
        # small; this remains a deterministic, conservative tuning boundary.
        item_chars = sum(len(value) for value in item.values())
        if used_chars + item_chars > max_total_chars:
            continue
        selected.append(item)
        used_chars += item_chars

    return selected


def context_ids(context: list[dict[str, str]]) -> tuple[str, ...]:
    """SQL-free diagnostic ids for logging/tests."""
    return tuple(item["pattern_id"] for item in context)
