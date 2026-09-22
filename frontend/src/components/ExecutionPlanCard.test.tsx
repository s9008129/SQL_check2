import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import ExecutionPlanCard from "./ExecutionPlanCard";
import type { ExecutionPlanAnalysis } from "../types/api";

const plan: ExecutionPlanAnalysis = {
  recognized: true,
  source: "actual",
  source_label: "測試機實際執行計畫",
  plan_hash_value: "123456789",
  sql_id: "abc123xyz",
  step_count: 2,
  plan_cost: 88,
  cost_matches_input: true,
  has_runtime_stats: true,
  runtime_metrics: [{ key: "consistent_gets", label: "Consistent gets", value: 2000 }],
  steps: [
    {
      id: 0,
      operation: "SELECT STATEMENT",
      options: null,
      object_name: null,
      estimated_rows: null,
      actual_rows: 1000,
      starts: 1,
      cost: 88,
      buffers: 2000,
      reads: 3,
      actual_time: "00:00:01",
      access_predicates: [],
      filter_predicates: [],
    },
    {
      id: 1,
      operation: "TABLE ACCESS FULL",
      options: null,
      object_name: "TAX_CASE",
      estimated_rows: 10,
      actual_rows: 1000,
      starts: 1,
      cost: 88,
      buffers: 2000,
      reads: 3,
      actual_time: "00:00:01",
      access_predicates: [],
      filter_predicates: ['TRUNC("A"."CASE_DATE")=DATE'],
    },
  ],
  observations: [
    {
      code: "CARDINALITY_GAP",
      level: "review",
      title: "估計列數與實際列數差距較大",
      detail: "Step 1：E-Rows 10，A-Rows/Start 約 1,000。",
      step_id: 1,
    },
  ],
  message: "已辨識測試機實際執行計畫／執行統計。",
};

test("renders actual test-plan evidence without calling it production truth", () => {
  render(<ExecutionPlanCard plan={plan} />);

  expect(screen.getByText("測試機實際執行計畫")).toBeInTheDocument();
  expect(screen.getByText("Consistent gets")).toBeInTheDocument();
  expect(screen.getByText("估計列數與實際列數差距較大")).toBeInTheDocument();
  expect(screen.getByText(/不代表正式機一定採用相同 Plan/)).toBeInTheDocument();
});

test("renders a safe unrecognized state", () => {
  render(
    <ExecutionPlanCard
      plan={{
        ...plan,
        recognized: false,
        source: "unknown",
        source_label: "執行計畫格式待確認",
        step_count: 0,
        steps: [],
        observations: [],
        runtime_metrics: [],
        message: "未辨識到可解析的 Oracle 執行計畫表格。",
      }}
    />,
  );

  expect(screen.getByText("格式待確認")).toBeInTheDocument();
  expect(screen.getByText(/SQL 規則檢核仍然有效/)).toBeInTheDocument();
});

// SQL Developer's PLAN_TABLE grid / CSV export splits the access path into
// OPERATION ("TABLE ACCESS") and OPTIONS ("FULL"); the backend merges them for
// detection, and the UI must show the same single observable operation.
test("renders SQL Developer OPERATION + OPTIONS as one merged operation", () => {
  render(
    <ExecutionPlanCard
      plan={{
        ...plan,
        steps: [
          plan.steps[0],
          {
            ...plan.steps[1],
            operation: "TABLE ACCESS",
            options: "FULL",
          },
        ],
      }}
    />,
  );

  const mergedCell = screen.getByText("TABLE ACCESS FULL");
  expect(mergedCell.textContent).toBe("TABLE ACCESS FULL");

  const selectStatementCell = screen.getByText("SELECT STATEMENT");
  expect(selectStatementCell.textContent).toBe("SELECT STATEMENT");
  expect(screen.queryByText("null")).toBeNull();
});

test("merges INDEX + RANGE SCAN without inventing extra text", () => {
  render(
    <ExecutionPlanCard
      plan={{
        ...plan,
        steps: [{ ...plan.steps[1], operation: "INDEX", options: "RANGE SCAN" }],
      }}
    />,
  );

  expect(screen.getByText("INDEX RANGE SCAN")).toBeInTheDocument();
});
