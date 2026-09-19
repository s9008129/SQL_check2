import inspect

import pytest

from app.schemas import Finding
from app.services import improvement_score, rule_engine
from app.services.sql_parser import parse_sql_text
from app.settings import get_settings


@pytest.fixture(scope="module")
def rules_cfg():
    return get_settings().rules_config


@pytest.fixture(scope="module")
def tables_cfg():
    return get_settings().important_tables_config


def test_clean_sql_near_threshold_cost_is_good(rules_cfg, tables_cfg):
    parsed = parse_sql_text("SELECT A.X FROM T A WHERE A.Y = 1")
    _, _, findings = rule_engine.evaluate(parsed, 90000, rules_cfg, tables_cfg)
    result = improvement_score.compute(parsed.statements, findings, 90000, rules_cfg)
    assert result.level == "GOOD"
    assert 0 <= result.score <= 59


def test_missing_where_forces_priority_floor(rules_cfg, tables_cfg):
    parsed = parse_sql_text("SELECT * FROM T A")
    _, _, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    result = improvement_score.compute(parsed.statements, findings, 1000, rules_cfg)
    assert result.score >= 80
    assert result.level == "PRIORITY"
    assert any(b.component == "block_floor" for b in result.breakdown)


def test_score_never_exceeds_max(rules_cfg, tables_cfg):
    sql = (
        "SELECT * FROM T A, T2 B, T3 C, T4 D "
        "WHERE TRUNC(A.D1) = :X OR TRUNC(A.D2) = :Y OR A.NAME LIKE '%Z' "
        "OR A.CODE LIKE '%W'"
    )
    parsed = parse_sql_text(sql)
    _, _, findings = rule_engine.evaluate(parsed, 999999999, rules_cfg, tables_cfg)
    result = improvement_score.compute(parsed.statements, findings, 999999999, rules_cfg)
    assert result.score <= 100


def test_index_is_fully_deterministic_and_has_no_ai_component(rules_cfg, tables_cfg):
    # 2026-09-17 user decision: the 0-100 index is computed from deterministic
    # facts only. There is no AI parameter on compute(), no `ai_adjustment`
    # config left in rules.yaml, and no AI row in the breakdown - so the same
    # SQL + COST + rules config always yields exactly the same score, no
    # matter what the AI says (or whether it is available at all).
    assert "ai_adjustment" not in rules_cfg["improvement_score"]
    assert "ai_advice" not in inspect.signature(improvement_score.compute).parameters

    parsed = parse_sql_text("SELECT A.X FROM T A WHERE TRUNC(A.Y) = :D")
    _, _, findings = rule_engine.evaluate(parsed, 68420, rules_cfg, tables_cfg)
    first = improvement_score.compute(parsed.statements, findings, 68420, rules_cfg)
    second = improvement_score.compute(parsed.statements, findings, 68420, rules_cfg)
    assert first.score == second.score
    assert {b.component for b in first.breakdown} == {"rule_findings", "structure", "cost_ratio"}


def test_unknown_weight_key_does_not_crash():
    # A Finding whose rule_id has no WEIGHT_KEYS mapping must be silently
    # ignored by the score, not raise.
    findings = [Finding(rule_id="R999", status="NOTICE", fact="x", statement_index=0)]
    parsed = parse_sql_text("SELECT A.X FROM T A WHERE A.Y = 1")
    rules_cfg = get_settings().rules_config
    result = improvement_score.compute(parsed.statements, findings, 1000, rules_cfg)
    assert result.score >= 0


def test_level_boundaries(rules_cfg):
    levels = rules_cfg["improvement_score"]["levels"]
    assert improvement_score._level_for_score(59, levels)[0] == "GOOD"
    assert improvement_score._level_for_score(60, levels)[0] == "IMPROVE"
    assert improvement_score._level_for_score(79, levels)[0] == "IMPROVE"
    assert improvement_score._level_for_score(80, levels)[0] == "PRIORITY"
    assert improvement_score._level_for_score(0, levels)[0] == "GOOD"
    assert improvement_score._level_for_score(100, levels)[0] == "PRIORITY"


