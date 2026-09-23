import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import ExecutionPlanCard from "./ExecutionPlanCard";
import type { ExecutionPlanAnalysis } from "../types/api";

const plan: ExecutionPlanAnalysis = {
  recognized: true,
  source: "actual",
  source_label: "含實際執行統計的執行計畫",
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
  message: "已辨識含實際執行統計的 Plan。",
};

test("renders runtime evidence without inventing its source environment", () => {
  render(<ExecutionPlanCard plan={plan} />);

  expect(screen.getByText("含實際統計")).toBeInTheDocument();
  expect(screen.getByText("Consistent gets")).toBeInTheDocument();
  expect(screen.getByText("預估筆數和實際筆數差很多")).toBeInTheDocument();
  expect(screen.getByText(/這份 SQL Developer 執行計畫含實際統計/)).toBeInTheDocument();
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
  expect(screen.getByText(/請貼上 SQL Developer F10 的完整執行計畫/)).toBeInTheDocument();
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

test("renders formal-database F10 as estimated evidence, not runtime proof", () => {
  render(
    <ExecutionPlanCard
      plan={{
        ...plan,
        source: "estimated",
        source_label: "正式資料庫 F10 Explain Plan（估算）",
        has_runtime_stats: false,
        runtime_metrics: [],
        message:
          "已辨識正式資料庫 F10 Explain Plan（估算）。這反映正式庫 Optimizer 在 Explain 當下選出的預估路徑。",
      }}
    />,
  );

  expect(screen.getByText("SQL Developer F10｜估算")).toBeInTheDocument();
  expect(screen.getByText(/SQL Developer 的 F10 Explain Plan/)).toBeInTheDocument();
  expect(screen.getByText(/F10 是估算結果，適合用來比較改寫前後的執行方式/)).toBeInTheDocument();
  expect(screen.queryByText(/Optimizer|I\/O|不代表 SQL 已實際執行/)).toBeNull();
});


test("shows only the top three cost steps first and keeps technical details collapsible", () => {
  render(
    <ExecutionPlanCard
      plan={{
        ...plan,
        source: "estimated",
        has_runtime_stats: false,
        runtime_metrics: [],
        steps: [
          { ...plan.steps[0], id: 0, cost: 1000, actual_rows: null, buffers: null },
          {
            ...plan.steps[1],
            id: 1,
            operation: "SORT",
            options: "ORDER BY",
            object_name: null,
            cost: 900,
            estimated_rows: 100,
            actual_rows: null,
            buffers: null,
          },
          {
            ...plan.steps[1],
            id: 2,
            operation: "HASH",
            options: "UNIQUE",
            object_name: null,
            cost: 800,
            estimated_rows: 100,
            actual_rows: null,
            buffers: null,
          },
          {
            ...plan.steps[1],
            id: 3,
            operation: "TABLE ACCESS",
            options: "FULL",
            object_name: "TAX_CASE",
            cost: 700,
            estimated_rows: 5000,
            actual_rows: null,
            buffers: null,
          },
          {
            ...plan.steps[1],
            id: 4,
            operation: "INDEX",
            options: "RANGE SCAN",
            object_name: "IDX_CASE",
            cost: 100,
            estimated_rows: 10,
            actual_rows: null,
            buffers: null,
          },
        ],
      }}
    />,
  );

  const priorityList = screen.getByTestId("plan-priority-list");
  expect(priorityList.textContent).toContain("排序資料");
  expect(priorityList.textContent).toContain("移除重複資料");
  expect(priorityList.textContent).toContain("讀取整張表");
  expect(priorityList.textContent).not.toContain("使用索引找資料");
  expect(screen.getByText("Top 3")).toBeInTheDocument();
  expect(screen.getByText("查看完整技術明細（進階）")).toBeInTheDocument();
});
