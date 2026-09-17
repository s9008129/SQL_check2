"""2026-09-17: the improvement-potential level is derived by the server from
facts it knows; the model's percentage is archive-only. These tests pin the
derivation table in ai_service.improvement_potential."""

from app.schemas import AdviceItem, AiResult, Finding, SuggestedSql
from app.services.ai_service import improvement_potential


def _finding(status: str) -> Finding:
    return Finding(rule_id="R005", status=status, fact="TRUNC(A.D)", statement_index=0)


def _advice(impact: str, verification: str | None = None) -> AdviceItem:
    return AdviceItem(
        title="t", explanation="e", impact=impact, example="A.X = 1" if verification else None, before="x", verification=verification
    )


def _ok(advice: list[AdviceItem], outcome: str = "advice_only") -> AiResult:
    return AiResult(
        status="ok",
        summary="s",
        advice=advice,
        suggested_sql=SuggestedSql(available=outcome == "provided", reason="r", sql="SELECT 1" if outcome == "provided" else None, outcome=outcome),
    )


def test_block_finding_is_high():
    level, basis = improvement_potential(_ok([]), [_finding("BLOCK")])
    assert level == "high"
    assert basis == ["規則檢核：1 項不符合"]


def test_confirmed_high_impact_fragment_is_high():
    level, basis = improvement_potential(_ok([_advice("high", "corrected")]), [])
    assert level == "high"
    assert basis == ["AI 建議：高影響（系統已確認查詢結果不變）"]


def test_unconfirmed_high_impact_is_only_low():
    # A high-impact claim the system could not confirm is not evidence.
    level, basis = improvement_potential(_ok([_advice("high", "unverified")]), [])
    assert level == "low"
    assert basis == ["AI 建議：高影響（系統無法確認查詢結果）"]


def test_notice_finding_is_medium():
    level, _ = improvement_potential(_ok([]), [_finding("NOTICE")])
    assert level == "medium"


def test_passed_full_rewrite_is_medium_or_high_with_high_advice():
    assert improvement_potential(_ok([_advice("medium", "verified")], outcome="provided"), [])[0] == "medium"
    assert improvement_potential(_ok([_advice("high", "verified")], outcome="provided"), [])[0] == "high"
    assert improvement_potential(_ok([_advice("high", None)], outcome="provided"), [])[0] == "high"


def test_prose_only_advice_is_low():
    assert improvement_potential(_ok([_advice("low")]), [])[0] == "low"


def test_nothing_found_is_none():
    assert improvement_potential(_ok([], outcome="not_needed"), []) == (None, [])


def test_unavailable_is_none():
    assert improvement_potential(AiResult(status="unavailable", message="m"), [_finding("BLOCK")]) == (None, [])


def test_basis_lists_rules_rewrite_and_advice_in_order():
    level, basis = improvement_potential(
        _ok([_advice("high", "verified"), _advice("low")], outcome="provided"),
        [_finding("BLOCK"), _finding("NOTICE"), _finding("NOTICE")],
    )
    assert level == "high"
    assert basis == [
        "規則檢核：1 項不符合、2 項提醒",
        "已提供整段建議寫法，系統已確認查詢結果不變",
        "AI 建議：高影響（系統已確認查詢結果不變）、低影響",
    ]
