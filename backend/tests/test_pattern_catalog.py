"""Integrity checks for backend/app/knowledge/pattern_catalog.yaml.

This validates the knowledge asset — pattern ids, classification rules,
provenance, and governance invariants. Phase 2's pattern_selector.py reads the
catalog in shadow mode, but these tests still never initialize Ollama and never
need a live model or Oracle connection. Runtime selection behavior is covered
separately by tests/test_pattern_selector.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_CATALOG_PATH = Path(__file__).resolve().parents[1] / "app" / "knowledge" / "pattern_catalog.yaml"

_VALID_CLASSIFICATIONS = {"VERIFIED_REWRITE", "ADVICE_ONLY", "INFORMATIONAL", "OUT_OF_SCOPE"}
_VALID_DETECTION_SOURCES = {
    "rule_engine",
    "rewrite_rules",
    "sql_parser_complexity_flag",
    "improvement_score_structure",
    "prompt_heuristic_only",
    "none",
}
_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_RULE_ID_RE = re.compile(r"^R\d{3}$")
_VALID_SOURCE_TYPES = {"internal", "external_skill", "oracle_documentation"}
_VALID_RUNTIME_GAP_KINDS = {"unverified_precondition", "unauthorized_accepted_form"}
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_RULES_YAML = _BACKEND_DIR / "app" / "config" / "rules.yaml"
_SQL_PARSER_PY = _BACKEND_DIR / "app" / "services" / "sql_parser.py"

# Which specific-id list belongs to which deterministic detection.source.
_SPECIFIC_LIST_FOR_SOURCE = {
    "rule_engine": "rule_ids",
    "rewrite_rules": "rewrite_rule_ids",
    "sql_parser_complexity_flag": "complexity_flags",
    "improvement_score_structure": "structure_keys",
}

# Oracle 19c: "You can specify up to 1000 expressions in expression_list."
# https://docs.oracle.com/en/database/oracle/oracle-database/19/sqlrf/IN-Condition.html
_ORACLE_IN_LIST_MAX_EXPRESSIONS = 1000
# Runtime rewrite rules whose output is a single IN list.
_IN_LIST_PRODUCING_RUNTIME_RULES = {"or_eq_to_in"}
_VALID_BOUNDARY_KEYS = {"max_in_list_expressions", "oracle_version", "description_zh_tw"}

# rule_engine rules that fire for a whole family, so they can never be the
# specific detector of one pattern (PR #2 review item 4). Add a rule here
# when its findings cover several catalog patterns at once.
_FAMILY_ONLY_RULE_IDS = {
    "R005": "fires on any function applied to a condition column",
    "R006": "fires on any OR, same-column or cross-column",
}


def _load_catalog() -> dict[str, Any]:
    with _CATALOG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), "pattern_catalog.yaml must parse to a mapping"
    return data


@pytest.fixture(scope="module")
def catalog() -> dict[str, Any]:
    return _load_catalog()


@pytest.fixture(scope="module")
def patterns(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    patterns = catalog.get("patterns")
    assert isinstance(patterns, list) and patterns, "catalog must declare at least one pattern"
    return patterns


def test_catalog_has_version(catalog: dict[str, Any]) -> None:
    assert isinstance(catalog.get("catalog_version"), int)


def test_pattern_ids_are_nonempty_unique_and_well_formed(patterns: list[dict[str, Any]]) -> None:
    ids = [p.get("id") for p in patterns]
    for pid in ids:
        assert pid, "pattern id must not be empty/blank"
        assert isinstance(pid, str) and _ID_RE.match(pid), f"pattern id not upper_snake_case: {pid!r}"
    assert len(ids) == len(set(ids)), "pattern ids must be unique"


def test_classification_is_one_of_four_legal_values(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        assert p.get("classification") in _VALID_CLASSIFICATIONS, (
            f"{p.get('id')}: illegal classification {p.get('classification')!r}"
        )


def test_every_pattern_has_provenance(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        sources = p.get("sources")
        assert isinstance(sources, list) and sources, f"{p.get('id')}: missing provenance (sources)"
        for s in sources:
            assert s.get("type") in _VALID_SOURCE_TYPES, f"{p.get('id')}: bad source type {s!r}"
            assert s.get("ref"), f"{p.get('id')}: source missing ref"


def test_verified_rewrite_requires_deterministic_linkage(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        if p.get("classification") != "VERIFIED_REWRITE":
            continue
        verification = p.get("verification") or {}
        assert verification.get("required_for_rewrite") is True, (
            f"{p.get('id')}: VERIFIED_REWRITE must require verification"
        )
        assert verification.get("mechanism") == "deterministic_python", (
            f"{p.get('id')}: VERIFIED_REWRITE must name a deterministic mechanism"
        )
        detection = p.get("detection") or {}
        assert detection.get("source") == "rewrite_rules", (
            f"{p.get('id')}: VERIFIED_REWRITE must be detected via rewrite_rules"
        )
        assert detection.get("rewrite_rule_ids"), (
            f"{p.get('id')}: VERIFIED_REWRITE must name its rewrite_rules.py rule id(s)"
        )


def test_out_of_scope_never_allows_automatic_rewrite(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        if p.get("classification") != "OUT_OF_SCOPE":
            continue
        allowed = p.get("allowed_behavior") or {}
        assert allowed.get("automatic_rewrite") is False, f"{p.get('id')}: OUT_OF_SCOPE must not allow automatic_rewrite"


def test_advice_only_never_allows_automatic_rewrite(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        if p.get("classification") != "ADVICE_ONLY":
            continue
        allowed = p.get("allowed_behavior") or {}
        assert allowed.get("automatic_rewrite") is False, f"{p.get('id')}: ADVICE_ONLY must not allow automatic_rewrite"


def test_only_verified_rewrite_may_allow_automatic_rewrite(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        allowed = p.get("allowed_behavior") or {}
        if allowed.get("automatic_rewrite") is True:
            assert p.get("classification") == "VERIFIED_REWRITE", (
                f"{p.get('id')}: only VERIFIED_REWRITE may set automatic_rewrite=true"
            )


def test_allowed_behavior_fields_present_and_boolean(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        allowed = p.get("allowed_behavior") or {}
        for key in ("explain", "advice", "automatic_rewrite"):
            assert isinstance(allowed.get(key), bool), f"{p.get('id')}: allowed_behavior.{key} must be a bool"


def test_detection_source_is_declared_and_legal(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        detection = p.get("detection") or {}
        source = detection.get("source")
        assert source in _VALID_DETECTION_SOURCES, f"{p.get('id')}: illegal detection.source {source!r}"


def test_rule_ids_are_well_formed_when_present(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        detection = p.get("detection") or {}
        family = detection.get("family_signals") or {}
        for rid in (detection.get("rule_ids") or []) + (family.get("rule_ids") or []):
            assert _RULE_ID_RE.match(rid), f"{p.get('id')}: malformed rule_id {rid!r}"


def test_specific_detection_lists_match_source(patterns: list[dict[str, Any]]) -> None:
    """`source` names the detector that hits THIS pattern specifically. Only
    the id list belonging to that source may be filled; `none` and
    `prompt_heuristic_only` mean no specific deterministic detector, so all
    four lists must be empty (family-level signals go in family_signals)."""
    all_lists = set(_SPECIFIC_LIST_FOR_SOURCE.values())
    for p in patterns:
        detection = p.get("detection") or {}
        source = detection.get("source")
        expected = _SPECIFIC_LIST_FOR_SOURCE.get(source)
        if expected is not None:
            assert detection.get(expected), f"{p.get('id')}: source {source!r} needs a non-empty {expected}"
        for key in all_lists - {expected}:
            assert not detection.get(key), (
                f"{p.get('id')}: {key} is only allowed with its own source, got source={source!r}"
            )


def test_family_only_rules_are_never_specific_detectors(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        for rid in (p.get("detection") or {}).get("rule_ids") or []:
            assert rid not in _FAMILY_ONLY_RULE_IDS, (
                f"{p.get('id')}: {rid} {_FAMILY_ONLY_RULE_IDS.get(rid)}; list it under family_signals instead"
            )


def test_family_signals_are_well_formed(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        family = (p.get("detection") or {}).get("family_signals")
        if family is None:
            continue
        assert set(family) <= {"rule_ids", "complexity_flags", "qualifier_zh_tw"}, (
            f"{p.get('id')}: unknown family_signals key(s) {set(family) - {'rule_ids', 'complexity_flags', 'qualifier_zh_tw'}}"
        )
        assert family.get("rule_ids") or family.get("complexity_flags"), f"{p.get('id')}: empty family_signals"
        assert (family.get("qualifier_zh_tw") or "").strip(), (
            f"{p.get('id')}: family_signals needs qualifier_zh_tw saying what the signal cannot tell apart"
        )


def test_referenced_rule_ids_exist_in_rules_yaml(patterns: list[dict[str, Any]]) -> None:
    rules = yaml.safe_load(_RULES_YAML.read_text(encoding="utf-8"))
    known = {r["id"] for r in rules["rules"]}
    for p in patterns:
        detection = p.get("detection") or {}
        family = detection.get("family_signals") or {}
        for rid in (detection.get("rule_ids") or []) + (family.get("rule_ids") or []):
            assert rid in known, f"{p.get('id')}: rule_id {rid!r} is not defined in rules.yaml"


def test_referenced_complexity_flags_are_emitted_by_sql_parser(patterns: list[dict[str, Any]]) -> None:
    emitted = set(re.findall(r'flags\.add\("([a-z_]+)"\)', _SQL_PARSER_PY.read_text(encoding="utf-8")))
    assert emitted, "could not find any flags.add(...) in sql_parser.py"
    for p in patterns:
        detection = p.get("detection") or {}
        family = detection.get("family_signals") or {}
        for flag in (detection.get("complexity_flags") or []) + (family.get("complexity_flags") or []):
            assert flag in emitted, f"{p.get('id')}: complexity flag {flag!r} is never emitted by sql_parser.py"


def test_referenced_structure_keys_exist_in_rules_yaml(patterns: list[dict[str, Any]]) -> None:
    rules = yaml.safe_load(_RULES_YAML.read_text(encoding="utf-8"))
    known = set(rules["improvement_score"]["structure"]["weights"])
    for p in patterns:
        for key in (p.get("detection") or {}).get("structure_keys") or []:
            assert key in known, f"{p.get('id')}: structure key {key!r} is not in rules.yaml structure.weights"


def _runtime_rewrite_rule_names() -> set[str]:
    """The `Rewrite.rule` names the runtime can emit, one per `_RULES`
    function. The function-name suffix does NOT always match the emitted name
    (`_rule_substr_eq` emits rule="substr_eq_to_like"), so read the literal
    from each function's source instead of guessing."""
    import inspect

    from app.services import rewrite_rules

    names: set[str] = set()
    for fn in rewrite_rules._RULES:
        found = re.findall(r'rule="([a-z_]+)"', inspect.getsource(fn))
        assert len(set(found)) == 1, f"{fn.__name__}: expected exactly one rule=\"...\" literal, found {found}"
        names.add(found[0])
    return names


