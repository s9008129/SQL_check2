"""2026-09-17: the system, not the model, is the authority on predicate
equivalence. These tests pin every rule's equivalence argument and the
production case that motivated the module."""

import pytest
from sqlglot import parse_one

from app.services import rewrite_rules as rr


def _v(before: str, example: str) -> rr.FragmentVerification:
    return rr.verify_fragment(before, example)


# --- the production bug ----------------------------------------------------
def test_mid_string_substr_wrong_like_is_corrected():
    v = _v("SUBSTR(MANAGE_CD, 6, 3) = '551'", "T2.MANAGE_CD LIKE '__%551%'")
    assert v.status == "corrected"
    assert v.example == "MANAGE_CD LIKE '_____551%'"
    assert v.rule == "substr_eq_to_like"


def test_mid_string_substr_correct_like_is_verified():
    v = _v("SUBSTR(MANAGE_CD, 6, 3) = '551'", "manage_cd like '_____551%'")
    assert v.status == "verified"


# --- SUBSTR prefix ---------------------------------------------------------
def test_prefix_substr_canonical_like_is_verified():
    assert _v("substr(w.coll_b_date, 1, 3) = '107'", "w.coll_b_date LIKE '107%'").status == "verified"


def test_prefix_substr_range_bounds_are_not_verified():
    # 2026-09-18: the p=1 prefix-range form depends on collation, which
    # SQLCheck cannot see. It is never accepted as written; the system
    # replaces it with its own canonical LIKE (the proven form).
    v = _v("substr(w.coll_b_date, 1, 3) = '107'", "w.coll_b_date >= '107' AND w.coll_b_date < '108'")
    assert v.status == "corrected"
    assert v.example == "w.coll_b_date LIKE '107%'"


def test_prefix_substr_wrong_bounds_corrected_to_like():
    v = _v("substr(w.coll_b_date, 1, 3) = '107'", "w.coll_b_date >= '1070101' AND w.coll_b_date < '1080101'")
    assert v.status == "corrected"
    assert v.example == "w.coll_b_date LIKE '107%'"


def test_full_rewrite_with_prefix_range_bounds_is_rejected():
    o, s = _trees(
        "SELECT A.X FROM T A WHERE SUBSTR(A.C, 1, 3) = '107'",
        "SELECT A.X FROM T A WHERE A.C >= '107' AND A.C < '108'",
    )
    ok, why = rr.verify_predicate_changes(o, s)
    assert ok is False and why


def test_substr_length_mismatch_is_not_rewritable():
    # SUBSTR of length 3 can never equal a 2-char literal: no rule, unverified.
    assert _v("SUBSTR(A.C, 1, 3) = '10'", "A.C LIKE '10%'").status == "unverified"


def test_substr_literal_longer_than_length_is_not_rewritable():
    assert _v("SUBSTR(A.C, 1, 2) = '107'", "A.C LIKE '107%'").status == "unverified"


def test_substr_value_with_wildcard_is_not_rewritable():
    assert _v("SUBSTR(A.C, 1, 2) = '1_'", "A.C LIKE '1_%'").status == "unverified"


def test_substr_value_with_percent_is_not_rewritable():
    assert _v("SUBSTR(A.C, 1, 2) = '1%'", "A.C LIKE '1%%'").status == "unverified"


def test_substr_value_with_quote_yields_valid_escaped_like():
    # The canonical text must stay valid SQL when v contains a quote; the
    # model's correctly escaped LIKE is verified, anything else is corrected
    # to the escaped form (previously the system emitted `LIKE 'O'B%'`).
    assert _v("SUBSTR(A.C, 1, 3) = 'O''B'", "A.C LIKE 'O''B%'").status == "verified"
    v = _v("SUBSTR(A.C, 1, 3) = 'O''B'", "A.C = 'x'")
    assert v.status == "corrected"
    assert v.example == "A.C LIKE 'O''B%'"
    assert rr.parse_predicate(v.example) is not None


# --- TRUNC: never server-proven (2026-09-18 Runtime Correctness v1) --------
# TRUNC(col)=X ⇔ col>=X AND col<X+1 needs X to carry no time component AND
# col to be a DATE (for a NUMBER col TRUNC truncates toward zero, so
# TRUNC(n)=0 is -1<n<1, not 0<=n<1). Neither is visible in SQL text, so no
# RHS shape — bind, expression or literal — may be verified or corrected.
def test_trunc_eq_range_with_unknown_bind_is_not_verified():
    v = _v("TRUNC(A.TXN_DATE) = :D", "A.TXN_DATE >= :D AND A.TXN_DATE < :D + 1")
    assert v.status == "unverified"
    assert v.example == "A.TXN_DATE >= :D AND A.TXN_DATE < :D + 1"
    assert v.assumption is None


