"""Deterministic Oracle 11g evidence selection for SQLCheck advice.

The model never chooses an authority source. This module maps exact Pattern
Catalog matches to a reviewed evidence registry and returns reviewer-facing
plain-language claims. URLs remain in the registry for audit; the API exposes
only the approved source label/document and bounded prose.

Evidence answers "why this pattern is worth reviewing", not "did this query
actually run faster". Actual index use, access paths and runtime improvement
still require user-supplied Oracle test evidence.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.schemas import PerformanceEvidence, VerifiedRewrite
from app.services.pattern_selector import PatternSelection, get_catalog_pattern

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
EVIDENCE_REGISTRY_PATH = KNOWLEDGE_DIR / "performance_evidence.yaml"

_LIKE_LITERAL_RE = re.compile(r"\bLIKE\s+'((?:''|[^'])*)'", re.IGNORECASE)


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict[str, Any]]:
    with EVIDENCE_REGISTRY_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if data.get("registry_version") != 1:
        raise ValueError("unsupported performance evidence registry version")
    entries = data.get("evidence")
    if not isinstance(entries, list):
        raise ValueError("performance evidence registry must contain an evidence list")

    registry: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            raise ValueError("invalid performance evidence entry")
        evidence_id = str(entry["id"])
        if evidence_id in registry:
            raise ValueError(f"duplicate performance evidence id: {evidence_id}")
        registry[evidence_id] = entry
    return registry


def clear_evidence_cache() -> None:
    """Test helper; production does not mutate the registry."""
    _registry.cache_clear()


def get_evidence_entry(evidence_id: str) -> dict[str, Any] | None:
    return _registry().get(evidence_id)


def _compact(value: object) -> str:
    return " ".join(str(value or "").split())


def _build_item(
    evidence_id: str,
    *,
    pattern_id: str,
    statement_indexes: tuple[int, ...],
    applicability: str,
) -> PerformanceEvidence:
    entry = get_evidence_entry(evidence_id)
    if entry is None:
        raise ValueError(f"missing performance evidence: {evidence_id}")

    strength = str(entry.get("strength") or "")
    if strength not in {"strong", "conditional"}:
        raise ValueError(f"unsupported evidence strength: {evidence_id}")

    required = {
        "source_label": _compact(entry.get("source_label")),
        "source_document": _compact(entry.get("source_document")),
        "claim_zh_tw": _compact(entry.get("claim_zh_tw")),
        "caveat_zh_tw": _compact(entry.get("caveat_zh_tw")),
    }
    if not all(required.values()):
        raise ValueError(f"incomplete performance evidence: {evidence_id}")

    return PerformanceEvidence(
        evidence_id=evidence_id,
        pattern_id=pattern_id,
        statement_indexes=list(statement_indexes),
        source_label=required["source_label"],
        source_document=required["source_document"],
        claim_zh_tw=required["claim_zh_tw"],
        applicability_zh_tw=_compact(applicability),
        caveat_zh_tw=required["caveat_zh_tw"],
        strength=strength,
    )


def _substr_variant(rewrite: VerifiedRewrite) -> str | None:
    if rewrite.rule != "substr_eq_to_like":
        return None
    match = _LIKE_LITERAL_RE.search(rewrite.after)
    if not match:
        return None
    pattern = match.group(1).replace("''", "'")
    if not pattern:
        return None
    return "leading_wildcard" if pattern[0] in {"%", "_"} else "fixed_prefix"


def _default_applicability(pattern_id: str) -> str:
    return {
        "LATEST_ROW_CORRELATED_MAX": (
            "這支 SQL 對同一來源重複使用 MAX 子查詢來找最新資料，"
            "所以值得評估是否能先把最新資料集中算好，再和主查詢 JOIN。"
        ),
        "REPEATED_SOURCE_UNION_BRANCH": (
            "這支 SQL 的多個區塊會重複讀取相同來源，"
            "所以值得評估是否能把共同資料先取一次，再集中處理。"
        ),
        "LEADING_WILDCARD_LIKE": (
            "這支 SQL 的 LIKE 一開始就是萬用字元，因此無法使用「固定開頭」來先縮小搜尋範圍。"
        ),
        "COMPOSITE_KEY_EXPRESSION_JOIN": (
            "這支 SQL 在 JOIN 比對前，至少有一側先對欄位做函數、串接或運算，"
            "所以值得檢查是否能直接使用原始欄位比對。"
        ),
        "STRING_CONCAT_PREDICATE_SPLIT": (
            "這支 SQL 先把欄位串接起來再比對，"
            "所以值得檢查是否能改成直接用原始欄位做條件。"
        ),
        "OR_SAME_COLUMN_TO_IN": (
            "這支 SQL 的同欄位 OR 已由系統確認可以安全整理成 IN，而且值的數量沒有超過 Oracle 11g 的 1000 個上限。"
        ),
    }.get(pattern_id, "SQLCheck 已確認這支 SQL 符合這項 Oracle 11g 官方調校原則的適用情況。")


def build_performance_evidence(
    selection: PatternSelection,
    verified_rewrites: list[VerifiedRewrite],
) -> list[PerformanceEvidence]:
    """Return reviewed Oracle 11g evidence for exact matches only.

    Family signals never receive evidence. SUBSTR is refined using the
    deterministic canonical rewrite: prefix LIKE and leading-wildcard LIKE
    deliberately receive different access-path wording.
    """
    items: list[PerformanceEvidence] = []
    seen: set[tuple[str, str, tuple[int, ...], str]] = set()

    def add(evidence_id: str, pattern_id: str, indexes: tuple[int, ...], applicability: str) -> None:
        key = (evidence_id, pattern_id, indexes, _compact(applicability))
        if key in seen:
            return
        seen.add(key)
        items.append(
            _build_item(
                evidence_id,
                pattern_id=pattern_id,
                statement_indexes=indexes,
                applicability=applicability,
            )
        )

    for match in selection.exact:
        if match.classification == "OUT_OF_SCOPE":
            continue
        pattern = get_catalog_pattern(match.pattern_id)
        if pattern is None:
            raise ValueError(f"catalog entry missing for evidence pattern {match.pattern_id}")

        for evidence_id in pattern.get("evidence_refs") or ():
            add(
                str(evidence_id),
                match.pattern_id,
                match.statement_indexes,
                _default_applicability(match.pattern_id),
            )

        if match.pattern_id == "SUBSTR_EQ_TO_LIKE":
            variants = {
                _substr_variant(rewrite)
                for rewrite in verified_rewrites
                if rewrite.statement_index in match.statement_indexes
            }
            if "fixed_prefix" in variants:
                add(
                    "ORACLE11G_PREFIX_LIKE_RANGE_SCAN",
                    match.pattern_id,
                    match.statement_indexes,
                    (
                        "這次改寫後的 LIKE 是從固定文字開頭，例如 '13%'；"
                        "如果欄位有合適索引，Oracle 會有較好的機會先縮小搜尋範圍。"
                    ),
                )
            if "leading_wildcard" in variants:
                add(
                    "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT",
                    match.pattern_id,
                    match.statement_indexes,
                    (
                        "這次 SUBSTR→LIKE 雖已確認查詢結果不變，但改寫後的 LIKE 前面仍有萬用字元；"
                        "所以只能說改寫安全，不能因此宣稱一般索引的查找效率一定會變好。"
                    ),
                )

    return items
