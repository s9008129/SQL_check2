from app.schemas import VerifiedRewrite
from app.services import execution_plan

ESTIMATED_PLAN = """
Plan hash value: 3556827125

------------------------------------------------------------------------------
| Id | Operation           | Name        | Rows | Bytes | Cost (%CPU)| Time     |
------------------------------------------------------------------------------
|  0 | SELECT STATEMENT    |             |    4 |   124 |     5 (20)| 00:00:01 |
|  1 |  SORT ORDER BY      |             |    4 |   124 |     5 (20)| 00:00:01 |
|* 2 |   HASH JOIN         |             |    4 |   124 |     4  (0)| 00:00:01 |
|* 3 |    TABLE ACCESS FULL| EMPLOYEES   |    4 |    60 |     2  (0)| 00:00:01 |
|  4 |    TABLE ACCESS FULL| DEPARTMENTS |   27 |   432 |     2  (0)| 00:00:01 |
------------------------------------------------------------------------------

Predicate Information (identified by operation id):
---------------------------------------------------
   2 - access("E"."DEPARTMENT_ID"="D"."DEPARTMENT_ID")
   3 - filter("SALARY"<3000)
"""


ACTUAL_PLAN = """
SQL_ID  8h4m1abcxyz12, child number 0
Plan hash value: 123456789

---------------------------------------------------------------------------------------------------
| Id | Operation          | Name     | Starts | E-Rows | A-Rows | A-Time   | Buffers | Reads | Cost |
---------------------------------------------------------------------------------------------------
|  0 | SELECT STATEMENT   |          |      1 |        |   1000 | 00:00:01 |    2000 |     3 |   88 |
|* 1 | TABLE ACCESS FULL  | TAX_CASE |      1 |     10 |   1000 | 00:00:01 |    2000 |     3 |   88 |
---------------------------------------------------------------------------------------------------

Predicate Information (identified by operation id):
---------------------------------------------------
   1 - filter(TRUNC("A"."CASE_DATE")=DATE '2026-09-20')

Statistics
----------------------------------------------------------
       2000  consistent gets
          3  physical reads
       1000  rows processed
"""


def test_parses_dbms_xplan_estimated_plan_and_predicates():
    result = execution_plan.analyze(ESTIMATED_PLAN, expected_cost=5)
    assert result.recognized is True
    assert result.source == "estimated"
    assert result.plan_hash_value == "3556827125"
    assert result.plan_cost == 5
    assert result.cost_matches_input is True
    assert result.step_count == 5

    step3 = next(step for step in result.steps if step.id == 3)
    assert step3.operation == "TABLE ACCESS FULL"
    assert step3.object_name == "EMPLOYEES"
    assert step3.filter_predicates == ['"SALARY"<3000']
    assert any(item.code == "TABLE_ACCESS_FULL" for item in result.observations)


def test_parses_actual_rows_runtime_metrics_and_cardinality_gap():
    result = execution_plan.analyze(ACTUAL_PLAN, expected_cost=88)
    assert result.source == "actual"
    assert result.has_runtime_stats is True
    assert result.sql_id == "8h4m1abcxyz12"
    assert {item.key: item.value for item in result.runtime_metrics}["consistent_gets"] == 2000

    step1 = next(step for step in result.steps if step.id == 1)
    assert step1.estimated_rows == 10
    assert step1.actual_rows == 1000
    assert step1.buffers == 2000
    assert any(item.code == "CARDINALITY_GAP" and item.step_id == 1 for item in result.observations)
    assert any(item.code == "FUNCTION_FILTER_PREDICATE" for item in result.observations)


def test_cost_mismatch_is_review_evidence_not_compliance():
    result = execution_plan.analyze(ESTIMATED_PLAN, expected_cost=999)
    mismatch = next(item for item in result.observations if item.code == "COST_MISMATCH")
    assert mismatch.level == "review"
    assert "999" in mismatch.detail
    assert "5" in mismatch.detail


def test_verified_substr_rewrite_can_be_correlated_with_filter_evidence():
    plan = ACTUAL_PLAN.replace("TRUNC", "SUBSTR")
    rewrite = VerifiedRewrite(
        statement_index=0,
        rule="substr_eq_to_like",
        source_rule_id="R005",
        title="SUBSTR 比對改為 LIKE",
        before="SUBSTR(A.CASE_DATE,1,3)='114'",
        after="A.CASE_DATE LIKE '114%'",
    )
    result = execution_plan.analyze(plan, expected_cost=88, verified_rewrites=[rewrite])
    item = next(obs for obs in result.observations if obs.code == "VERIFIED_REWRITE_PLAN_MATCH")
    assert item.level == "opportunity"
    assert item.step_id == 1


def test_sql_developer_csv_grid_export_is_supported():
    csv_text = """Id,Operation,Name,Rows,Cost (%CPU),Time
0,SELECT STATEMENT,,25,14 (0),00:00:01
1,TABLE ACCESS FULL,TAX_CASE,25,14 (0),00:00:01
"""
    result = execution_plan.analyze(csv_text, expected_cost=14)
    assert result.recognized is True
    assert result.source == "estimated"
    assert result.steps[1].object_name == "TAX_CASE"
    assert result.plan_cost == 14


def test_sql_developer_tab_copy_is_supported():
    tab_text = "Id\tOperation\tName\tE-Rows\tA-Rows\tStarts\tBuffers\n0\tSELECT STATEMENT\t\t10\t12\t1\t8"
    result = execution_plan.analyze(tab_text, expected_cost=100)
    assert result.recognized is True
    assert result.source == "actual"
    assert result.steps[0].actual_rows == 12


def test_unrecognized_text_fails_closed_without_inventing_plan_facts():
    result = execution_plan.analyze("這不是執行計畫", expected_cost=100)
    assert result.recognized is False
    assert result.source == "unknown"
    assert result.steps == []
    assert result.observations == []