def test_trunc_eq_is_never_corrected_by_the_system():
    # Previously the system replaced this with its own range as "corrected".
    v = _v("TRUNC(A.TXN_DATE) = :D", "A.TXN_DATE BETWEEN :D AND :D + 1")
    assert v.status == "unverified"
    assert v.example == "A.TXN_DATE BETWEEN :D AND :D + 1"


def test_trunc_eq_with_generic_expression_rhs_is_not_verified():
    assert _v("TRUNC(A.D) = SYSDATE - 1", "A.D >= SYSDATE - 1 AND A.D < SYSDATE").status == "unverified"
    assert _v("TRUNC(A.D) = B.D", "A.D >= B.D AND A.D < B.D + 1").status == "unverified"


def test_trunc_eq_with_literal_that_may_carry_time_is_not_verified():
    before = "TRUNC(A.D) = TO_DATE('2026-09-18 10:00', 'YYYY-MM-DD HH24:MI')"
    example = (
        "A.D >= TO_DATE('2026-09-18 10:00', 'YYYY-MM-DD HH24:MI') "
        "AND A.D < TO_DATE('2026-09-18 10:00', 'YYYY-MM-DD HH24:MI') + 1"
    )
    assert _v(before, example).status == "unverified"


def test_trunc_eq_with_time_free_date_literal_is_still_not_verified():
    # Boundary: the RHS provably has no time, but the column type is unknown.
    v = _v("TRUNC(A.D) = DATE '2026-09-18'", "A.D >= DATE '2026-09-18' AND A.D < DATE '2026-09-18' + 1")
    assert v.status == "unverified"


def test_trunc_eq_with_numeric_rhs_is_not_verified():
    assert _v("TRUNC(A.N) = 0", "A.N >= 0 AND A.N < 0 + 1").status == "unverified"


# --- NVL: never server-proven (CHAR blank-padded vs VARCHAR2 nonpadded) ----
def test_nvl_same_default_is_not_verified():
    v = _v("NVL(A.S, 'N') = 'N'", "(A.S = 'N' OR A.S IS NULL)")
    assert v.status == "unverified"


def test_nvl_other_value_is_never_corrected_by_the_system():
    # Previously the system replaced the model's text with "A.S = 'Y'".
    v = _v("NVL(A.S, 'N') = 'Y'", "A.S = 'Y' OR A.S IS NULL")
    assert v.status == "unverified"
    assert v.example == "A.S = 'Y' OR A.S IS NULL"


def test_nvl_plain_comparison_is_not_verified():
    assert _v("NVL(A.S, 'x') = 'b'", "A.S = 'b'").status == "unverified"


# --- OR → IN ---------------------------------------------------------------
def test_or_chain_same_column_becomes_in():
    assert _v("A.C = '1' OR A.C = '2' OR A.C = '3'", "A.C IN ('1', '2', '3')").status == "verified"


def test_or_chain_different_columns_not_rewritable():
    assert _v("A.C = '1' OR A.D = '2'", "A.C IN ('1','2')").status == "unverified"


# --- things the system must NOT bless --------------------------------------
def test_upper_removal_is_unverified():
    assert _v("UPPER(A.NAME) = :N", "A.NAME = :N").status == "unverified"


def test_prose_before_is_unverified():
    assert _v("請確認查詢範圍", "A.X = 1").status == "unverified"


def test_multi_conjunct_before_each_part_checked():
    before = "SUBSTR(A.C, 1, 3) = '107' AND A.S = '1'"
    ok = "A.C LIKE '107%' AND A.S = '1'"
    assert _v(before, ok).status == "verified"
    # dropping the untouched conjunct is not equivalent
    assert _v(before, "A.C LIKE '107%'").status == "corrected"


def test_multi_conjunct_unproven_part_must_stay_unchanged():
    # SUBSTR is proven, TRUNC is not: the system's own correction keeps the
    # TRUNC conjunct exactly as written instead of rewriting it.
    before = "SUBSTR(A.C, 1, 3) = '107' AND TRUNC(A.D) = :X"
    v = _v(before, "A.C LIKE '107%' AND A.D >= :X AND A.D < :X + 1")
    assert v.status == "corrected"
    assert v.example == "A.C LIKE '107%' AND TRUNC(A.D) = :X"


