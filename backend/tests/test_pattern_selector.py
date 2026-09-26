from app.schemas import Finding
from app.services.pattern_selector import (
    SUPPORTED_EXACT_SOURCES,
    PatternMatch,
    PatternSelection,
    _catalog_patterns,
    select_patterns,
)
from app.services.sql_parser import parse_sql_text


def _parsed(sql: str):
    return parse_sql_text(sql).statements


def _finding(rule_id: str, index: int = 0) -> Finding:
    return Finding(rule_id=rule_id, status="NOTICE", fact="synthetic", statement_index=index)


def _rules(threshold: int = 4) -> dict:
    return {"improvement_score": {"structure": {"many_tables_threshold": threshold}}}


def test_selector_supports_every_deterministic_catalog_source():
    deterministic_sources = {
        (p.get("detection") or {}).get("source")
        for p in _catalog_patterns()
        if (p.get("detection") or {}).get("source") not in {"none", "prompt_heuristic_only"}
    }
    assert deterministic_sources <= SUPPORTED_EXACT_SOURCES


def test_clean_sql_selects_nothing():
    selection = select_patterns(_parsed("SELECT A.X FROM T A WHERE A.X = 1"), [], _rules())
    assert selection.exact_ids == ()
    assert selection.family_signal_ids == ()


def test_rewrite_rules_produce_exact_matches_without_using_rule_family_as_proof():
    sql = "SELECT A.X FROM T A WHERE SUBSTR(A.C,1,3)='107' AND (A.Y=1 OR A.Y=2)"
    selection = select_patterns(_parsed(sql), [_finding("R005"), _finding("R006")], _rules())
    assert "SUBSTR_EQ_TO_LIKE" in selection.exact_ids
    assert "OR_SAME_COLUMN_TO_IN" in selection.exact_ids
    # Broad R005/R006 signals remain explicitly ambiguous; they are never
    # promoted into future context candidates merely because the rule fired.
    assert selection.context_candidate_ids == selection.exact_ids
    assert "OR_CROSS_COLUMN_TO_UNION_ALL" in selection.family_signal_ids


def test_or_over_oracle_limit_is_not_an_exact_verified_pattern():
    chain = " OR ".join(f"A.C = {i}" for i in range(1, 1002))
    selection = select_patterns(_parsed(f"SELECT A.X FROM T A WHERE {chain}"), [_finding("R006")], _rules())
    assert "OR_SAME_COLUMN_TO_IN" not in selection.exact_ids
    assert "OR_SAME_COLUMN_TO_IN" in selection.family_signal_ids


def test_rule_engine_exact_sources_select_leading_wildcard_and_important_table():
    statements = _parsed("SELECT A.X FROM WIIT001 A WHERE A.N LIKE '%ABC'")
    selection = select_patterns(statements, [_finding("R004"), _finding("R007")], _rules())
    assert "LEADING_WILDCARD_LIKE" in selection.exact_ids
    assert "IMPORTANT_TABLE_USAGE" in selection.exact_ids


def test_complexity_flags_select_exact_catalog_patterns():
    cases = [
        ("SELECT A.X FROM T A WHERE A.K NOT IN (SELECT B.K FROM U B)", "NOT_IN_SUBQUERY_TO_NOT_EXISTS"),
        (
            "SELECT A.X FROM T A WHERE EXISTS (SELECT 1 FROM U B WHERE B.K = A.K)",
            "CORRELATED_SUBQUERY_TO_JOIN_OR_WINDOW",
        ),
        ("SELECT DISTINCT A.X FROM T A WHERE A.X=1", "DISTINCT_REMOVAL"),
        ("SELECT A.X FROM T A, U B WHERE A.X=1", "CARTESIAN_JOIN_MISSING_CONDITION"),
        ("SELECT * FROM T A WHERE A.X=1", "SELECT_STAR"),
    ]
    for sql, expected in cases:
        selection = select_patterns(_parsed(sql), [], _rules())
        assert expected in selection.exact_ids, (sql, selection.exact_ids)


