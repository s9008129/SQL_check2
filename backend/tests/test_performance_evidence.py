from app.schemas import AdviceItem, VerifiedRewrite
from app.services import performance_evidence, rewrite_rules
from app.services.pattern_selector import select_patterns
from app.services.sql_parser import parse_sql_text


def _rules() -> dict:
    return {"improvement_score": {"structure": {"many_tables_threshold": 4}}}


def _verified(sql: str) -> list[VerifiedRewrite]:
    metadata = {
        "substr_eq_to_like": ("R005", "SUBSTR 比對改為 LIKE"),
        "or_eq_to_in": ("R006", "同欄位 OR 改為 IN"),
    }
    parsed = parse_sql_text(sql)
    items: list[VerifiedRewrite] = []
    for statement in parsed.statements:
        for candidate in rewrite_rules.find_verified_rewrites(statement.raw_sql):
            source_rule_id, title = metadata[candidate.rule]
            items.append(
                VerifiedRewrite(
                    statement_index=statement.index,
                    rule=candidate.rule,
                    source_rule_id=source_rule_id,
                    title=title,
                    before=candidate.before,
                    after=candidate.after,
                )
            )
    return items


def _evidence(sql: str):
    parsed = parse_sql_text(sql)
    selection = select_patterns(parsed.statements, [], _rules())
    return performance_evidence.build_performance_evidence(selection, _verified(sql))


def _ids(items) -> set[str]:
    return {item.evidence_id for item in items}


def test_prefix_substr_gets_transformed_column_and_prefix_like_evidence():
    sql = "SELECT A.X FROM T A WHERE SUBSTR(A.YEAR_CODE, 1, 2) = '13'"
    items = _evidence(sql)
    assert _ids(items) == {
        "ORACLE11G_TRANSFORMED_COLUMN",
        "ORACLE11G_PREFIX_LIKE_RANGE_SCAN",
    }
    prefix = next(item for item in items if item.evidence_id == "ORACLE11G_PREFIX_LIKE_RANGE_SCAN")
    assert prefix.source_label == "Oracle Database 11g 官方文件"
    assert "固定文字開頭" in prefix.applicability_zh_tw
    assert "一定" not in prefix.claim_zh_tw
    assert "source_url" not in prefix.model_dump()


def test_mid_string_substr_never_gets_positive_prefix_range_scan_claim():
    sql = "SELECT A.X FROM T A WHERE SUBSTR(A.MANAGE_KEY, 6, 3) = '551'"
    items = _evidence(sql)
    assert "ORACLE11G_TRANSFORMED_COLUMN" in _ids(items)
    assert "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT" in _ids(items)
    assert "ORACLE11G_PREFIX_LIKE_RANGE_SCAN" not in _ids(items)
    limited = next(item for item in items if item.evidence_id == "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT")
    assert "只能說改寫安全" in limited.applicability_zh_tw
    assert "不能因此宣稱一般索引的查找效率一定會變好" in limited.applicability_zh_tw


def test_repeated_correlated_max_gets_11g_subquery_evidence_but_no_verified_rewrite():
    sql = """
    SELECT A.CASE_ID
    FROM TAX_CASE A
    JOIN TAX_HISTORY B ON B.CASE_ID = A.CASE_ID
    WHERE B.UPDATE_DATE = (
      SELECT MAX(H1.UPDATE_DATE)
      FROM TAX_HISTORY H1
      WHERE H1.CASE_ID = A.CASE_ID
    )
    AND B.UPDATE_TIME = (
      SELECT MAX(H2.UPDATE_TIME)
      FROM TAX_HISTORY H2
      WHERE H2.CASE_ID = A.CASE_ID
    )
    """
    parsed = parse_sql_text(sql)
    selection = select_patterns(parsed.statements, [], _rules())
    assert "LATEST_ROW_CORRELATED_MAX" in selection.exact_ids
    assert rewrite_rules.find_verified_rewrites(sql) == []
    items = performance_evidence.build_performance_evidence(selection, [])
    assert _ids(items) == {"ORACLE11G_SUBQUERY_UNNESTING"}
    assert items[0].strength == "conditional"
    assert "MAX" in items[0].claim_zh_tw
    assert "反覆處理相似的工作" in items[0].claim_zh_tw


def test_same_column_or_exposes_oracle_in_list_limit_without_claiming_speedup():
    sql = "SELECT A.X FROM T A WHERE A.STATUS='A' OR A.STATUS='B'"
    items = _evidence(sql)
    assert _ids(items) == {"ORACLE11G_IN_LIST_LIMIT"}
    assert "不代表" in items[0].caveat_zh_tw
    assert "一定會變快" in items[0].caveat_zh_tw


def test_clean_sql_has_no_performance_evidence():
    assert _evidence("SELECT A.X FROM T A WHERE A.STATUS='1'") == []


def test_merge_advice_evidence_materializes_family_signal_source_for_visible_advice():
    sql = "SELECT A.ID FROM T A WHERE TO_CHAR(A.TXN_DATE,'YYYY')='2024'"
    parsed = parse_sql_text(sql)
    selection = select_patterns(
        parsed.statements,
        [],
        _rules(),
    )
    # PREDICATE_FUNCTION_GENERIC remains a family signal, but once the
    # server provenance gate allows that specific advice, the API must also
    # materialize its reviewed Oracle source.
    advice = [
        AdviceItem(
            title="直接比對原始欄位",
            explanation="請先確認欄位型態。",
            example=None,
            impact="medium",
            pattern_id="PREDICATE_FUNCTION_GENERIC",
            evidence_ids=["ORACLE11G_TRANSFORMED_COLUMN"],
            verification="unverified",
        )
    ]
    merged = performance_evidence.merge_advice_evidence([], selection, advice)
    assert _ids(merged) == {"ORACLE11G_TRANSFORMED_COLUMN"}
    assert merged[0].pattern_id == "PREDICATE_FUNCTION_GENERIC"
