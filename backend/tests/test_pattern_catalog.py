"""Integrity checks for backend/app/knowledge/pattern_catalog.yaml.

This validates the knowledge ASSET only — pattern ids, classification rules,
provenance, and the governance invariants from the SQLCheck Oracle Knowledge
v1 Phase 1 design. It never initializes Ollama, never imports ai_service, and
never touches the running request path: the catalog is not wired into the
runtime yet (see skills/sqlcheck-oracle-review/references/project-boundaries.md).
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