def test_rewrite_rule_ids_reference_known_rewrite_rules_module_rules(patterns: list[dict[str, Any]]) -> None:
    documented_rule_names = _runtime_rewrite_rule_names()
    for p in patterns:
        detection = p.get("detection") or {}
        for rid in detection.get("rewrite_rule_ids") or []:
            assert rid in documented_rule_names, (
                f"{p.get('id')}: rewrite_rule_id {rid!r} does not match a known rewrite_rules.py rule"
            )


def test_verification_mechanism_is_declared(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        verification = p.get("verification") or {}
        assert verification.get("mechanism") in ("deterministic_python", "none"), (
            f"{p.get('id')}: verification.mechanism must be declared"
        )
        assert isinstance(verification.get("required_for_rewrite"), bool), (
            f"{p.get('id')}: verification.required_for_rewrite must be a bool"
        )


def test_deterministic_proof_mechanism_is_reserved_for_verified_rewrite(patterns: list[dict[str, Any]]) -> None:
    """`deterministic_python` means a governance-accepted proof exists. A
    runtime rule whose equivalence rests on an unchecked precondition (TRUNC,
    NVL) must not claim it just because rewrite_rules.py has code for it."""
    for p in patterns:
        if (p.get("verification") or {}).get("mechanism") == "deterministic_python":
            assert p.get("classification") == "VERIFIED_REWRITE", (
                f"{p.get('id')}: only VERIFIED_REWRITE may declare a deterministic_python proof"
            )


def test_runtime_gap_is_well_formed(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        gap = p.get("runtime_gap")
        if gap is None:
            continue
        pid = p.get("id")
        assert gap.get("kind") in _VALID_RUNTIME_GAP_KINDS, f"{pid}: illegal runtime_gap.kind {gap.get('kind')!r}"
        rewrite_rule_ids = (p.get("detection") or {}).get("rewrite_rule_ids") or []
        assert gap.get("runtime_rule") in rewrite_rule_ids, (
            f"{pid}: runtime_gap.runtime_rule must be one of this pattern's rewrite_rule_ids"
        )
        assert (gap.get("description_zh_tw") or "").strip(), f"{pid}: runtime_gap needs description_zh_tw"
        assert (gap.get("required_action_zh_tw") or "").strip(), f"{pid}: runtime_gap needs required_action_zh_tw"
        if gap["kind"] == "unauthorized_accepted_form":
            forms = gap.get("not_authorized_forms")
            assert isinstance(forms, list) and forms, f"{pid}: unauthorized_accepted_form must list not_authorized_forms"


def test_runtime_rule_not_certified_by_governance_must_declare_runtime_gap(patterns: list[dict[str, Any]]) -> None:
    """rewrite_rules.py labels every derivable fragment verified/corrected. If
    governance classifies that rule below VERIFIED_REWRITE, the mismatch must
    be recorded explicitly — never left for a future selector to discover."""
    for p in patterns:
        rewrite_rule_ids = (p.get("detection") or {}).get("rewrite_rule_ids") or []
        if rewrite_rule_ids and p.get("classification") != "VERIFIED_REWRITE":
            assert p.get("runtime_gap"), (
                f"{p.get('id')}: runtime rule {rewrite_rule_ids} is not VERIFIED_REWRITE here, so runtime_gap is required"
            )


def test_verified_rewrite_never_rests_on_an_unverified_precondition(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        if p.get("classification") != "VERIFIED_REWRITE":
            continue
        gap = p.get("runtime_gap") or {}
        assert gap.get("kind") != "unverified_precondition", (
            f"{p.get('id')}: a pattern with an unverified precondition cannot be VERIFIED_REWRITE"
        )


def test_every_runtime_rewrite_rule_has_exactly_one_governance_entry(patterns: list[dict[str, Any]]) -> None:
    """Reverse direction of the check above (PR #2 review item 5): a rule
    added to rewrite_rules._RULES without a catalog entry must fail here.
    The entry may have any classification — what is locked is that a
    governance decision exists, not that every runtime rule is Class A."""
    owners: dict[str, list[str]] = {}
    for p in patterns:
        for rid in (p.get("detection") or {}).get("rewrite_rule_ids") or []:
            owners.setdefault(rid, []).append(p.get("id"))
    for rule_name in sorted(_runtime_rewrite_rule_names()):
        assert len(owners.get(rule_name, [])) == 1, (
            f"runtime rewrite rule {rule_name!r} must have exactly one catalog entry, found {owners.get(rule_name, [])}"
        )


def test_authorized_boundary_is_well_formed(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        boundary = p.get("authorized_boundary")
        if boundary is None:
            continue
        pid = p.get("id")
        assert p.get("classification") == "VERIFIED_REWRITE", f"{pid}: authorized_boundary only applies to VERIFIED_REWRITE"
        assert set(boundary) <= _VALID_BOUNDARY_KEYS, f"{pid}: unknown authorized_boundary key(s) {set(boundary) - _VALID_BOUNDARY_KEYS}"
        limit = boundary.get("max_in_list_expressions")
        assert isinstance(limit, int) and 1 <= limit <= _ORACLE_IN_LIST_MAX_EXPRESSIONS, (
            f"{pid}: max_in_list_expressions must be an int in 1..{_ORACLE_IN_LIST_MAX_EXPRESSIONS}, got {limit!r}"
        )
        assert (boundary.get("description_zh_tw") or "").strip(), f"{pid}: authorized_boundary needs description_zh_tw"


def _owner_of_runtime_rule(patterns: list[dict[str, Any]], rule_name: str) -> dict[str, Any]:
    owners = [p for p in patterns if rule_name in ((p.get("detection") or {}).get("rewrite_rule_ids") or [])]
    assert len(owners) == 1, f"{rule_name}: expected exactly one catalog owner, found {[p.get('id') for p in owners]}"
    return owners[0]


def test_in_list_verified_rewrite_never_authorizes_more_than_oracle_limit(patterns: list[dict[str, Any]]) -> None:
    """PR #2 review round 2 item 1: a Class A rewrite must also produce SQL
    Oracle can execute. A single IN list holds at most 1000 expressions, so
    an IN-producing VERIFIED_REWRITE must declare a boundary that excludes a
    synthetic 1001-value input."""
    for rule_name in _IN_LIST_PRODUCING_RUNTIME_RULES:
        p = _owner_of_runtime_rule(patterns, rule_name)
        if p.get("classification") != "VERIFIED_REWRITE":
            continue
        limit = (p.get("authorized_boundary") or {}).get("max_in_list_expressions")
        assert isinstance(limit, int), f"{p.get('id')}: IN-producing VERIFIED_REWRITE must declare max_in_list_expressions"
        over_limit = _ORACLE_IN_LIST_MAX_EXPRESSIONS + 1
        assert over_limit > limit, f"{p.get('id')}: a {over_limit}-value IN list must not be authorized"


def _derive_same_column_or_chain(n: int):
    """Derive a synthetic `A.C = 1 OR ... OR A.C = n` chain at the default
    recursion limit (the runtime flattens OR chains iteratively)."""
    from app.services import rewrite_rules as rr

    atom = rr.parse_predicate(" OR ".join(f"A.C = {i}" for i in range(1, n + 1)))
    assert atom is not None, f"synthetic {n}-value OR chain failed to parse"
    return rr.derive(atom)


def test_runtime_or_to_in_matches_catalog_boundary_and_gap(patterns: list[dict[str, Any]]) -> None:
    """The runtime must never authorize more than the catalog boundary, and
    the catalog's runtime_gap must exist exactly when the runtime still
    derives an IN list past that boundary."""
    from app.services import rewrite_rules as rr

    p = _owner_of_runtime_rule(patterns, "or_eq_to_in")
    limit = (p.get("authorized_boundary") or {}).get("max_in_list_expressions")
    assert isinstance(limit, int)
    assert limit >= rr.ORACLE_IN_LIST_MAX_EXPRESSIONS, "runtime IN-list limit exceeds the catalog's authorized boundary"

    inside = _derive_same_column_or_chain(rr.ORACLE_IN_LIST_MAX_EXPRESSIONS)
    assert inside is not None and inside.rule == "or_eq_to_in", "probe sanity: the runtime limit itself must still derive IN"
    runtime_accepts_over_limit = _derive_same_column_or_chain(limit + 1) is not None
    assert runtime_accepts_over_limit == bool(p.get("runtime_gap")), (
        f"{p.get('id')}: runtime {'still derives' if runtime_accepts_over_limit else 'no longer derives'} "
        f"a {limit + 1}-value IN list, so runtime_gap must {'be declared' if runtime_accepts_over_limit else 'be removed'}"
    )


# Synthetic probes of forms the catalog does NOT certify, keyed by the pattern
# that governs them: (before, example, statuses meaning "the runtime certifies
# this form"). For SUBSTR only "verified" counts — "corrected" means the
# runtime replaced the range with its own canonical LIKE, which is certified.
_UNCERTIFIED_FORM_PROBES: dict[str, list[tuple[str, str, frozenset[str]]]] = {
    "SUBSTR_EQ_TO_LIKE": [
        ("SUBSTR(A.C, 1, 3) = '107'", "A.C >= '107' AND A.C < '108'", frozenset({"verified"})),
    ],
    "TRUNC_EQ_TO_RANGE": [
        ("TRUNC(A.D) = :X", "A.D >= :X AND A.D < :X + 1", frozenset({"verified", "corrected"})),
        ("TRUNC(A.D) = :X", "A.D BETWEEN :X AND :X + 1", frozenset({"verified", "corrected"})),
    ],
    "NVL_EQ_TO_OR_IS_NULL": [
        ("NVL(A.S, 'N') = 'N'", "(A.S = 'N' OR A.S IS NULL)", frozenset({"verified", "corrected"})),
        ("NVL(A.S, 'N') = 'Y'", "A.S = 'Y'", frozenset({"verified", "corrected"})),
    ],
    "OR_SAME_COLUMN_TO_IN": [
        (
            " OR ".join(f"A.C = {i}" for i in range(1, 1002)),
            f"A.C IN ({', '.join(str(i) for i in range(1, 1002))})",
            frozenset({"verified", "corrected"}),
        ),
    ],
}


def test_runtime_gap_matches_what_the_runtime_actually_certifies(patterns: list[dict[str, Any]]) -> None:
    """Runtime Correctness v1: the catalog's runtime_gap must describe the
    runtime exactly — declared while the runtime still certifies a form the
    catalog does not, removed once it no longer does."""
    from app.services import rewrite_rules as rr

    by_id = {p.get("id"): p for p in patterns}
    for pid, probes in _UNCERTIFIED_FORM_PROBES.items():
        assert pid in by_id, f"probe refers to unknown pattern {pid!r}"
        certified = [
            (before[:40], example[:40], status)
            for before, example, certifying in probes
            if (status := rr.verify_fragment(before, example).status) in certifying
        ]
        has_gap = bool(by_id[pid].get("runtime_gap"))
        assert bool(certified) == has_gap, (
            f"{pid}: runtime certifies {certified} but runtime_gap is {'declared' if has_gap else 'absent'}"
        )


def test_every_declared_runtime_gap_has_a_probe(patterns: list[dict[str, Any]]) -> None:
    for p in patterns:
        if p.get("runtime_gap"):
            assert p.get("id") in _UNCERTIFIED_FORM_PROBES, f"{p.get('id')}: add a probe for its runtime_gap"


def test_no_duplicate_source_of_truth_pattern_names(patterns: list[dict[str, Any]]) -> None:
    """Every VERIFIED_REWRITE rewrite_rule_id maps to exactly one catalog
    pattern id — otherwise the catalog would be a second, possibly
    conflicting, source of truth for the same rewrite."""
    seen: dict[str, str] = {}
    for p in patterns:
        detection = p.get("detection") or {}
        for rid in detection.get("rewrite_rule_ids") or []:
            if rid in seen:
                raise AssertionError(
                    f"rewrite_rule_id {rid!r} claimed by both {seen[rid]!r} and {p.get('id')!r}"
                )
            seen[rid] = p.get("id")