# --- large AND robustness -------------------------------------------------
def _and_chain(n: int, *, start: int = 1) -> str:
    return " AND ".join(f"A.C{i} = {i}" for i in range(start, start + n))


def test_conjuncts_large_and_chain_is_iterative_and_keeps_source_order():
    # Regression: recursive _conjuncts failed around Python's recursion limit.
    expr = rr.parse_predicate(_and_chain(3000))
    conjuncts = rr._conjuncts(expr)
    assert len(conjuncts) == 3000
    assert conjuncts[0].sql(dialect="oracle") == "A.C1 = 1"
    assert conjuncts[-1].sql(dialect="oracle") == "A.C3000 = 3000"


def test_atoms_large_and_statement_is_iterative():
    tree = parse_one(f"SELECT A.X FROM T A WHERE {_and_chain(3000)}", read="oracle")
    atoms = rr._atoms(tree)
    assert len(atoms) == 3000
    assert atoms[0].sql(dialect="oracle") == "A.C1 = 1"
    assert atoms[-1].sql(dialect="oracle") == "A.C3000 = 3000"


def test_full_rewrite_large_unchanged_and_chain_does_not_fail_closed():
    sql = f"SELECT A.X FROM T A WHERE {_and_chain(1500)}"
    original, suggested = _trees(sql, sql)
    assert rr.verify_predicate_changes(original, suggested) == (True, None)


# --- full rewrite predicate check ------------------------------------------
def _trees(orig: str, sugg: str):
    return parse_one(orig, read="oracle"), parse_one(sugg, read="oracle")


def test_full_rewrite_with_rule_derived_change_ok():
    o, s = _trees(
        "SELECT A.X FROM T A WHERE SUBSTR(A.C, 1, 3) = '107' AND A.S = '1'",
        "SELECT A.X FROM T A WHERE A.C LIKE '107%' AND A.S = '1'",
    )
    assert rr.verify_predicate_changes(o, s) == (True, None)


def test_full_rewrite_changing_trunc_to_range_is_rejected():
    o, s = _trees(
        "SELECT A.X FROM T A WHERE TRUNC(A.D) = :X AND A.S = '1'",
        "SELECT A.X FROM T A WHERE A.D >= :X AND A.D < :X + 1 AND A.S = '1'",
    )
    ok, why = rr.verify_predicate_changes(o, s)
    assert ok is False and why == rr.REASON_UNVERIFIABLE_CHANGE


def test_full_rewrite_changing_nvl_is_rejected():
    o, s = _trees(
        "SELECT A.X FROM T A WHERE NVL(A.S, 'N') = 'N'",
        "SELECT A.X FROM T A WHERE (A.S = 'N' OR A.S IS NULL)",
    )
    ok, why = rr.verify_predicate_changes(o, s)
    assert ok is False and why == rr.REASON_UNVERIFIABLE_CHANGE


def test_full_rewrite_with_unprovable_change_rejected():
    o, s = _trees(
        "SELECT A.X FROM T A WHERE UPPER(A.N) = :N",
        "SELECT A.X FROM T A WHERE A.N = :N",
    )
    ok, why = rr.verify_predicate_changes(o, s)
    assert ok is False and why


def test_full_rewrite_with_wrong_substr_like_rejected():
    o, s = _trees(
        "SELECT A.X FROM T A WHERE SUBSTR(A.C, 6, 3) = '551'",
        "SELECT A.X FROM T A WHERE A.C LIKE '__%551%'",
    )
    ok, _ = rr.verify_predicate_changes(o, s)
    assert ok is False


def test_full_rewrite_adding_condition_rejected():
    o, s = _trees("SELECT A.X FROM T A WHERE A.Y = 1", "SELECT A.X FROM T A WHERE A.Y = 1 AND A.Z = 2")
    assert rr.verify_predicate_changes(o, s)[0] is False


def test_full_rewrite_reordering_conditions_ok():
    o, s = _trees("SELECT A.X FROM T A WHERE A.Y = 1 AND A.Z = 2", "SELECT A.X FROM T A WHERE A.Z = 2 AND A.Y = 1")
    assert rr.verify_predicate_changes(o, s) == (True, None)


# --- OR → IN: Oracle 19c 1000-expression boundary (2026-09-18) -------------
# One IN list holds at most 1000 expressions, so only 2..1000 same-column
# equality terms may become IN. Longer chains are refused by an explicit
# count guard, never by a crash, and the OR flattening is iterative so the
# default recursion limit is irrelevant (it used to fail at ~997 terms).
def _or_chain(n: int, col: str = "A.C") -> str:
    return " OR ".join(f"{col} = {i}" for i in range(1, n + 1))


