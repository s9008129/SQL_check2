"""2026-09-17 round-1 third-party review: the golden runner's clean-SQL
expectation used to accept EITHER `advice == []` OR
`suggested_sql.outcome == "not_needed"`, which let a "not_needed" answer that
still carried 1-3 fabricated advice items pass - exactly the hard-sell
behaviour those cases exist to catch. These tests pin the strict rule:
both signals are required, and the contradictory state is a FAIL.

Only the pure judgement helper is exercised here; the live-model run itself
is production-host-only (needs a real Ollama/Gemma instance)."""

from tests.golden.run_golden import evaluate_no_advice_expectation


def test_quiet_clean_sql_passes_only_when_both_signals_agree():
    quiet_kind, problems = evaluate_no_advice_expectation("not_needed", 0)
    assert problems == []
    assert quiet_kind == "not_needed"


def test_not_needed_with_one_advice_item_is_a_contradiction_and_fails():
    quiet_kind, problems = evaluate_no_advice_expectation("not_needed", 1)
    assert quiet_kind == "not_needed_with_advice"
    assert len(problems) == 1
    assert "矛盾狀態" in problems[0]


def test_not_needed_with_three_advice_items_fails():
    # Three is the schema maximum - the most aggressive hard sell must fail.
    _, problems = evaluate_no_advice_expectation("not_needed", 3)
    assert len(problems) == 1


def test_empty_advice_with_a_non_quiet_outcome_fails():
    # advice == [] alone is not enough: the rewrite path must also have
    # concluded that nothing needed changing.
    for outcome in ("advice_only", "provided", "unavailable", None):
        quiet_kind, problems = evaluate_no_advice_expectation(outcome, 0)
        assert quiet_kind == "advice_empty", outcome
        assert problems, outcome


def test_advice_and_non_quiet_outcome_fails_as_before():
    quiet_kind, problems = evaluate_no_advice_expectation("advice_only", 2)
    assert quiet_kind == "neither"
    assert len(problems) == 1
