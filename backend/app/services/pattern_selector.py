"""Deterministic SQL pattern selection for Knowledge v1 (Phase 2 shadow mode).

This module reads ``knowledge/pattern_catalog.yaml`` and maps facts SQLCheck
already knows (rule-engine findings, sql_parser complexity flags, and
rewrite_rules proofs) to catalog pattern ids.

Phase 2 contract:
- ``exact`` matches are deterministic and are the *only* patterns eligible for
  a future compact-context adapter.
- ``family_signal`` matches are deliberately ambiguous broader signals from
  the catalog. They are observable in shadow diagnostics but are never treated
  as a confirmed pattern and must not be injected into the model as if matched.
- Selection never changes compliance, scores, rewrite verification, or AI
  output. ``ai_service`` may call it in shadow mode and log ids only.
- Match records contain no SQL text, literal values, table names, or model
  output, so shadow diagnostics cannot become a second copy of user SQL.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from sqlglot import exp

from app.schemas import Finding
from app.services import rewrite_rules
from app.services.sql_parser import ParsedStatement

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
PATTERN_CATALOG_PATH = KNOWLEDGE_DIR / "pattern_catalog.yaml"

MatchKind = Literal["exact", "family_signal"]

SUPPORTED_EXACT_SOURCES = frozenset(
    {"rule_engine", "rewrite_rules", "sql_parser_complexity_flag", "improvement_score_structure"}
)


@dataclass(frozen=True)
class PatternMatch:
    pattern_id: str
    classification: str
    match_kind: MatchKind
    statement_indexes: tuple[int, ...]
    signals: tuple[str, ...]


@dataclass(frozen=True)
class PatternSelection:
    exact: tuple[PatternMatch, ...] = ()
    family_signals: tuple[PatternMatch, ...] = ()

    @property
    def exact_ids(self) -> tuple[str, ...]:
        return tuple(match.pattern_id for match in self.exact)

    @property
    def family_signal_ids(self) -> tuple[str, ...]:
        return tuple(match.pattern_id for match in self.family_signals)

    @property
    def context_candidate_ids(self) -> tuple[str, ...]:
        """Future adapter input: exact matches only, never OUT_OF_SCOPE."""
        return tuple(match.pattern_id for match in self.exact if match.classification != "OUT_OF_SCOPE")

    def log_fields(self) -> dict[str, object]:
        """SQL-free diagnostics suitable for INFO logs / tests."""
        return {
            "exact_ids": list(self.exact_ids),
            "family_signal_ids": list(self.family_signal_ids),
            "exact_count": len(self.exact),
            "family_signal_count": len(self.family_signals),
        }


@lru_cache(maxsize=1)
def _catalog_patterns() -> tuple[dict[str, Any], ...]:
    with PATTERN_CATALOG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if data.get("catalog_version") != 1:
        raise ValueError("unsupported pattern catalog version")
    patterns = data.get("patterns")
    if not isinstance(patterns, list):
        raise ValueError("pattern catalog must contain a patterns list")
    return tuple(p for p in patterns if isinstance(p, dict))


def clear_catalog_cache() -> None:
    """Test helper for catalog-file mutation tests; production never needs it."""
    _catalog_patterns.cache_clear()


def _statement_indexes_for_rule_ids(findings: Sequence[Finding], rule_ids: Iterable[str]) -> tuple[int, ...]:
    wanted = set(rule_ids)
    return tuple(sorted({f.statement_index for f in findings if f.rule_id in wanted}))


def _statement_indexes_for_flags(
    statements: Sequence[ParsedStatement], flags: Iterable[str]
) -> tuple[int, ...]:
    required = set(flags)
    if not required:
        return ()
    # Multiple flags in one catalog entry mean the statement must carry all of
    # them; current catalog entries use one flag, and this rule is deterministic
    # for future compound entries too.
    return tuple(sorted(s.index for s in statements if required.issubset(s.complexity_flags)))


def _rewrite_hits(statements: Sequence[ParsedStatement]) -> dict[str, set[int]]:
    hits: dict[str, set[int]] = {}
    for stmt in statements:
        if stmt.parse_status != "ok" or stmt.tree is None:
            continue
        # Current deterministic rules operate on equality predicates and OR
        # chains. Walking every expression keeps the selector aligned with
        # rewrite_rules without duplicating its pattern predicates here.
        for node in stmt.tree.walk():
            if isinstance(node, exp.Or):
                # Only evaluate the maximal OR chain. sqlglot represents a
                # long chain as nested left-deep OR nodes; evaluating every
                # nested node would falsely select OR_SAME_COLUMN_TO_IN for a
                # 1001+ term chain merely because one inner prefix has <=1000
                # terms. Parentheses do not create a new logical chain.
                parent = node.parent
                while isinstance(parent, exp.Paren):
                    parent = parent.parent
                if isinstance(parent, exp.Or):
                    continue
            elif not isinstance(node, exp.Predicate):
                continue
            rw = rewrite_rules.derive(node)
            if rw is not None:
                hits.setdefault(rw.rule, set()).add(stmt.index)
    return hits


def _many_tables_indexes(
    statements: Sequence[ParsedStatement], rules_config: dict[str, Any]
) -> tuple[int, ...]:
    structure = (rules_config.get("improvement_score") or {}).get("structure") or {}
    threshold = int(structure.get("many_tables_threshold", 4))
    return tuple(sorted(s.index for s in statements if s.table_count >= threshold))


def _exact_match(
    pattern: dict[str, Any],
    *,
    statements: Sequence[ParsedStatement],
    findings: Sequence[Finding],
    rewrite_hits: dict[str, set[int]],
    rules_config: dict[str, Any],
) -> PatternMatch | None:
    detection = pattern.get("detection") or {}
    source = detection.get("source")
    indexes: tuple[int, ...] = ()
    signals: tuple[str, ...] = ()

    if source == "rule_engine":
        rule_ids = tuple(detection.get("rule_ids") or ())
        indexes = _statement_indexes_for_rule_ids(findings, rule_ids)
        signals = tuple(f"rule:{rid}" for rid in rule_ids if any(f.rule_id == rid for f in findings))
    elif source == "sql_parser_complexity_flag":
        flags = tuple(detection.get("complexity_flags") or ())
        indexes = _statement_indexes_for_flags(statements, flags)
        present = {flag for s in statements for flag in s.complexity_flags}
        signals = tuple(f"flag:{flag}" for flag in flags if flag in present)
    elif source == "rewrite_rules":
        rule_ids = tuple(detection.get("rewrite_rule_ids") or ())
        hit_indexes = set()
        active_rules: list[str] = []
        for rid in rule_ids:
            indexes_for_rule = rewrite_hits.get(rid, set())
            if indexes_for_rule:
                hit_indexes.update(indexes_for_rule)
                active_rules.append(rid)
        indexes = tuple(sorted(hit_indexes))
        signals = tuple(f"rewrite:{rid}" for rid in active_rules)
    elif source == "improvement_score_structure":
        keys = tuple(detection.get("structure_keys") or ())
        if "many_tables" in keys:
            indexes = _many_tables_indexes(statements, rules_config)
            if indexes:
                signals = ("structure:many_tables",)
    # prompt_heuristic_only / none intentionally never produce exact matches.

    if not indexes:
        return None
    return PatternMatch(
        pattern_id=str(pattern.get("id")),
        classification=str(pattern.get("classification")),
        match_kind="exact",
        statement_indexes=indexes,
        signals=signals,
    )


def _family_signal_match(
    pattern: dict[str, Any],
    *,
    statements: Sequence[ParsedStatement],
    findings: Sequence[Finding],
) -> PatternMatch | None:
    family = ((pattern.get("detection") or {}).get("family_signals") or {})
    if not family:
        return None

    indexes: set[int] = set()
    signals: list[str] = []

    for rid in family.get("rule_ids") or ():
        matched = {f.statement_index for f in findings if f.rule_id == rid}
        if matched:
            indexes.update(matched)
            signals.append(f"family_rule:{rid}")

    for flag in family.get("complexity_flags") or ():
        matched = {s.index for s in statements if flag in s.complexity_flags}
        if matched:
            indexes.update(matched)
            signals.append(f"family_flag:{flag}")

    if not indexes:
        return None
    return PatternMatch(
        pattern_id=str(pattern.get("id")),
        classification=str(pattern.get("classification")),
        match_kind="family_signal",
        statement_indexes=tuple(sorted(indexes)),
        signals=tuple(signals),
    )


def select_patterns(
    statements: Sequence[ParsedStatement],
    findings: Sequence[Finding],
    rules_config: dict[str, Any],
) -> PatternSelection:
    """Return deterministic exact matches plus ambiguous family signals.

    Ordering follows the catalog, making the result stable across runs and
    suitable for a later deterministic top-N context policy without adding a
    second ordering source here.
    """
    patterns = _catalog_patterns()
    rewrite_hits = _rewrite_hits(statements)

    exact: list[PatternMatch] = []
    family_signals: list[PatternMatch] = []
    exact_ids: set[str] = set()

    for pattern in patterns:
        if pattern.get("oracle_applicable") is False:
            continue
        match = _exact_match(
            pattern,
            statements=statements,
            findings=findings,
            rewrite_hits=rewrite_hits,
            rules_config=rules_config,
        )
        if match is not None:
            exact.append(match)
            exact_ids.add(match.pattern_id)

    for pattern in patterns:
        pattern_id = str(pattern.get("id"))
        if pattern_id in exact_ids or pattern.get("oracle_applicable") is False:
            continue
        match = _family_signal_match(pattern, statements=statements, findings=findings)
        if match is not None:
            family_signals.append(match)

    return PatternSelection(exact=tuple(exact), family_signals=tuple(family_signals))
