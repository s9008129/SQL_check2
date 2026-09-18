"""2026-09-17: the improvement-potential level is derived by the server from
server-observable facts only; the model's percentage is archive-only and the
model's own `impact` rating never raises the level. These tests pin the
derivation table in ai_service.improvement_potential."""

from app.schemas import AdviceItem, AiResult, Finding, SuggestedSql
from app.services.ai_service import improvement_potential


def _finding(status: str, rule_id: str = "R005") -> Finding:
    return Finding(rule_id=rule_id, status=status, fact="TRUNC(A.D)", statement_index=0)


def _advice(impact: str, verification: str | None = None) -> AdviceItem:
    return AdviceItem(
        title="t",
        explanation="e",
        impact=impact,
        example="A.X = 1" if verification else None,
        before="x",
        verification=verification,
    )


def _ok(advice: list[AdviceItem], outcome: str = "advice_only") -> AiResult:
    return AiResult(
        status="ok",
        summary="s",
        advice=advice,
        suggested_sql=SuggestedSql(
            available=outcome == "provided",
            reason="r",
            sql="SELECT 1" if outcome == "provided" else None,
            outcome=outcome,
        ),
    )


# --- deterministic non-compliance -----------------------------------------
# 2026-09-17 round-1 third-party review: a BLOCK is deterministic
# non-compliance, but on its own it is NOT a server-verified improvement
# evidence, so it can never promote the potential to high. It stays visible
# through the 中心規範 verdict + 改善優先指數, and the potential stays at
# "low" (never high, never None / 「目前寫法良好」).


def test_block_finding_alone_is_low_never_high():
    level, basis = improvement_potential(_ok([]), [_finding("BLOCK", rule_id="R002")])
    assert level == "low"
    assert basis == ["規則檢核：1 項不符合"]


def test_block_finding_plus_governance_notice_stays_low_not_notice_only():
    # A BLOCK is a concrete finding about the SQL itself: unlike a pure R007
    # governance reminder it must never fall back to "notice_only".
    level, basis = improvement_potential(
        _ok([], outcome="not_needed"),
        [_finding("BLOCK", rule_id="R002"), _finding("NOTICE", rule_id="R007")],
    )
    assert level == "low"
    assert basis == ["規則檢核：1 項不符合、1 項提醒"]


def test_block_finding_with_one_verified_evidence_is_medium():
    level, _ = improvement_potential(
        _ok([_advice("high", "verified")], outcome="advice_only"),
        [_finding("BLOCK", rule_id="R002")],
    )
    assert level == "medium"


def test_block_finding_with_two_verified_evidences_is_high():
    level, _ = improvement_potential(
        _ok([_advice("high", "verified"), _advice("low", "corrected")], outcome="advice_only"),
        [_finding("BLOCK", rule_id="R002")],
    )
    assert level == "high"


def test_block_finding_with_validated_full_rewrite_is_medium():
    # The rewrite itself is exactly one verified evidence.
    level, _ = improvement_potential(_ok([], outcome="provided"), [_finding("BLOCK", rule_id="R002")])
    assert level == "medium"


# --- R007 governance reminder: reminder shown, but no level ---------------


def test_pure_governance_notice_is_not_a_level():
    # R007 重要資料表 is a reminder about *which data* is touched - it is not
    # evidence about the SQL writing itself, so the UI must say "有提醒，但未
    # 確認具體改善點" rather than 高／中／低 (and never 「目前寫法良好」).
    level, basis = improvement_potential(_ok([], outcome="not_needed"), [_finding("NOTICE", rule_id="R007")])
    assert level == "notice_only"
    assert basis == ["規則檢核：1 項提醒"]


def test_governance_notices_never_promote_to_medium():
    level, _ = improvement_potential(
        _ok([], outcome="not_needed"),
        [_finding("NOTICE", rule_id="R007"), _finding("NOTICE", rule_id="R007")],
    )
    assert level == "notice_only"


# --- concrete SQL-writing findings without a verified rewrite -------------


def test_write_style_findings_without_verified_rewrite_are_at_most_low():
    for rule_id in ("R004", "R005", "R006"):
        level, _ = improvement_potential(_ok([], outcome="advice_only"), [_finding("NOTICE", rule_id=rule_id)])
        assert level == "low", rule_id


def test_unconfirmed_high_impact_advice_is_only_low():
    # A high-impact claim the system could not confirm is not evidence.
    level, basis = improvement_potential(_ok([_advice("high", "unverified")]), [])
    assert level == "low"
    assert basis == []


def test_prose_only_advice_is_low():
    assert improvement_potential(_ok([_advice("low")]), [])[0] == "low"


def test_unverified_advice_stays_low_even_with_governance_notice():
    level, _ = improvement_potential(
        _ok([_advice("high", "unverified")], outcome="advice_only"), [_finding("NOTICE", rule_id="R007")]
    )
    assert level == "low"


