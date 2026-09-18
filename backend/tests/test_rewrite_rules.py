"""2026-09-17: the system, not the model, is the authority on predicate
equivalence. These tests pin every rule's equivalence argument and the
production case that motivated the module."""

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
def test_prefix_substr_like_and_bounds_both_verified():
    assert _v("substr(w.coll_b_date, 1, 3) = '107'", "w.coll_b_date LIKE '107%'").status == "verified"
    assert _v("substr(w.coll_b_date, 1, 3) = '107'", "w.coll_b_date >= '107' AND w.coll_b_date < '108'").status == "verified"


def test_prefix_substr_wrong_bounds_corrected_to_like():
    v = _v("substr(w.coll_b_date, 1, 3) = '107'", "w.coll_b_date >= '1070101' AND w.coll_b_date < '1080101'")
    assert v.status == "corrected"
    assert v.example == "w.coll_b_date LIKE '107%'"


def test_substr_length_mismatch_is_not_rewritable():
    # SUBSTR of length 3 can never equal a 2-char literal: no rule, unverified.
    assert _v("SUBSTR(A.C, 1, 3) = '10'", "A.C LIKE '10%'").status == "unverified"


def test_substr_value_with_wildcard_is_not_rewritable():
    assert _v("SUBSTR(A.C, 1, 2) = '1_'", "A.C LIKE '1_%'").status == "unverified"


def test_next_prefix_edge_cases():
    assert rr._next_prefix("107") == "108"
    assert rr._next_prefix("109") is None
    assert rr._next_prefix("AZ") is None


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