def test_real_tax_specific_flags_select_exact_advice_patterns():
    cases = [
        (
            "SELECT A.X FROM T A WHERE A.STATUS='1' OR A.CLOSE_DATE >= '1150101'",
            "OR_CROSS_COLUMN_TO_UNION_ALL",
        ),
        (
            "SELECT A.X FROM T A WHERE A.TAX_CD || A.SUBTAX_CD = '551'",
            "STRING_CONCAT_PREDICATE_SPLIT",
        ),
        (
            "SELECT A.X FROM T A JOIN U B "
            "ON SUBSTR(A.MANAGE_KEY,1,2)=B.DISTRICT_CD WHERE A.STATUS='1'",
            "COMPOSITE_KEY_EXPRESSION_JOIN",
        ),
        (
            "SELECT A.X FROM T A JOIN H B ON B.ID=A.ID "
            "WHERE B.UPDATE_DATE=(SELECT MAX(H1.UPDATE_DATE) FROM H H1 WHERE H1.ID=A.ID) "
            "AND B.UPDATE_TIME=(SELECT MAX(H2.UPDATE_TIME) FROM H H2 WHERE H2.ID=A.ID)",
            "LATEST_ROW_CORRELATED_MAX",
        ),
        (
            "SELECT A.X, "
            "(SELECT COUNT(*) FROM D D1 WHERE D1.ID=A.ID AND D1.KIND='A') C1, "
            "(SELECT COUNT(*) FROM D D2 WHERE D2.ID=A.ID AND D2.KIND='B') C2 "
            "FROM T A WHERE A.STATUS='1'",
            "REPEATED_SCALAR_AGGREGATE",
        ),
        (
            "SELECT A.AREA_CD FROM T A WHERE A.STATUS='1' "
            "UNION ALL SELECT B.AREA_CD FROM T B WHERE B.STATUS='2'",
            "REPEATED_SOURCE_UNION_BRANCH",
        ),
    ]
    for sql, expected in cases:
        selection = select_patterns(_parsed(sql), [], _rules())
        assert expected in selection.exact_ids, (sql, selection.exact_ids)
        matched = next(item for item in selection.exact if item.pattern_id == expected)
        assert matched.classification == "ADVICE_ONLY"


def test_cross_column_or_is_exact_only_when_ast_confirms_different_columns():
    same_column = select_patterns(
        _parsed("SELECT A.X FROM T A WHERE A.STATUS='1' OR A.STATUS='2'"),
        [_finding("R006")],
        _rules(),
    )
    assert "OR_CROSS_COLUMN_TO_UNION_ALL" not in same_column.exact_ids
    assert "OR_CROSS_COLUMN_TO_UNION_ALL" in same_column.family_signal_ids

    cross_column = select_patterns(
        _parsed("SELECT A.X FROM T A WHERE A.STATUS='1' OR A.CLOSE_DATE >= '1150101'"),
        [_finding("R006")],
        _rules(),
    )
    assert "OR_CROSS_COLUMN_TO_UNION_ALL" in cross_column.exact_ids
    assert "OR_CROSS_COLUMN_TO_UNION_ALL" not in cross_column.family_signal_ids


def test_many_tables_uses_same_threshold_contract_as_improvement_score():
    sql = (
        "SELECT A.X FROM T1 A "
        "JOIN T2 B ON B.K=A.K JOIN T3 C ON C.K=A.K JOIN T4 D ON D.K=A.K "
        "WHERE A.X=1"
    )
    assert "STRUCTURAL_COMPLEXITY_MANY_TABLES" in select_patterns(_parsed(sql), [], _rules(4)).exact_ids
    assert "STRUCTURAL_COMPLEXITY_MANY_TABLES" not in select_patterns(_parsed(sql), [], _rules(5)).exact_ids


def test_family_signals_stay_separate_from_exact_matches():
    function_selection = select_patterns(
        _parsed("SELECT A.X FROM T A WHERE UPPER(A.N)='ABC'"), [_finding("R005")], _rules()
    )
    assert "UPPER_CASE_FOLD_REMOVAL" not in function_selection.exact_ids
    assert "UPPER_CASE_FOLD_REMOVAL" in function_selection.family_signal_ids
    assert "PREDICATE_FUNCTION_GENERIC" in function_selection.family_signal_ids

    outer = select_patterns(
        _parsed("SELECT A.X FROM T A LEFT JOIN U B ON B.K=A.K WHERE A.X=1"), [], _rules()
    )
    assert "LEFT_JOIN_TO_INNER_JOIN" not in outer.exact_ids
    assert "LEFT_JOIN_TO_INNER_JOIN" in outer.family_signal_ids

    grouped = select_patterns(_parsed("SELECT A.X, COUNT(*) FROM T A GROUP BY A.X"), [], _rules())
    assert "GROUP_BY_STRUCTURAL_REWRITE" not in grouped.exact_ids
    assert "GROUP_BY_STRUCTURAL_REWRITE" in grouped.family_signal_ids


