"""Golden Semantic Trap dataset runner (Phase 1 — knowledge asset only).

Loads `tests/knowledge/semantic_traps.yaml` and checks each case against
SQLCheck's existing PURE deterministic verifiers
(`app.services.rewrite_rules`, `app.services.sql_parser`). This proves those
verifiers already refuse to bless the rewrites `pattern_catalog.yaml` and
`skills/sqlcheck-oracle-review/references/advice-only-patterns.md` document
as semantic traps — independent of any future Gemma integration.

This module must NEVER import `app.services.ai_service` or initialize
Ollama. It is not a Runtime test; it is a knowledge-asset regression test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlglot import parse_one

from app.services import rewrite_rules as rr
from app.services import sql_parser

DATASET_PATH = Path(__file__).resolve().parent / "knowledge" / "semantic_traps.yaml"
APP_YAML_PATH = Path(__file__).resolve().parents[1] / "app" / "config" / "app.yaml"
DIALECT = "oracle"


def _load_cases() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["cases"]


CASES = _load_cases()
CATALOG_IDS = {p["id"] for p in yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "app" / "knowledge" / "pattern_catalog.yaml").read_text(encoding="utf-8")
)["patterns"]}


def _id(case: dict[str, Any]) -> str:
    return case["id"]


@pytest.mark.parametrize("case", CASES, ids=_id)
def test_case_pattern_id_exists_in_catalog(case: dict[str, Any]) -> None:
    assert case["pattern_id"] in CATALOG_IDS, (
        f"{case['id']}: pattern_id {case['pattern_id']!r} not found in pattern_catalog.yaml"
    )


@pytest.mark.parametrize("case", [c for c in CASES if c["mechanism"] == "verify_fragment"], ids=_id)
def test_verify_fragment_cases(case: dict[str, Any]) -> None:
    result = rr.verify_fragment(case["before"], case["candidate_example"])
    assert result.status == case["expected_status"], (
        f"{case['id']}: expected status {case['expected_status']!r}, got {result.status!r}"
    )


def _structural_signature_of(sql: str) -> dict[str, Any]:
    tree = parse_one(sql, read=DIALECT)
    return sql_parser.structural_signature(tree)


@pytest.mark.parametrize("case", [c for c in CASES if c["mechanism"] == "structural_signature_diff"], ids=_id)
def test_structural_signature_diff_cases(case: dict[str, Any]) -> None:
    before_sig = _structural_signature_of(case["before_sql"])
    candidate_sig = _structural_signature_of(case["candidate_sql"])
    assert before_sig, f"{case['id']}: before_sql produced an empty structural signature"
    assert candidate_sig, f"{case['id']}: candidate_sql produced an empty structural signature"

    are_equal = before_sig == candidate_sig
    assert are_equal == case["expect_equal"], (
        f"{case['id']}: expected signatures equal={case['expect_equal']}, got equal={are_equal}\n"
        f"before={before_sig}\ncandidate={candidate_sig}"
    )
    if not case["expect_equal"]:
        for field in case.get("diff_fields", []):
            assert before_sig.get(field) != candidate_sig.get(field), (
                f"{case['id']}: expected field {field!r} to differ but it did not "
                f"(before={before_sig.get(field)!r}, candidate={candidate_sig.get(field)!r})"
            )


@pytest.mark.parametrize("case", [c for c in CASES if c["mechanism"] == "complexity_flag_presence"], ids=_id)
def test_complexity_flag_presence_cases(case: dict[str, Any]) -> None:
    parsed = sql_parser.parse_sql_text(case["sql"])
    assert parsed.statements, f"{case['id']}: SQL failed to parse into any statement"
    flags = parsed.statements[0].complexity_flags

    if "expected_flag_present" in case:
        assert case["expected_flag_present"] in flags, (
            f"{case['id']}: expected flag {case['expected_flag_present']!r} in {flags}"
        )
    if "expected_flag_absent" in case:
        assert case["expected_flag_absent"] not in flags, (
            f"{case['id']}: expected flag {case['expected_flag_absent']!r} NOT in {flags}, got {flags}"
        )


_GATE_CASES = [c for c in CASES if "expected_candidate_forbidden_flag" in c]


@pytest.mark.parametrize("case", _GATE_CASES, ids=_id)
def test_candidate_gate_still_forbids_flag(case: dict[str, Any]) -> None:
    """The dataset claims this flag blocks full-rewrite candidates today.
    Lock that claim against app.yaml itself (PR #2 review item 6): removing
    the flag from config must fail here. Reads YAML only — no ai_service."""
    app_cfg = yaml.safe_load(APP_YAML_PATH.read_text(encoding="utf-8"))
    forbidden = app_cfg["ai_gate"]["candidate_forbidden_complexity_flags"]
    assert case["expected_candidate_forbidden_flag"] in forbidden, (
        f"{case['id']}: {case['expected_candidate_forbidden_flag']!r} is no longer in "
        f"app.yaml ai_gate.candidate_forbidden_complexity_flags {forbidden}"
    )


def test_correlated_subquery_trap_locks_the_candidate_gate() -> None:
    """Keep the gate assertion from disappearing silently with a dataset edit."""
    assert any(
        c["pattern_id"] == "CORRELATED_SUBQUERY_TO_JOIN_OR_WINDOW"
        and c.get("expected_candidate_forbidden_flag") == "correlated_subquery"
        for c in _GATE_CASES
    ), "the correlated-subquery trap must assert the app.yaml candidate gate"


def test_every_case_declares_forbidden_automatic_rewrite() -> None:
    """Phase 1 sanity check: every semantic-trap case must explicitly say the
    rewrite it describes must not be automatically applied — this dataset
    exists specifically to guard against silently blessing these."""
    for case in CASES:
        assert case.get("forbidden_automatic_rewrite") is True, (
            f"{case['id']}: semantic trap dataset entries must all set forbidden_automatic_rewrite: true"
        )


def test_all_six_required_semantic_traps_are_covered() -> None:
    """Phase-1 spec section 10 names six semantic traps that must be
    analyzed. This does not need every trap to use every case `kind` — just
    that each trap has at least one case here."""
    required_patterns = {
        "UPPER_CASE_FOLD_REMOVAL",
        "LEFT_JOIN_TO_INNER_JOIN",
        "OR_CROSS_COLUMN_TO_UNION_ALL",
        "NOT_IN_SUBQUERY_TO_NOT_EXISTS",
        "CORRELATED_SUBQUERY_TO_JOIN_OR_WINDOW",
        "DISTINCT_REMOVAL",
    }
    covered = {c["pattern_id"] for c in CASES}
    missing = required_patterns - covered
    assert not missing, f"missing semantic-trap coverage for: {missing}"
