from app.services.sql_parser import parse_sql_text


def _one(sql: str):
    result = parse_sql_text(sql)
    assert len(result.statements) == 1, f"expected 1 statement, got {len(result.statements)}"
    return result.statements[0]


# ---------------------------------------------------------------------------
# Basic parsing / table extraction
# ---------------------------------------------------------------------------
def test_basic_select_parses_ok_with_where():
    s = _one("SELECT A.X FROM T A WHERE A.X = 1")
    assert s.statement_type == "SELECT"
    assert s.parse_status == "ok"
    assert s.tables == {"T"}
    assert s.where_applicable is True
    assert s.has_where is True


def test_schema_qualified_table_drops_schema():
    s = _one("SELECT * FROM TAX.HOUT120 A WHERE A.X = 1")
    assert s.tables == {"HOUT120"}


def test_missing_where_is_detected():
    s = _one("SELECT * FROM T A")
    assert s.where_applicable is True
    assert s.has_where is False


def test_select_1_no_from_where_not_applicable():
    s = _one("SELECT 1")
    assert s.where_applicable is False
    assert s.has_where is None


def test_select_from_dual_where_not_applicable():
    s = _one("SELECT SYSDATE FROM DUAL")
    assert s.where_applicable is False
    assert s.has_where is None


def test_union_branch_without_where_marks_missing():
    s = _one("SELECT * FROM T A WHERE A.X=1 UNION SELECT * FROM T2 B")
    assert s.where_applicable is True
    assert s.has_where is False


def test_union_all_branches_with_where_passes():
    s = _one("SELECT * FROM T A WHERE A.X=1 UNION SELECT * FROM T2 B WHERE B.Y=2")
    assert s.has_where is True


def test_join_on_condition_populates_scope_not_where():
    # JOIN ON is not itself a WHERE clause; accept_join_on defaults to false
    # at the rule-engine layer, but sql_parser must report has_where based on
    # the statement's own WHERE arg only.
    s = _one("SELECT * FROM T A JOIN T2 B ON A.ID = B.ID")
    assert s.where_applicable is True
    assert s.has_where is False


# ---------------------------------------------------------------------------
# INSERT / MERGE applicability (PRD §14)
# ---------------------------------------------------------------------------
def test_insert_select_where_checked_on_inner_select():
    s = _one("INSERT INTO T (X) SELECT Y FROM T2 B WHERE B.Z = 1")
    assert s.statement_type == "INSERT"
    assert s.where_applicable is True
    assert s.has_where is True


def test_insert_select_missing_where_flagged():
    s = _one("INSERT INTO T (X) SELECT Y FROM T2 B")
    assert s.has_where is False


def test_insert_values_where_not_applicable():
    s = _one("INSERT INTO T (X, Y) VALUES (1, 2)")
    assert s.where_applicable is False
    assert s.has_where is None


def test_merge_where_not_applicable():
    s = _one(
        "MERGE INTO T A USING T2 B ON (A.ID=B.ID) WHEN MATCHED THEN UPDATE SET A.X=B.X"
    )
    assert s.statement_type == "MERGE"
    assert s.where_applicable is False
    assert s.parse_status == "ok"


def test_update_delete_where():
    s1 = _one("UPDATE T A SET A.X = 1 WHERE A.Y = 2")
    assert s1.where_applicable is True and s1.has_where is True
    s2 = _one("UPDATE T A SET A.X = 1")
    assert s2.has_where is False
    s3 = _one("DELETE FROM T A WHERE A.Y = 2")
    assert s3.has_where is True
    s4 = _one("DELETE FROM T A")
    assert s4.has_where is False


# ---------------------------------------------------------------------------
# Multi-statement splitting
# ---------------------------------------------------------------------------
def test_split_semicolon_inside_string_literal_is_safe():
    sql = "SELECT ';' AS X FROM DUAL; SELECT 2 FROM DUAL"
    result = parse_sql_text(sql)
    assert len(result.statements) == 2
    assert result.statements[0].statement_type == "SELECT"
    assert result.statements[1].statement_type == "SELECT"


def test_split_semicolon_inside_comment_is_safe():
    sql = "SELECT * FROM T A WHERE A.X=1; -- comment; still fine\nSELECT * FROM T2 B WHERE B.Y=2"
    result = parse_sql_text(sql)
    assert len(result.statements) == 2


def test_multi_statement_count_and_types():
    sql = "SELECT * FROM T WHERE X=1;\nUPDATE T SET X=1 WHERE Y=2;\nDELETE FROM T WHERE Z=3;"
    result = parse_sql_text(sql)
    assert [s.statement_type for s in result.statements] == ["SELECT", "UPDATE", "DELETE"]
    assert [s.index for s in result.statements] == [0, 1, 2]