def _in_list(n: int, col: str = "A.C") -> str:
    return f"{col} IN ({', '.join(str(i) for i in range(1, n + 1))})"


@pytest.mark.parametrize("n", [2, 10, 999, 1000])
def test_or_to_in_within_oracle_limit_is_derived_and_verified(n):
    rw = rr._rule_or_eq_to_in(rr.parse_predicate(_or_chain(n)))
    assert rw is not None and rw.rule == "or_eq_to_in"
    assert rw.canonical.count(",") + 1 == n
    assert _v(_or_chain(n), _in_list(n)).status == "verified"


@pytest.mark.parametrize("n", [1001, 1500, 3000])
def test_or_to_in_over_oracle_limit_is_refused_by_the_guard_not_a_crash(n):
    atom = rr.parse_predicate(_or_chain(n))
    assert rr._rule_or_eq_to_in(atom) is None  # called directly: no exception to swallow
    assert rr.derive(atom) is None
    v = _v(_or_chain(n), _in_list(n))
    assert v.status == "unverified"
    assert v.example == _in_list(n)


def test_or_to_in_limit_matches_oracle_19c_documentation():
    assert rr.ORACLE_IN_LIST_MAX_EXPRESSIONS == 1000


def test_flatten_or_is_iterative_and_keeps_source_order():
    # 5000 terms at the default recursion limit: a recursive flatten raised
    # RecursionError at ~997.
    disjuncts = rr._flatten_or(rr.parse_predicate(_or_chain(5000)))
    assert len(disjuncts) == 5000
    assert [d.expression.sql() for d in disjuncts[:3]] == ["1", "2", "3"]
    assert disjuncts[-1].expression.sql() == "5000"


def test_or_to_in_keeps_value_order():
    rw = rr.derive(rr.parse_predicate("A.C = 3 OR A.C = 1 OR A.C = 2"))
    assert rw is not None and rw.canonical == "A.C IN (3, 1, 2)"


@pytest.mark.parametrize(
    "predicate",
    [
        "A.C = 1 OR A.D = 2",  # cross-column
        "A.C = 1 OR A.C > 2",  # mixed operator
        "A.C = 1 OR A.C IN (2, 3)",
        "A.C = 1 OR A.C IS NULL",
        "A.C = 1 OR A.C LIKE '2%'",
        "A.C <> 1 OR A.C <> 2",  # non-equality
        "A.C >= 1 OR A.C >= 2",
        "A.C = B.D OR A.C = 1",  # column on the right-hand side
        "NOT A.C = 1 OR A.C = 2",
        "A.C = 1 OR (A.C = 2 AND A.D = 3)",  # nested parentheses hiding an AND
        "(A.C = 1 OR A.D = 2) OR A.C = 3",  # nested parentheses hiding another column
    ],
)
def test_or_chains_that_are_not_same_column_equality_are_never_rewritten(predicate):
    assert rr.derive(rr.parse_predicate(predicate)) is None


def test_or_chain_grouped_only_by_parentheses_is_still_same_column():
    # Parentheses that only group same-column equality terms change nothing.
    rw = rr.derive(rr.parse_predicate("(A.C = 1 OR A.C = 2) OR A.C = 3"))
    assert rw is not None and rw.canonical == "A.C IN (1, 2, 3)"


def test_full_rewrite_with_in_list_over_oracle_limit_is_rejected():
    o, s = _trees(f"SELECT A.X FROM T A WHERE {_or_chain(1001)}", f"SELECT A.X FROM T A WHERE {_in_list(1001)}")
    ok, why = rr.verify_predicate_changes(o, s)
    assert ok is False and why == rr.REASON_UNVERIFIABLE_CHANGE


def test_full_rewrite_with_in_list_at_oracle_limit_is_accepted():
    o, s = _trees(f"SELECT A.X FROM T A WHERE {_or_chain(1000)}", f"SELECT A.X FROM T A WHERE {_in_list(1000)}")
    assert rr.verify_predicate_changes(o, s) == (True, None)



def test_or_to_in_fragment_with_where_wrapper_is_verified():
    v = _v("WHERE A.C = '1' OR A.C = '2'", "WHERE A.C IN ('1', '2')")
    assert v.status == "verified"


def test_or_to_in_fragment_with_on_wrapper_is_verified():
    v = _v("ON A.C = '1' OR A.C = '2'", "ON A.C IN ('1', '2')")
    assert v.status == "verified"
