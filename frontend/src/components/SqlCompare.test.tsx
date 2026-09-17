import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// SqlCompare's own job is choosing WHICH panel/message to show; whether
// CodeMirror itself mounts correctly is SqlEditor's concern (exercised by
// `npm run build` + manual QA). Mocking it here keeps this test focused
// and avoids depending on jsdom's incomplete text-layout measurement.
vi.mock("./SqlEditor", () => ({
  default: ({ value, ariaLabel }: { value: string; ariaLabel?: string }) => (
    <div data-testid={`sql-editor-${ariaLabel ?? "editor"}`}>{value}</div>
  ),
}));

import SqlCompare from "./SqlCompare";
import { makeAi } from "../test/fixtures";

describe("SqlCompare", () => {
  it("shows only a verdict note (no editor panes) when there is no full rewrite", () => {
    render(
      <SqlCompare
        originalSql="SELECT 1 FROM DUAL;"
       
        ai={makeAi({ advice: [], suggested_sql: { available: false, reason: "r", sql: null, outcome: "not_needed" } })}
      />,
    );
    expect(screen.queryByTestId("sql-editor-原始 SQL")).toBeNull();
    expect(screen.getByTestId("compare-verdict").textContent).toContain("不需要改寫");
  });

  it("shows the aligned diff without repeating the COST when there is a full rewrite", () => {
    render(<SqlCompare originalSql="SELECT 1 FROM DUAL;" ai={makeAi()} />);
    expect(screen.getByRole("table", { name: "原始 SQL 與 AI 建議寫法逐行對照" })).toBeTruthy();
    expect(screen.queryByText(/COST/)).toBeNull();
    expect(screen.queryByText("複製建議寫法")).toBeNull();
  });

  it("is titled 優化前後比較 and labels the right-hand side as AI 建議寫法", () => {
    render(<SqlCompare originalSql="SELECT 1 FROM DUAL;" ai={makeAi()} />);
    expect(screen.getByText("優化前後比較")).toBeTruthy();
    expect(screen.queryByText("SQL 寫法比較")).toBeNull();
    expect(screen.getAllByText("AI 建議寫法").length).toBeGreaterThan(0);
  });

  it("renders a line-aligned word-highlighted diff when a suggestion is available", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE TRUNC(A.D) = :X"
       
        ai={makeAi({
          suggested_sql: { available: true, reason: "r", sql: "SELECT A.X FROM T A WHERE A.D >= :X AND A.D < :X + 1", outcome: "provided" },
        })}
      />,
    );
    expect(screen.getByRole("table", { name: "原始 SQL 與 AI 建議寫法逐行對照" })).toBeTruthy();
    const marks = document.querySelectorAll("mark.diff-add");
    expect(marks.length).toBeGreaterThan(1); // legend + at least one real change
  });

  it("shows the red warning that suggestions must be tested first", () => {
    render(<SqlCompare originalSql="SELECT 1 FROM DUAL;" ai={makeAi()} />);
    expect(screen.getByRole("note").textContent).toContain("測試機");
  });

  it("lists every advice fragment as its own before/after diff when only advice is given", () => {
    render(
      <SqlCompare
        originalSql="select a\nfrom t w\nwhere substr(w.coll_b_date, 1, 3) = '107'\n  and w.tax_cd||w.subtax_cd = '551'"
       
        ai={makeAi({
          advice: [
            {
              title: "改為範圍比對",
              explanation: "e",
              before: "substr(w.coll_b_date, 1, 3) = '107'",
              example: "w.coll_b_date >= '107' AND w.coll_b_date < '108'",
              impact: "high",
            },
            { title: "拆分串接", explanation: "e", example: "w.tax_cd = '55' AND w.subtax_cd = '1'", impact: "medium", before: null },
            { title: "確認查詢範圍", explanation: "e", example: null, impact: "low", before: null },
          ],
          suggested_sql: { available: false, reason: "需業務確認。", sql: null, outcome: "advice_only" },
        })}
      />,
    );
    const blocks = screen.getAllByTestId("fragment-diff");
    expect(blocks).toHaveLength(2); // the prose-only advice has no fragment
    expect(blocks[0].textContent).toContain("原寫法");
    expect(blocks[0].querySelectorAll("mark.diff-add").length).toBeGreaterThan(0);
    // second item had no `before`: located heuristically from the original
    expect(blocks[1].textContent).toContain("tax_cd");
  });

  it("splits a business-assumption prefix out of the example into a note", () => {
    render(
      <SqlCompare
        originalSql="select a from t w where w.tax_cd||w.subtax_cd = '551'"
       
        ai={makeAi({
          advice: [
            {
              title: "拆分串接",
              explanation: "e",
              before: "w.tax_cd||w.subtax_cd = '551'",
              example: "若 tax_cd 為 2 碼：w.tax_cd = '55' AND w.subtax_cd = '1'",
              impact: "high",
            },
          ],
          suggested_sql: { available: false, reason: "r", sql: null, outcome: "advice_only" },
        })}
      />,
    );
    const block = screen.getByTestId("fragment-diff");
    expect(block.textContent).toContain("前提：若 tax_cd 為 2 碼");
    expect(block.querySelector(".fragment-after code")?.textContent).not.toContain("若");
  });

  it("shows the positive 'not needed' message when outcome is not_needed", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.Y = 1"
       
        ai={makeAi({
          suggested_sql: { available: false, reason: "目前寫法已良好。", sql: null, outcome: "not_needed" },
        })}
      />,
    );
    expect(screen.getByText("AI 檢視後認為目前寫法已良好，本次不需要改寫。")).toBeTruthy();
    expect(screen.queryByText("為避免改變原本查詢內容，本次先提供改善方向，不自動產生建議寫法。")).toBeNull();
  });

  it("shows the advice-only message plus the reason when outcome is advice_only", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.C||A.D = '551'"
       
        ai={makeAi({
          suggested_sql: { available: false, reason: "需確認切分方式。", sql: null, outcome: "advice_only" },
        })}
      />,
    );
    expect(screen.getByText(/改善方向請見上方/)).toBeTruthy();
    expect(screen.getByText("需確認切分方式。")).toBeTruthy();
  });

  it("shows the fixed not-available-by-design message when suggested_sql.available is false", () => {
    render(
      <SqlCompare
        originalSql="UPDATE T SET X = 1;"
       
        ai={makeAi({
          suggested_sql: {
            available: false,
            reason: "MVP 只允許 SELECT 建議寫法。",
            sql: null,
          },
        })}
      />,
    );
    expect(
      screen.getByText("為避免改變原本查詢內容，本次先提供改善方向，不自動產生建議寫法。"),
    ).toBeTruthy();
    expect(screen.queryByTestId("sql-editor-建議寫法")).toBeNull();
  });

  it("does not duplicate the fixed message when the backend's own reason equals it verbatim", () => {
    // Real backend behavior (ai_service.py's server-side override / safety
    // re-validation) sets `reason` to this exact fixed copy when *it*
    // declines, not the model — rendering it a second time as a "reason"
    // line would show the same sentence twice in a row (caught via a live
    // browser E2E run against the real backend, not by a unit test using
    // an arbitrary different mock reason string).
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.Y = 1;"
       
        ai={makeAi({
          suggested_sql: {
            available: false,
            reason: "為避免改變原本查詢內容，本次先提供改善方向，不自動產生建議寫法。",
            sql: null,
          },
        })}
      />,
    );
    expect(
      screen.getAllByText("為避免改變原本查詢內容，本次先提供改善方向，不自動產生建議寫法。"),
    ).toHaveLength(1);
  });

  it("shows the fixed AI-unavailable message when ai.status is unavailable — a different message from the not-available-by-design one", () => {
    render(
      <SqlCompare
        originalSql="SELECT 1 FROM DUAL;"
       
        ai={makeAi({
          status: "unavailable",
          advice: [],
          suggested_sql: null,
          estimated_improvement_pct: null,
          message: "智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。",
        })}
      />,
    );
    expect(
      screen.getByText("智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。"),
    ).toBeTruthy();
    expect(
      screen.queryByText("為避免改變原本查詢內容，本次先提供改善方向，不自動產生建議寫法。"),
    ).toBeNull();
  });

  it("shows the pending copy while ai.status is pending, with no copy button", () => {
    render(
      <SqlCompare
        originalSql="SELECT 1 FROM DUAL;"
       
        ai={makeAi({ status: "pending", advice: [], suggested_sql: null, estimated_improvement_pct: null })}
      />,
    );
    expect(screen.getByText("AI 分析中，約需數十秒。")).toBeTruthy();
    expect(screen.queryByText("複製")).toBeNull();
  });
});