# ---------------------------------------------------------------------------
# PL/SQL block isolation
# ---------------------------------------------------------------------------
def test_plsql_block_is_isolated_and_not_ast_parsed():
    sql = "DECLARE\n  X NUMBER;\nBEGIN\n  X := 1;\nEND;\n/\n"
    result = parse_sql_text(sql)
    assert len(result.statements) == 1
    assert result.statements[0].statement_type == "PLSQL"
    assert result.statements[0].parse_status == "failed"


def test_plsql_block_followed_by_real_sql():
    sql = (
        "DECLARE\n  X NUMBER;\nBEGIN\n  X := 1;\nEND;\n/\n"
        "SELECT * FROM T A WHERE A.X = 1"
    )
    result = parse_sql_text(sql)
    assert len(result.statements) == 2
    assert result.statements[0].statement_type == "PLSQL"
    assert result.statements[1].statement_type == "SELECT"
    assert result.statements[1].parse_status == "ok"


# ---------------------------------------------------------------------------
# SQL*Plus command stripping — including the UPDATE...SET false-positive guard
# ---------------------------------------------------------------------------
def test_sqlplus_preamble_is_stripped_before_parsing():
    sql = "SET LINESIZE 200\nSPOOL out.txt\nSELECT * FROM T A WHERE A.X = 1;\nSPOOL OFF"
    result = parse_sql_text(sql)
    assert len(result.statements) == 1
    assert result.statements[0].parse_status == "ok"
    assert "LINESIZE 200" in " ".join(result.sqlplus_commands)


def test_update_set_is_not_mistaken_for_sqlplus_set():
    sql = "UPDATE T A\nSET A.X = 1\nWHERE A.Y = 2"
    result = parse_sql_text(sql)
    assert len(result.statements) == 1
    s = result.statements[0]
    assert s.statement_type == "UPDATE"
    assert s.parse_status == "ok"
    assert s.has_where is True
    assert result.sqlplus_commands == []


# ---------------------------------------------------------------------------
# Parallel hint detection (token/text-level; see lessons.md)
# ---------------------------------------------------------------------------
def test_parallel_hint_on_select_detected():
    s = _one("SELECT /*+ PARALLEL(A, 4) */ A.X FROM T A WHERE A.X = 1")
    assert s.hint_evidence is not None
    assert "PARALLEL" in s.hint_evidence


def test_parallel_hint_on_update_detected():
    s = _one("UPDATE /*+ PARALLEL(A, 4) */ T A SET A.X = 1 WHERE A.Y = 2")
    assert s.hint_evidence is not None


def test_parallel_hint_line_style_detected():
    s = _one("SELECT --+ PARALLEL(A 4)\nA.X FROM T A WHERE A.Y = 2")
    assert s.hint_evidence is not None


def test_noparallel_is_not_flagged_as_parallel():
    s = _one("SELECT /*+ NOPARALLEL(A) */ A.X FROM T A WHERE A.Y = 2")
    assert s.hint_evidence is None


def test_parallel_index_hint_detected():
    s = _one("SELECT /*+ PARALLEL_INDEX(A, IDX1, 4) */ * FROM T A WHERE A.X=1")
    assert s.hint_evidence is not None


def test_hint_inside_string_literal_is_not_detected():
    s = _one("SELECT * FROM T A WHERE A.NOTE = '/*+ PARALLEL */' AND A.X=1")
    assert s.hint_evidence is None


def test_no_hint_present():
    s = _one("SELECT * FROM T A WHERE A.X = 1")
    assert s.hint_evidence is None


# ---------------------------------------------------------------------------
# Function-on-condition-column (R005) — the And/Or-is-Func regression guard
# ---------------------------------------------------------------------------
def test_trunc_on_column_is_flagged():
    s = _one("SELECT * FROM T A WHERE TRUNC(A.TXN_DATE) = :DATE_001")
    assert len(s.function_findings) == 1
    assert "TRUNC" in s.function_findings[0]


def test_trunc_sysdate_no_column_is_not_flagged():
    s = _one("SELECT * FROM T A WHERE A.STATUS = :S AND A.CREATED >= TRUNC(SYSDATE)")
    assert s.function_findings == []


def test_function_with_bind_arg_only_is_not_flagged():
    s = _one("SELECT * FROM T A WHERE A.AMT = ROUND(:X, 2)")
    assert s.function_findings == []


def test_and_or_are_never_reported_as_function_on_condition():
    s = _one("SELECT * FROM T A WHERE A.X = 1 AND A.Y = 2 OR A.Z = 3")
    assert s.function_findings == []


def test_function_on_both_sides_gives_two_findings():
    s = _one("SELECT * FROM T A WHERE TRUNC(A.D1) = TRUNC(A.D2)")
    assert len(s.function_findings) == 2


