import pytest

from app.services import rule_engine
from app.services.sql_parser import parse_sql_text
from app.settings import get_settings


@pytest.fixture(scope="module")
def cfg():
    s = get_settings()
    return s.rules_config, s.important_tables_config


def _row(rows, rule_id):
    return next(r for r in rows if r.rule_id == rule_id)


def test_cost_pass_below_threshold(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT * FROM T A WHERE A.X=1")
    compliance, rows, findings = rule_engine.evaluate(parsed, 68420, rules_cfg, tables_cfg)
    r001 = _row(rows, "R001")
    assert r001.status == "PASS"
    assert r001.note == "低於規範門檻 100,000"
    assert compliance.status == "PASS"


def test_cost_block_at_threshold(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT * FROM T A WHERE A.X=1")
    compliance, rows, findings = rule_engine.evaluate(parsed, 100000, rules_cfg, tables_cfg)
    r001 = _row(rows, "R001")
    assert r001.status == "BLOCK"
    # Exact equality is a BLOCK because the policy is COST < threshold, but
    # the wording must not imply the value is already above the threshold.
    assert r001.note == "已達規範門檻 100,000"
    assert compliance.status == "BLOCK"
    assert compliance.label == "不符合中心規範"
    assert any(f.rule_id == "R001" and f.statement_index == -1 for f in findings)


def test_cost_pass_just_below_threshold(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT * FROM T A WHERE A.X=1")
    compliance, rows, _ = rule_engine.evaluate(parsed, 99999, rules_cfg, tables_cfg)
    r001 = _row(rows, "R001")
    assert r001.status == "PASS"
    assert r001.note == "低於規範門檻 100,000"


def test_cost_block_just_above_threshold(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT * FROM T A WHERE A.X=1")
    compliance, rows, findings = rule_engine.evaluate(parsed, 100001, rules_cfg, tables_cfg)
    r001 = _row(rows, "R001")
    assert r001.status == "BLOCK"
    assert r001.note == "已高於規範門檻 100,000"
    assert compliance.status == "BLOCK"
    assert any(f.rule_id == "R001" and f.statement_index == -1 for f in findings)


def test_where_missing_is_block(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT * FROM T A")
    compliance, rows, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    assert _row(rows, "R002").status == "BLOCK"
    assert compliance.status == "BLOCK"


def test_where_present_is_pass(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT * FROM T A WHERE A.X=1")
    _, rows, _ = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    assert _row(rows, "R002").status == "PASS"


def test_where_parse_failure_is_review_not_pass(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELEKT * FRM T")
    compliance, rows, _ = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    assert _row(rows, "R002").status == "REVIEW"
    assert compliance.status == "REVIEW"
    assert compliance.label == "請人工確認"


def test_where_not_applicable_for_merge_and_insert_values(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("INSERT INTO T (X, Y) VALUES (1, 2)")
    _, rows, _ = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    assert _row(rows, "R002").status == "NA"


def test_block_wins_over_review_in_overall_compliance(cfg):
    rules_cfg, tables_cfg = cfg
    # statement 1 parse-fails (-> R002 REVIEW), statement 2 has a real BLOCK (parallel hint)
    sql = "SELEKT * FRM T;\nSELECT /*+ PARALLEL(A,4) */ * FROM T2 A WHERE A.X=1;"
    parsed = parse_sql_text(sql)
    compliance, rows, _ = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    assert compliance.status == "BLOCK"


def test_parallel_hint_block(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT /*+ PARALLEL(A,4) */ * FROM T A WHERE A.X=1")
    compliance, rows, _ = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    assert _row(rows, "R003").status == "BLOCK"
    assert compliance.status == "BLOCK"


# ---------------------------------------------------------------------------
# R002 restriction evidence: do not reduce the rule to a keyword check, but
# also do not overclaim that JOIN ON is the same as the center's explicit
# WHERE requirement. A real WHERE inside a subquery/CTE may PASS; JOIN-only
# evidence defaults to REVIEW so a human can confirm the operational rule.
# ---------------------------------------------------------------------------
def test_where_missing_with_no_restriction_evidence_still_blocks(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT * FROM T A, U B")
    compliance, rows, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    assert _row(rows, "R002").status == "BLOCK"
    assert compliance.status == "BLOCK"
    assert any(f.rule_id == "R002" and f.status == "BLOCK" for f in findings)


def test_where_via_inner_join_on_constant_requires_review(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT A.X FROM T A JOIN U B ON A.K = B.K AND B.YR = '114'")
    compliance, rows, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    r002 = _row(rows, "R002")
    assert r002.status == "REVIEW"
    assert compliance.status == "REVIEW"
    assert "JOIN ON" in r002.evidence
    assert "沒有獨立的 WHERE" in r002.note
    assert "人工確認" in r002.note
    assert any(f.rule_id == "R002" and f.status == "REVIEW" for f in findings)


def test_where_via_left_join_on_constant_requires_review_and_explains_outer_side(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT A.X FROM T A LEFT JOIN U B ON A.K = B.K AND B.YR = '114'")
    compliance, rows, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    r002 = _row(rows, "R002")
    assert r002.status == "REVIEW"
    assert compliance.status == "REVIEW"
    # Must not overclaim: an outer-joined ON constant restricts only the
    # joined (副) table, never the driving (主) table's row count.
    assert "不會縮小主表範圍" in r002.note
    assert any(f.rule_id == "R002" and f.status == "REVIEW" for f in findings)


def test_where_via_join_key_equality_only_requires_review(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT A.X FROM T A JOIN U B ON A.K = B.K")
    compliance, rows, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    r002 = _row(rows, "R002")
    assert r002.status == "REVIEW"
    assert compliance.status == "REVIEW"
    assert "JOIN" in r002.evidence
    assert "沒有獨立的 WHERE" in r002.note
    assert any(f.rule_id == "R002" and f.status == "REVIEW" for f in findings)


def test_where_via_cte_source_passes_with_explanation(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("WITH V AS (SELECT K FROM T WHERE Y = 1) SELECT V.K FROM V")
    _compliance, rows, _findings = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    r002 = _row(rows, "R002")
    assert r002.status == "PASS"
    assert "子查詢" in r002.evidence or "WITH" in r002.evidence


def test_restriction_verdict_can_be_configured_to_block():
    settings = get_settings()
    rules_cfg = dict(settings.rules_config)
    rules_cfg["rules"] = [
        dict(r, restriction_verdicts={"join_on_only": "block"}) if r["id"] == "R002" else r
        for r in rules_cfg["rules"]
    ]
    parsed = parse_sql_text("SELECT A.X FROM T A JOIN U B ON A.K = B.K")
    compliance, rows, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, settings.important_tables_config)
    assert _row(rows, "R002").status == "BLOCK"
    assert compliance.status == "BLOCK"
    assert any(f.rule_id == "R002" and f.status == "BLOCK" for f in findings)


def test_restriction_verdict_can_be_configured_to_review():
    settings = get_settings()
    rules_cfg = dict(settings.rules_config)
    rules_cfg["rules"] = [
        dict(r, restriction_verdicts={"join_on_only": "review"}) if r["id"] == "R002" else r
        for r in rules_cfg["rules"]
    ]
    parsed = parse_sql_text("SELECT A.X FROM T A JOIN U B ON A.K = B.K")
    compliance, rows, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, settings.important_tables_config)
    assert _row(rows, "R002").status == "REVIEW"
    assert compliance.status == "REVIEW"
    assert any(f.rule_id == "R002" and f.status == "REVIEW" for f in findings)


def test_notice_rules_never_flip_compliance(cfg):
    rules_cfg, tables_cfg = cfg
    sql = "SELECT * FROM HOUT120 A WHERE TRUNC(A.TXN_DATE) = :D OR A.STATUS = :S"
    parsed = parse_sql_text(sql)
    compliance, rows, _ = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    assert compliance.status == "PASS"
    assert compliance.label == "符合中心規範"
    assert _row(rows, "R005").status == "NOTICE"
    assert _row(rows, "R006").status == "NOTICE"
    assert _row(rows, "R007").status == "NOTICE"
    # 3 distinct NOTICE-class rule rows fired -> notice_count == 3
    assert compliance.notice_count == 3


def test_important_table_name_and_pattern_match(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT * FROM WIIT001 A WHERE A.X=1")
    _, rows, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    r007 = _row(rows, "R007")
    assert r007.status == "NOTICE"
    assert "WIIT001" in r007.evidence
    assert any(f.rule_id == "R007" and f.table == "WIIT001" for f in findings)


def test_important_table_schema_qualified_still_matches(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT * FROM TAX.HOUT120 A WHERE A.X=1")
    _, rows, _ = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    r007 = _row(rows, "R007")
    assert r007.status == "NOTICE"
    assert "HOUT120" in r007.evidence


def test_important_table_no_match_is_pass(cfg):
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("SELECT * FROM PLAIN_TABLE A WHERE A.X=1")
    _, rows, _ = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    assert _row(rows, "R007").status == "PASS"


def test_forbidden_operation_default_config_never_blocks(cfg):
    # PRD §45: forbidden_operations defaults to an empty list; R008 must
    # never fire until business rules are supplied.
    rules_cfg, tables_cfg = cfg
    parsed = parse_sql_text("DELETE FROM WIIT001 A WHERE A.X=1")
    _, rows, _ = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    assert _row(rows, "R008").status == "PASS"


def test_forbidden_operation_with_custom_config_blocks():
    rules_cfg = {
        "rules": [
            {"id": "R001", "name": "COST", "type": "block", "enabled": True, "threshold": 100000},
            {"id": "R002", "name": "WHERE 查詢條件", "type": "block", "enabled": True},
            {"id": "R003", "name": "Parallel Hint", "type": "block", "enabled": True},
            {"id": "R004", "name": "LIKE", "type": "notice", "enabled": True},
            {"id": "R005", "name": "函數", "type": "notice", "enabled": True},
            {"id": "R006", "name": "OR", "type": "notice", "enabled": True},
            {"id": "R007", "name": "重要資料表", "type": "notice", "enabled": True},
            {"id": "R008", "name": "禁止操作", "type": "block", "enabled": True},
        ]
    }
    tables_cfg = {
        "important_tables": [],
        "forbidden_operations": [
            {"name": "SECRET_TABLE", "statement_types": ["DELETE"], "message": "禁止刪除此表。"}
        ],
    }
    parsed = parse_sql_text("DELETE FROM SECRET_TABLE A WHERE A.X=1")
    compliance, rows, findings = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    assert _row(rows, "R008").status == "BLOCK"
    assert compliance.status == "BLOCK"
    assert any(f.rule_id == "R008" for f in findings)

    # same table but via SELECT (not in statement_types) must not block
    parsed2 = parse_sql_text("SELECT * FROM SECRET_TABLE A WHERE A.X=1")
    compliance2, rows2, _ = rule_engine.evaluate(parsed2, 1000, rules_cfg, tables_cfg)
    assert _row(rows2, "R008").status == "PASS"
    assert compliance2.status == "PASS"


def test_multi_statement_evidence_is_segment_prefixed(cfg):
    rules_cfg, tables_cfg = cfg
    sql = "SELECT * FROM T A WHERE A.X=1;\nSELECT * FROM T2 B;"
    parsed = parse_sql_text(sql)
    _, rows, _ = rule_engine.evaluate(parsed, 1000, rules_cfg, tables_cfg)
    r002 = _row(rows, "R002")
    assert r002.status == "BLOCK"
    assert "第2段" in r002.evidence
