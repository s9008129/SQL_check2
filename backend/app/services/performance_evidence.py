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
            "本案已由 AST 確認同一來源存在多個相關 MAX scalar subquery；"
            "因此 Oracle 11g 對 nested subquery 與 unnesting 的原理適用於本案的改善評估。"
        ),
        "REPEATED_SOURCE_UNION_BRANCH": (
            "本案已由 AST 確認多個 set-operation branch 使用相同來源；"
            "因此可依 Oracle 11g「盡量減少重複存取資料」原理評估是否能集中處理。"
        ),
        "LEADING_WILDCARD_LIKE": (
            "本案已由中心規則 R004 確認 LIKE 樣式以前置萬用字元開始；"
            "因此不能套用固定前綴 LIKE 的 Index Range Scan 正向說法。"
        ),
        "COMPOSITE_KEY_EXPRESSION_JOIN": (
            "本案已由 AST 確認不同資料表欄位在比較前至少一側先做函數、串接或運算；"
            "Oracle 11g 對 transformed column 的調校原理可作為檢視依據。"
        ),
        "STRING_CONCAT_PREDICATE_SPLIT": (
            "本案已由 AST 確認條件式先串接欄位再比對；"
            "Oracle 11g 對 untransformed column predicate 的原理可作為檢視依據。"
        ),
        "OR_SAME_COLUMN_TO_IN": (
            "本案 OR→IN 已由系統確認條件等價，且改寫後 IN expression 數量在 Oracle 11g 的 1000 上限內。"
        ),
    }.get(pattern_id, "本案已由 SQLCheck 的確定性 Pattern Selector 確認符合這項 Oracle 11g 原理的適用範圍。")


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
                        "本案 canonical 改寫為固定前綴 LIKE，第一個字元不是 % 或 _；"
                        "因此符合 Oracle 11g 所述的 Index Range Scan 候選條件形狀。"
                    ),
                )
            if "leading_wildcard" in variants:
                add(
                    "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT",
                    match.pattern_id,
                    match.statement_indexes,
                    (
                        "本案雖已確認 SUBSTR→LIKE 的查詢結果不變，但 canonical LIKE 前方仍有萬用字元；"
                        "因此不能把這次安全改寫包裝成一般 B-tree 前綴索引的效能改善證據。"
                    ),
                )

    return items