def test_prototype_worked_example_lands_in_improve_band(rules_cfg, tables_cfg):
    # Mirrors PRD prototype: TRUNC(TXN_DATE) condition + HOUT120 + COST 68,420
    # -> plan's worked example expects F=50 (function 30 + important-table 20)
    # and C=10 (68.4% of threshold) -> 60, i.e. "建議改善". Since 2026-09-17
    # there is no AI component any more: 60 comes from deterministic facts
    # alone and must not depend on what the model happens to suggest.
    sql = "SELECT A.X FROM HOUT120 A WHERE TRUNC(A.TXN_DATE) = :D AND A.STATUS = :S"
    parsed = parse_sql_text(sql)
    _, _, findings = rule_engine.evaluate(parsed, 68420, rules_cfg, tables_cfg)
    result = improvement_score.compute(parsed.statements, findings, 68420, rules_cfg)
    assert result.level == "IMPROVE"
    assert result.label == "建議改善"
    assert 60 <= result.score <= 79


def test_cost_over_threshold_alone_still_scores_even_with_no_statements(rules_cfg, tables_cfg):
    # Degenerate case: nothing parseable, but rule_engine still evaluates
    # COST as a global fact. Score must not crash on an empty statement list.
    parsed = parse_sql_text("not sql at all !!!")
    _, _, findings = rule_engine.evaluate(parsed, 150000, rules_cfg, tables_cfg)
    result = improvement_score.compute(parsed.statements, findings, 150000, rules_cfg)
    assert result.score >= 0


def test_breakdown_explains_each_component_in_plain_language(rules_cfg, tables_cfg):
    # 2026-09-17 user feedback: "COST 佔規範門檻約 69%" was not understandable.
    # Every component must carry a `detail` sentence; the COST one must state
    # the actual COST, the threshold, the percentage and the max points.
    parsed = parse_sql_text("SELECT A.X FROM T A WHERE A.Y = 1")
    _, _, findings = rule_engine.evaluate(parsed, 68888, rules_cfg, tables_cfg)
    result = improvement_score.compute(parsed.statements, findings, 68888, rules_cfg)
    by_component = {b.component: b for b in result.breakdown}
    assert set(by_component) == {"rule_findings", "structure", "cost_ratio"}
    for item in result.breakdown:
        assert item.detail and "分" in item.detail
        assert "佔規範門檻" not in item.label
    cost_item = by_component["cost_ratio"]
    assert cost_item.label == "COST 接近門檻的程度"
    assert "68,888" in cost_item.detail
    assert "100,000" in cost_item.detail
    assert "69%" in cost_item.detail
    assert "最多 15 分" in cost_item.detail


def test_block_floor_breakdown_item_has_detail(rules_cfg, tables_cfg):
    parsed = parse_sql_text("SELECT * FROM T A")
    _, _, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    result = improvement_score.compute(parsed.statements, findings, 1000, rules_cfg)
    floor = next(b for b in result.breakdown if b.component == "block_floor")
    assert floor.detail and "80" in floor.detail



def test_cartesian_join_is_at_least_improve_without_becoming_center_block(rules_cfg, tables_cfg):
    sql = "SELECT A.ID, B.TYPE FROM TEST_DATA A, TEST_ADDRESS B WHERE A.STATUS = 'A'"
    parsed = parse_sql_text(sql)
    compliance, _, findings = rule_engine.evaluate(parsed, 5000, rules_cfg, tables_cfg)
    result = improvement_score.compute(parsed.statements, findings, 5000, rules_cfg)

    assert compliance.status == "PASS"
    assert result.level in {"IMPROVE", "PRIORITY"}
    assert result.score >= 60
    floor = next(b for b in result.breakdown if b.component == "structure_floor")
    assert "不是新增中心規範" in (floor.detail or "")
