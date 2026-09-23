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
    assert result.source_label == "正式資料庫 F10 Explain Plan（估算）"
    assert "不代表 SQL 已實際執行" in result.message
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
    assert result.source_label == "含實際執行統計的執行計畫"
    assert "來源環境仍以使用者的作業紀錄為準" in result.message
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


def test_sql_developer_csv_grid_export_supports_plan_table_columns():
    csv_text = """Id,Operation,Options,Object_Name,Cardinality,Cost,Access_Predicates,Filter_Predicates
0,SELECT STATEMENT,,,25,14,,
1,TABLE ACCESS,FULL,TAX_CASE,25,14,,TRUNC(A.CASE_DATE)=DATE_VALUE
"""
    result = execution_plan.analyze(csv_text, expected_cost=14)
    assert result.recognized is True
    assert result.source == "estimated"
    step1 = result.steps[1]
    assert step1.operation == "TABLE ACCESS"
    assert step1.options == "FULL"
    assert step1.object_name == "TAX_CASE"
    assert step1.estimated_rows == 25
    assert step1.filter_predicates == ["TRUNC(A.CASE_DATE)=DATE_VALUE"]
    assert result.plan_cost == 14
    assert any(item.code == "TABLE_ACCESS_FULL" and item.step_id == 1 for item in result.observations)
    assert any(item.code == "FUNCTION_FILTER_PREDICATE" and item.step_id == 1 for item in result.observations)


def test_sql_developer_tab_copy_is_supported():
    tab_text = "Id\tOperation\tName\tE-Rows\tA-Rows\tStarts\tBuffers\n0\tSELECT STATEMENT\t\t10\t12\t1\t8"
    result = execution_plan.analyze(tab_text, expected_cost=100)
    assert result.recognized is True
    assert result.source == "actual"
    assert result.steps[0].actual_rows == 12


def test_tab_delimited_plan_table_split_operation_options_are_merged_for_detection():
    tab_text = (
        "Id\tOperation\tOptions\tObject_Name\tCardinality\tCost\tFilter_Predicates\n"
        "0\tSELECT STATEMENT\t\t\t25\t14\t\n"
        "1\tTABLE ACCESS\tFULL\tTAX_CASE\t25\t14\tTRUNC(A.CASE_DATE)=DATE_VALUE"
    )
    result = execution_plan.analyze(tab_text, expected_cost=14)
    assert result.recognized is True
    step1 = result.steps[1]
    assert step1.operation == "TABLE ACCESS"
    assert step1.options == "FULL"
    assert any(item.code == "TABLE_ACCESS_FULL" and item.step_id == 1 for item in result.observations)


def test_plan_table_predicate_columns_and_predicate_section_are_deduplicated():
    # A SQL Developer PLAN_TABLE export carries the predicate in its own
    # column; DBMS_XPLAN text repeats the same predicate under "Predicate
    # Information". The same predicate must not be reported twice. The
    # predicate field is RFC4180-escaped, exactly as a CSV export writes a
    # value that itself contains double quotes.
    text = (
        "Id,Operation,Options,Object_Name,Cardinality,Cost,Access_Predicates,Filter_Predicates\n"
        "0,SELECT STATEMENT,,,25,14,,\n"
        '1,TABLE ACCESS,FULL,TAX_CASE,25,14,,"""A"".""TAX_ID""=1"\n'
        "\n"
        "Predicate Information (identified by operation id):\n"
        "---------------------------------------------------\n"
        '   1 - filter("A"."TAX_ID"=1)\n'
    )
    result = execution_plan.analyze(text, expected_cost=14)
    step1 = result.steps[1]
    assert step1.filter_predicates == ['"A"."TAX_ID"=1']
    assert step1.access_predicates == []


