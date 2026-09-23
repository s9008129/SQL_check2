import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, expect, test, vi } from "vitest";
import App from "./App";
import { analyze, extractSql } from "./api/client";
import { makeAi, makeResult } from "./test/fixtures";
import type { AnalyzeRequest, ExecutionPlanAnalysis } from "./types/api";

// The real client is replaced here so this integration test stays
// deterministic and offline: it exercises App's wiring (upload → plan textarea
// → two-pass /api/analyze → ExecutionPlanCard), not HTTP behaviour.
vi.mock("./api/client", () => ({
  ApiError: class ApiError extends Error {},
  analyze: vi.fn(),
  extractSql: vi.fn(),
  extractPlan: vi.fn(),
  fetchHealth: vi.fn(),
}));

// A synthetic SQL Developer PLAN_TABLE grid export: OPERATION and OPTIONS are
// separate columns, exactly as SQL Developer writes them.
const PLAN_TEXT = [
  "Id,Operation,Options,Object_Name,Cardinality,Cost",
  "0,SELECT STATEMENT,,,25,14",
  "1,TABLE ACCESS,FULL,TAX_CASE,25,14",
].join("\n");

const PLAN_EVIDENCE: ExecutionPlanAnalysis = {
  recognized: true,
  source: "estimated",
  source_label: "正式資料庫 F10 Explain Plan（估算）",
  plan_hash_value: null,
  sql_id: null,
  step_count: 2,
  plan_cost: 14,
  cost_matches_input: true,
  has_runtime_stats: false,
  runtime_metrics: [],
  steps: [
    {
      id: 0,
      operation: "SELECT STATEMENT",
      options: null,
      object_name: null,
      estimated_rows: 25,
      actual_rows: null,
      starts: null,
      cost: 14,
      buffers: null,
      reads: null,
      actual_time: null,
      access_predicates: [],
      filter_predicates: [],
    },
    {
      id: 1,
      operation: "TABLE ACCESS",
      options: "FULL",
      object_name: "TAX_CASE",
      estimated_rows: 25,
      actual_rows: null,
      starts: null,
      cost: 14,
      buffers: null,
      reads: null,
      actual_time: null,
      access_predicates: [],
      filter_predicates: ["TRUNC(A.CASE_DATE)=DATE_VALUE"],
    },
  ],
  observations: [
    {
      code: "TABLE_ACCESS_FULL",
      level: "fact",
      title: "正式 Plan 包含 TABLE ACCESS FULL",
      detail:
        "Step 1 TAX_CASE 使用 TABLE ACCESS FULL。這是提供的 Plan 事實，本身不代表一定需要改成索引存取。",
      step_id: 1,
    },
  ],
  message: "已辨識正式資料庫 F10 Explain Plan（估算）。這反映正式庫 Optimizer 在 Explain 當下選出的預估路徑；F10 不代表 SQL 已實際執行。",
};

beforeAll(() => {
  // jsdom has no layout, so the result-section scroll App performs after the
  // first pass would otherwise throw.
  Element.prototype.scrollIntoView = vi.fn();
});

test("plan upload → analyze → card keeps the plan factual and out of the AI section", async () => {
  vi.mocked(extractSql).mockResolvedValueOnce({
    status: "ok",
    filename: "q.sql",
    sql: "SELECT A.X FROM TAX_CASE A WHERE TRUNC(A.CASE_DATE) = :D",
    statement_count: 1,
    needs_confirmation: false,
    message: "已讀取 SQL。",
  });

  const deterministicPass = makeResult({
    execution_plan: PLAN_EVIDENCE,
    ai: makeAi({ status: "pending", summary: null, advice: [], suggested_sql: null }),
  });
  const aiPass = makeResult({ execution_plan: PLAN_EVIDENCE, ai: makeAi() });
  vi.mocked(analyze).mockImplementation(async (body: AnalyzeRequest) =>
    body.include_ai ? aiPass : deterministicPass,
  );

  render(<App />);

  fireEvent.change(screen.getByLabelText(/申請單號/), { target: { value: "115000218" } });
  fireEvent.change(screen.getByLabelText(/COST/), { target: { value: "14" } });

  // The SQL editor is CodeMirror; filling it through the (real) attachment
  // path keeps this test on the same user journey without simulating typing.
  const sqlFileInput = document.querySelector('input[accept*=".docx"]') as HTMLInputElement;
  fireEvent.change(sqlFileInput, {
    target: { files: [new File(["SELECT 1"], "q.sql", { type: "text/plain" })] },
  });
  await waitFor(() => expect(screen.getByText(/已讀取 SQL/)).toBeInTheDocument());

  fireEvent.change(screen.getByLabelText("SQL Developer 執行計畫"), {
    target: { value: PLAN_TEXT },
  });
  fireEvent.click(screen.getByRole("button", { name: "開始檢核" }));

  await waitFor(() => expect(screen.getByText("TABLE ACCESS FULL")).toBeInTheDocument());

  // Both passes carry the plan: deterministic pass 1 and AI pass 2, no
  // server-side session or plan token store in between.
  const sentBodies = vi.mocked(analyze).mock.calls.map(([body]) => body);
  expect(sentBodies).toHaveLength(2);
  expect(sentBodies[0].include_ai).toBe(false);
  expect(sentBodies[1].include_ai).toBe(true);
  expect(sentBodies[0].execution_plan).toBe(PLAN_TEXT);
  expect(sentBodies[1].execution_plan).toBe(PLAN_TEXT);

  // The UI keeps SQL Developer / F10 context clear, but presents it in
  // business-friendly language instead of showing optimizer jargon first.
  expect(screen.getByText("SQL Developer F10｜估算")).toBeInTheDocument();
  expect(screen.getByText(/SQL Developer 的 F10 Explain Plan/)).toBeInTheDocument();
  expect(screen.getByText("讀取整張表")).toBeInTheDocument();
  expect(screen.queryByText(/Optimizer|I\/O/)).toBeNull();
  expect(screen.getAllByText("日期條件可再簡化").length).toBeGreaterThan(0);

  // The raw plan stays in the input textarea; neither the AI advice nor any
  // other part of the result area renders the raw plan text.
  expect((screen.getByLabelText("SQL Developer 執行計畫") as HTMLTextAreaElement).value).toBe(PLAN_TEXT);
  const resultArea = document.getElementById("resultArea");
  expect(resultArea).not.toBeNull();
  expect(resultArea?.innerHTML).not.toContain("Id,Operation,Options");
  expect(resultArea?.textContent).not.toContain("TABLE ACCESS,FULL");
});
