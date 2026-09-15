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
  it("always renders the original SQL", () => {
    render(<SqlCompare originalSql="SELECT 1 FROM DUAL;" cost={68420} ai={makeAi()} />);
    expect(screen.getByTestId("sql-editor-原始 SQL")).toBeTruthy();
    expect(screen.getByText("COST 68,420")).toBeTruthy();
  });

  it("renders the suggested SQL editor when a suggestion is available", () => {
    render(<SqlCompare originalSql="SELECT 1 FROM DUAL;" cost={68420} ai={makeAi()} />);
    expect(screen.getByTestId("sql-editor-建議寫法")).toBeTruthy();
  });

  it("shows the fixed not-available-by-design message when suggested_sql.available is false", () => {
    render(
      <SqlCompare
        originalSql="UPDATE T SET X = 1;"
        cost={68420}
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
        cost={68420}
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
        cost={68420}
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
        cost={68420}
        ai={makeAi({ status: "pending", advice: [], suggested_sql: null, estimated_improvement_pct: null })}
      />,
    );
    expect(screen.getByText("AI 分析中，約需數十秒。")).toBeTruthy();
    expect(screen.queryByText("複製")).toBeNull();
  });
});
