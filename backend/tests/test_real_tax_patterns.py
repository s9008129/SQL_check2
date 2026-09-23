from pathlib import Path

import yaml

from app.services.pattern_selector import select_patterns
from app.services.rewrite_rules import find_verified_rewrites
from app.services.sql_parser import parse_sql_text

_CASES_PATH = Path(__file__).parent / "knowledge" / "real_tax_patterns.yaml"


def _rules() -> dict:
    return {"improvement_score": {"structure": {"many_tables_threshold": 4}}}


def _load_cases() -> list[dict]:
    data = yaml.safe_load(_CASES_PATH.read_text(encoding="utf-8"))
    return list(data["cases"])


def test_real_tax_pattern_cases_are_synthetic_and_deidentified():
    raw = _CASES_PATH.read_text(encoding="utf-8").upper()
    forbidden = ("IDN_BAN", "LND_LOSN", "MANAGE_CD", "UPDATE_USER_ID", "Q67A.")
    assert not any(token in raw for token in forbidden)


def test_real_tax_patterns_match_expected_deterministic_evidence():
    for case in _load_cases():
        parsed = parse_sql_text(case["sql"])
        assert len(parsed.statements) == 1, case["id"]
        statement = parsed.statements[0]
        assert statement.parse_status == "ok", case["id"]

        for flag in case["expected_flags"]:
            assert flag in statement.complexity_flags, (case["id"], statement.complexity_flags)

        selection = select_patterns(parsed.statements, [], _rules())
        for pattern_id in case["expected_exact_patterns"]:
            assert pattern_id in selection.exact_ids, (case["id"], selection.exact_ids)

        verified = find_verified_rewrites(statement.raw_sql)
        assert [candidate.rule for candidate in verified] == case["expected_verified_rules"], case["id"]


def test_advice_only_real_tax_patterns_never_create_verified_diff():
    advice_only_ids = {
        "cross_column_or",
        "string_concat_predicate",
        "composite_key_expression_join",
        "latest_row_correlated_max",
        "repeated_scalar_aggregate",
        "repeated_source_union_branch",
    }
    for case in _load_cases():
        if case["id"] not in advice_only_ids:
            continue
        statement = parse_sql_text(case["sql"]).statements[0]
        assert find_verified_rewrites(statement.raw_sql) == [], case["id"]


def test_latest_row_pattern_requires_repetition_not_one_max_subquery():
    sql = """
    SELECT A.CASE_ID
    FROM TAX_CASE A
    WHERE A.UPDATE_DATE = (
      SELECT MAX(H.UPDATE_DATE)
      FROM TAX_HISTORY H
      WHERE H.CASE_ID = A.CASE_ID
    )
    """
    statement = parse_sql_text(sql).statements[0]
    assert "repeated_correlated_max_subquery" not in statement.complexity_flags


def test_repeated_source_pattern_does_not_treat_different_tables_as_same_source():
    sql = """
    SELECT A.AREA_CD FROM TAX_CASE_A A WHERE A.STATUS='1'
    UNION ALL
    SELECT B.AREA_CD FROM TAX_CASE_B B WHERE B.STATUS='1'
    """
    statement = parse_sql_text(sql).statements[0]
    assert "repeated_source_set_operation" not in statement.complexity_flags