def test_none_and_out_of_scope_patterns_are_never_selected_without_a_detector():
    selection = select_patterns(_parsed("SELECT A.X FROM T A WHERE A.X=1"), [], _rules())
    forbidden = {
        "IN_SUBQUERY_TO_EXISTS",
        "LARGE_RESULT_SET_NO_LIMIT",
        "INDEX_ADVISORY",
        "EXECUTION_PLAN_CLAIM",
        "FULL_TABLE_SCAN_CLAIM",
        "CARDINALITY_SELECTIVITY_DISTRIBUTION",
        "ACTUAL_RUNTIME_IMPROVEMENT_CLAIM",
        "POST_REWRITE_ORACLE_COST_CLAIM",
        "PARTITION_RECOMMENDATION",
        "PHYSICAL_STORAGE_AND_HOST_TUNING",
    }
    assert forbidden.isdisjoint(selection.exact_ids)
    assert forbidden.isdisjoint(selection.family_signal_ids)


def test_exact_match_order_follows_catalog_order():
    sql = (
        "SELECT * FROM T A WHERE SUBSTR(A.C,1,3)='107' "
        "AND (A.Y=1 OR A.Y=2) AND A.N LIKE '%ABC'"
    )
    selection = select_patterns(
        _parsed(sql), [_finding("R005"), _finding("R006"), _finding("R004")], _rules()
    )
    ids = selection.exact_ids
    assert ids.index("SUBSTR_EQ_TO_LIKE") < ids.index("OR_SAME_COLUMN_TO_IN")
    assert ids.index("OR_SAME_COLUMN_TO_IN") < ids.index("LEADING_WILDCARD_LIKE")
    assert ids.index("LEADING_WILDCARD_LIKE") < ids.index("SELECT_STAR")


def test_log_fields_are_sql_free_and_context_candidates_are_exact_only():
    secret = "SECRET_LITERAL_9487"
    statements = _parsed(f"SELECT A.X FROM TAX_PRIVATE A WHERE SUBSTR(A.C,1,3)='107' AND A.N='{secret}'")
    selection = select_patterns(statements, [_finding("R005")], _rules())
    blob = repr(selection.log_fields())
    assert secret not in blob
    assert "TAX_PRIVATE" not in blob
    assert selection.context_candidate_ids == selection.exact_ids


def test_out_of_scope_exact_match_can_never_become_context_candidate():
    selection = PatternSelection(
        exact=(
            PatternMatch(
                pattern_id="INDEX_ADVISORY",
                classification="OUT_OF_SCOPE",
                match_kind="exact",
                statement_indexes=(0,),
                signals=("synthetic:test",),
            ),
            PatternMatch(
                pattern_id="SELECT_STAR",
                classification="INFORMATIONAL",
                match_kind="exact",
                statement_indexes=(0,),
                signals=("flag:select_star",),
            ),
        )
    )
    assert selection.exact_ids == ("INDEX_ADVISORY", "SELECT_STAR")
    assert selection.context_candidate_ids == ("SELECT_STAR",)

def test_direct_predicate_functions_are_exact_patterns_but_nested_aggregate_nvl_is_not():
    direct_cases = [
        ("SELECT A.X FROM T A WHERE NVL(A.FLAG,'N')='N'", "NVL_EQ_TO_OR_IS_NULL"),
        ("SELECT A.X FROM T A WHERE TRUNC(A.TXN_DATE)=:D", "TRUNC_EQ_TO_RANGE"),
        ("SELECT A.X FROM T A WHERE TO_CHAR(A.TXN_DATE,'YYYY')=:Y", "TO_CHAR_CONDITION_PREDICATE"),
        ("SELECT A.X FROM T A WHERE UPPER(A.STATUS)=:S", "UPPER_CASE_FOLD_REMOVAL"),
    ]
    for sql, pattern_id in direct_cases:
        parsed = _parsed(sql)
        selection = select_patterns(parsed, [_finding("R005")], _rules())
        assert pattern_id in selection.exact_ids, (sql, selection.exact_ids)

    aggregate_sql = (
        "SELECT A.CASE_NO, SUM(NVL(P.AMT,0)) TOTAL "
        "FROM TAX_CASE A JOIN TAX_PAYMENT P ON P.CASE_NO=A.CASE_NO "
        "WHERE A.STATUS='A' GROUP BY A.CASE_NO "
        "HAVING SUM(NVL(P.AMT,0)) > 0"
    )
    parsed = _parsed(aggregate_sql)
    selection = select_patterns(parsed, [], _rules())
    assert "NVL_EQ_TO_OR_IS_NULL" not in selection.exact_ids
    assert "nvl_condition_predicate" not in parsed[0].complexity_flags
