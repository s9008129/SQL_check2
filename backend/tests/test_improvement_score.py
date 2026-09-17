import pytest

from app.schemas import AdviceItem, Finding
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
    advice = [AdviceItem(title="t", explanation="e", impact="high") for _ in range(5)]
    result = improvement_score.compute(parsed.statements, findings, 999999999, rules_cfg, ai_advice=advice)
    assert result.score <= 100


def test_ai_adjustment_capped_at_component_max(rules_cfg, tables_cfg):
    parsed = parse_sql_text("SELECT A.X FROM T A WHERE A.Y = 1")
    _, _, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    advice = [AdviceItem(title="t", explanation="e", impact="high") for _ in range(10)]
    result = improvement_score.compute(parsed.statements, findings, 1000, rules_cfg, ai_advice=advice)
    ai_component = next(b for b in result.breakdown if b.component == "ai_adjustment")
    assert ai_component.score == 10.0  # capped, not 50


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
    # -> plan's worked example expects F=50 (function 30 + important-table
    # 20), C=10 (68.4% of threshold), A up to 10 from AI impact -> "建議改善".
    sql = "SELECT A.X FROM HOUT120 A WHERE TRUNC(A.TXN_DATE) = :D AND A.STATUS = :S"
    parsed = parse_sql_text(sql)
    _, _, findings = rule_engine.evaluate(parsed, 68420, rules_cfg, tables_cfg)
    advice = [
        AdviceItem(title="日期條件可再簡化", explanation="e", impact="high"),
        AdviceItem(title="查詢 HOUT120 時可再確認範圍", explanation="e", impact="medium"),
    ]
    result = improvement_score.compute(parsed.statements, findings, 68420, rules_cfg, ai_advice=advice)
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
    assert set(by_component) == {"rule_findings", "structure", "cost_ratio", "ai_adjustment"}
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
