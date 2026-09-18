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
        for rid in detection.get("rule_ids") or []:
            assert _RULE_ID_RE.match(rid), f"{p.get('id')}: malformed rule_id {rid!r}"


def test_rewrite_rule_ids_reference_known_rewrite_rules_module_rules(patterns: list[dict[str, Any]]) -> None:
    import inspect
    import re

    from app.services import rewrite_rules

    # The `_RULES` function name suffix does NOT always match the `Rewrite.rule`
    # string it emits (e.g. `_rule_substr_eq` emits rule="substr_eq_to_like").
    # Extract the actual `rule="..."` literal from each function's source so
    # this test breaks loudly if a rule is renamed/removed/added, without
    # guessing from the function name.
    documented_rule_names: set[str] = set()
    for fn in rewrite_rules._RULES:
        match = re.search(r'rule="([a-z_]+)"', inspect.getsource(fn))
        assert match, f"{fn.__name__}: could not find a rule=\"...\" literal in its source"
        documented_rule_names.add(match.group(1))
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