# --- server-verified evidence ---------------------------------------------


def test_one_verified_fragment_is_medium():
    level, basis = improvement_potential(_ok([_advice("high", "verified")], outcome="advice_only"), [])
    assert level == "medium"
    assert basis == ["系統已驗證 1 項建議片段可保留原查詢結果"]


def test_one_corrected_fragment_is_medium():
    # `corrected` means the system replaced the model's fragment with its own
    # rule-derived equivalent - that is verified evidence too.
    level, _ = improvement_potential(_ok([_advice("low", "corrected")], outcome="advice_only"), [])
    assert level == "medium"


def test_validated_full_rewrite_alone_is_medium():
    level, basis = improvement_potential(_ok([], outcome="provided"), [])
    assert level == "medium"
    assert basis == ["已提供整段建議寫法，系統已確認查詢結果不變"]


def test_full_rewrite_plus_verified_fragment_is_high():
    level, basis = improvement_potential(_ok([_advice("medium", "verified")], outcome="provided"), [])
    assert level == "high"
    assert basis == [
        "已提供整段建議寫法，系統已確認查詢結果不變",
        "系統已驗證 1 項建議片段可保留原查詢結果",
    ]


def test_multiple_verified_fragments_are_high():
    level, _ = improvement_potential(
        _ok([_advice("high", "verified"), _advice("medium", "corrected")], outcome="advice_only"), []
    )
    assert level == "high"


def test_ai_impact_high_without_verified_evidence_never_reaches_high():
    # The model's own impact rating is not evidence: high/medium stay 中低
    # unless the *server* re-validated something.
    assert improvement_potential(_ok([_advice("high", "unverified")], outcome="advice_only"), [])[0] == "low"
    assert improvement_potential(_ok([_advice("high", None)], outcome="provided"), [])[0] == "medium"
    assert improvement_potential(_ok([_advice("high", None)], outcome="advice_only"), [])[0] == "low"


# --- nothing found / degraded ---------------------------------------------


def test_nothing_found_is_none():
    assert improvement_potential(_ok([], outcome="not_needed"), []) == (None, [])


def test_unavailable_is_none():
    assert improvement_potential(AiResult(status="unavailable", message="m"), [_finding("BLOCK")]) == (None, [])


# --- evidence source (2026-09-18 Runtime Correctness v1) --------------------
# The derivation table above is unchanged; what changed is which advice can
# become "verified"/"corrected" in the first place. TRUNC→range and NVL
# rewrites are not provable from SQL text, so after the real advice
# post-processing (ai_service._filter_advice → rewrite_rules.verify_fragment)
# they must stay "unverified" and never count as server-verified evidence.
def _through_runtime(before: str, example: str) -> AdviceItem:
    from app.services.ai_service import _filter_advice

    raw = AdviceItem(title="t", explanation="e", impact="high", before=before, example=example)
    (item,) = _filter_advice([raw], forbidden=[], vocab={})
    return item


def test_trunc_and_nvl_rewrites_never_become_server_verified_evidence():
    advice = [
        _through_runtime("TRUNC(A.TXN_DATE) = :D", "A.TXN_DATE >= :D AND A.TXN_DATE < :D + 1"),
        _through_runtime("NVL(A.S, 'N') = 'N'", "(A.S = 'N' OR A.S IS NULL)"),
        _through_runtime("NVL(A.S, 'N') = 'Y'", "A.S = 'Y'"),
    ]
    assert [a.verification for a in advice] == ["unverified", "unverified", "unverified"]
    # the system no longer substitutes its own "equivalent" text
    assert advice[0].example == "A.TXN_DATE >= :D AND A.TXN_DATE < :D + 1"
    level, basis = improvement_potential(_ok(advice, outcome="advice_only"), [_finding("NOTICE")])
    assert level == "low"
    assert not any("系統已驗證" in line for line in basis)


def test_proven_substr_rewrite_still_counts_as_evidence():
    item = _through_runtime("SUBSTR(A.C, 6, 3) = '551'", "A.C LIKE '__%551%'")
    assert item.verification == "corrected"
    assert item.example == "A.C LIKE '_____551%'"
    assert improvement_potential(_ok([item], outcome="advice_only"), [])[0] == "medium"


def test_basis_lists_rules_rewrite_and_verified_evidence_in_order():
    level, basis = improvement_potential(
        _ok([_advice("high", "verified"), _advice("low")], outcome="provided"),
        [_finding("BLOCK", rule_id="R002"), _finding("NOTICE", rule_id="R007"), _finding("NOTICE", rule_id="R004")],
    )
    assert level == "high"
    assert basis == [
        "規則檢核：1 項不符合、2 項提醒",
        "已提供整段建議寫法，系統已確認查詢結果不變",
        "系統已驗證 1 項建議片段可保留原查詢結果",
    ]