def test_estimated_plan_never_reports_a_cardinality_gap_without_actual_rows():
    plan_without_actuals = """
---------------------------------------------------------------
| Id | Operation          | Name | Rows | Cost (%CPU) | Time     |
---------------------------------------------------------------
|  0 | SELECT STATEMENT   |      |   10 |    68 (0)   | 00:00:01 |
|* 1 | TABLE ACCESS FULL  | T    |   10 |    68 (0)   | 00:00:01 |
---------------------------------------------------------------
Predicate Information (identified by operation id):
---------------------------------------------------
   1 - filter("A"."Y"=1)
"""
    result = execution_plan.analyze(plan_without_actuals, expected_cost=68)
    assert result.source == "estimated"
    assert result.has_runtime_stats is False
    assert [item.code for item in result.observations] == ["TABLE_ACCESS_FULL"]


def test_root_cost_falls_back_to_first_row_when_no_step_zero_is_present():
    text = "Id,Operation,Options,Object_Name,Cardinality,Cost\n1,TABLE ACCESS,FULL,T,5,9"
    result = execution_plan.analyze(text, expected_cost=9)
    assert result.plan_cost == 9
    assert result.cost_matches_input is True


def test_full_scan_evidence_never_becomes_an_index_recommendation():
    text = (
        "Id,Operation,Options,Object_Name,Cardinality,Cost\n"
        "0,SELECT STATEMENT,,,25,14\n"
        "1,TABLE ACCESS,FULL,TAX_CASE,25,14"
    )
    result = execution_plan.analyze(text, expected_cost=14)
    full_scan = next(item for item in result.observations if item.code == "TABLE_ACCESS_FULL")
    assert full_scan.level == "fact"
    assert "CREATE INDEX" not in full_scan.detail
    assert "建議建立" not in full_scan.detail
    assert "正式機" not in full_scan.detail
    # The observation states the plan fact and explicitly disclaims it being a
    # defect; it never tells the reviewer to add an index.
    assert "不代表" in full_scan.detail


def test_cardinality_gap_evidence_does_not_claim_broken_statistics():
    result = execution_plan.analyze(ACTUAL_PLAN, expected_cost=88)
    gap = next(item for item in result.observations if item.code == "CARDINALITY_GAP")
    assert gap.level == "review"
    assert "錯誤" not in gap.detail
    assert "10" in gap.detail


def test_unrecognized_text_fails_closed_without_inventing_plan_facts():
    result = execution_plan.analyze("這不是執行計畫", expected_cost=100)
    assert result.recognized is False
    assert result.source == "unknown"
    assert result.steps == []
    assert result.observations == []



def test_build_ai_context_is_bounded_and_literal_free():
    plan = execution_plan.analyze(ACTUAL_PLAN, expected_cost=88)
    context = execution_plan.build_ai_context(plan, allowed_tables={"TAX_CASE"})

    assert context is not None
    assert context["source"] == "actual"
    assert context["plan_cost"] == 88
    assert context["has_runtime_stats"] is True
    assert context["priority_steps"][0]["object_name"] == "TAX_CASE"
    assert context["priority_steps"][0]["filter_functions"] == ["TRUNC"]

    serialized = str(context)
    assert "2026-09-20" not in serialized
    assert "CASE_DATE" not in serialized
    assert "Plan hash value" not in serialized
    assert "8h4m1abcxyz12" not in serialized


def test_build_ai_context_hides_objects_not_already_present_in_sql():
    plan_text = """
Id,Operation,Options,Object_Name,Cardinality,Cost
0,SELECT STATEMENT,,,10,100
1,TABLE ACCESS,FULL,TAX_CASE,10,90
2,INDEX,RANGE SCAN,SECRET_INTERNAL_INDEX,10,80
"""
    plan = execution_plan.analyze(plan_text, expected_cost=100)
    context = execution_plan.build_ai_context(plan, allowed_tables={"TAX_CASE"})

    assert context is not None
    steps = context["priority_steps"]
    assert any(step["object_name"] == "TAX_CASE" for step in steps)
    assert all(step["object_name"] != "SECRET_INTERNAL_INDEX" for step in steps)