def test_upper_on_like_column_side_is_flagged():
    s = _one("SELECT * FROM T A WHERE UPPER(A.NAME) LIKE 'ABC%'")
    assert any("UPPER" in f for f in s.function_findings)


def test_function_in_select_list_does_not_trigger_r005():
    # R005 is about condition columns (WHERE/HAVING/ON), never the SELECT
    # list — TRUNC(A.TXN_DATE) as an output column is completely normal.
    s = _one("SELECT TRUNC(A.TXN_DATE) AS D FROM T A WHERE A.Y = 1")
    assert s.function_findings == []


def test_subquery_without_where_does_not_force_outer_missing_where():
    # PRD/plan assumption: R002 only evaluates the top-level statement (and
    # set-operation branches); an unfiltered subquery inside e.g. an IN(...)
    # must not make the OUTER statement look like it is missing a WHERE.
    s = _one("SELECT * FROM T A WHERE A.ID IN (SELECT B.ID FROM T2 B) AND A.X = 1")
    assert s.where_applicable is True
    assert s.has_where is True


# ---------------------------------------------------------------------------
# OR detection (R006)
# ---------------------------------------------------------------------------
def test_real_or_condition_detected():
    s = _one("SELECT * FROM T A WHERE A.X = 1 OR A.Y = 2")
    assert len(s.or_findings) == 1


def test_string_literal_containing_or_not_detected():
    s = _one("SELECT * FROM T A WHERE A.NOTE = 'A OR B'")
    assert s.or_findings == []


def test_comment_mentioning_or_not_detected():
    s = _one("-- avoid OR here\nSELECT * FROM T A WHERE A.X = 1")
    assert s.or_findings == []


# ---------------------------------------------------------------------------
# LIKE leading wildcard (R004)
# ---------------------------------------------------------------------------
def test_like_leading_percent_literal_detected():
    s = _one("SELECT * FROM T A WHERE A.NAME LIKE '%ABC'")
    assert len(s.like_findings) == 1


def test_like_trailing_percent_literal_not_detected():
    s = _one("SELECT * FROM T A WHERE A.NAME LIKE 'ABC%'")
    assert s.like_findings == []


def test_like_bind_variable_not_detected():
    s = _one("SELECT * FROM T A WHERE A.NAME LIKE :PATTERN")
    assert s.like_findings == []


def test_like_concat_leading_wildcard_detected():
    s = _one("SELECT * FROM T A WHERE A.NAME LIKE '%' || :PATTERN")
    assert len(s.like_findings) == 1


# ---------------------------------------------------------------------------
# Complexity flags (advisory; feeds improvement_score.py S component)
# ---------------------------------------------------------------------------
def test_outer_join_legacy_marker_flagged():
    s = _one("SELECT E.NAME FROM EMP E, EMP M WHERE E.MGR_ID = M.ID(+)")
    assert "outer_join" in s.complexity_flags


def test_select_star_flagged():
    s = _one("SELECT * FROM T A WHERE A.X=1")
    assert "select_star" in s.complexity_flags


def test_group_by_flagged():
    s = _one("SELECT A.X, COUNT(*) FROM T A WHERE A.Y=1 GROUP BY A.X")
    assert "group_by_aggregate" in s.complexity_flags


def test_distinct_flagged():
    s = _one("SELECT DISTINCT A.X FROM T A WHERE A.Y=1")
    assert "distinct" in s.complexity_flags


def test_rownum_flagged():
    s = _one("SELECT * FROM T A WHERE ROWNUM <= 10")
    assert "rownum" in s.complexity_flags


def test_clean_simple_select_has_no_complexity_flags_beyond_star():
    s = _one("SELECT A.X FROM T A WHERE A.Y = 1")
    assert s.complexity_flags == set()


# ---------------------------------------------------------------------------
# Parse failure handling
# ---------------------------------------------------------------------------
def test_garbage_sql_marks_failed_and_sets_parse_message():
    result = parse_sql_text("SELEKT * FRM T")
    assert len(result.statements) == 1
    assert result.statements[0].parse_status == "failed"
    assert result.parse_message is not None


def test_empty_after_sqlplus_strip_sets_parse_message():
    result = parse_sql_text("SPOOL out.txt\nSPOOL OFF")
    assert result.statements == []
    assert result.parse_message is not None


def test_valid_sql_has_no_parse_message():
    result = parse_sql_text("SELECT * FROM T A WHERE A.X = 1")
    assert result.parse_message is None


def test_parse_failure_still_detects_hint_and_cost_relevant_tables():
    # Even when AST parsing fails, token-level hint detection and best-effort
    # table extraction should still work (PRD: token 層判定，parse 失敗仍可判).
    result = parse_sql_text("SELEKT /*+ PARALLEL(A,4) */ * FRM T A WHERE A.X=1")
    s = result.statements[0]
    assert s.parse_status == "failed"
    assert s.hint_evidence is not None
