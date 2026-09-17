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


# --- TRUNC -----------------------------------------------------------------
def test_trunc_eq_range_verified_with_assumption():
    v = _v("TRUNC(A.TXN_DATE) = :D", "A.TXN_DATE >= :D AND A.TXN_DATE < :D + 1")
    assert v.status == "verified"
    assert v.assumption and ":D" in v.assumption


def test_trunc_eq_wrong_range_corrected():
    v = _v("TRUNC(A.TXN_DATE) = :D", "A.TXN_DATE BETWEEN :D AND :D + 1")
    assert v.status == "corrected"
    assert "< :D + 1" in v.example


# --- NVL -------------------------------------------------------------------
def test_nvl_same_default_becomes_or_is_null():
    v = _v("NVL(A.S, 'N') = 'N'", "(A.S = 'N' OR A.S IS NULL)")
    assert v.status == "verified"


def test_nvl_other_value_becomes_plain_eq():
    v = _v("NVL(A.S, 'N') = 'Y'", "A.S = 'Y' OR A.S IS NULL")
    assert v.status == "corrected"
    assert v.example == "A.S = 'Y'"


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
    before = "TRUNC(A.D) = :X AND A.S = '1'"
    ok = "A.D >= :X AND A.D < :X + 1 AND A.S = '1'"
    assert _v(before, ok).status == "verified"
    # dropping the untouched conjunct is not equivalent
    assert _v(before, "A.D >= :X AND A.D < :X + 1").status == "corrected"


# --- full rewrite predicate check ------------------------------------------
def _trees(orig: str, sugg: str):
    return parse_one(orig, read="oracle"), parse_one(sugg, read="oracle")


def test_full_rewrite_with_rule_derived_change_ok():
    o, s = _trees(
        "SELECT A.X FROM T A WHERE TRUNC(A.D) = :X AND A.S = '1'",
        "SELECT A.X FROM T A WHERE A.D >= :X AND A.D < :X + 1 AND A.S = '1'",
    )
    assert rr.verify_predicate_changes(o, s) == (True, None)


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
