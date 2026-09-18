import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ImprovementAdvice from "./ImprovementAdvice";
import { makeAi } from "../test/fixtures";

describe("ImprovementAdvice", () => {
  it("renders advice cards when ai.status is ok", () => {
    render(<ImprovementAdvice ai={makeAi()} />);
    expect(screen.getByText("日期條件可再簡化")).toBeTruthy();
    expect(
      screen.getByText("目前使用 TRUNC() 比對日期，可評估改成日期範圍。"),
    ).toBeTruthy();
  });

  it("labels opportunity separately from adoption safety", () => {
    render(
      <ImprovementAdvice
        ai={makeAi({
          advice: [
            {
              title: "合併同欄位 OR",
              explanation: "可改成較精簡的 IN 寫法。",
              before: "A.C = '1' OR A.C = '2'",
              example: "A.C IN ('1','2')",
              impact: "medium",
              verification: "verified",
            },
            {
              title: "確認關聯條件",
              explanation: "請先確認兩張表正確的關聯欄位。",
              example: null,
              impact: "high",
            },
          ],
        })}
      />,
    );
    expect(screen.getByText("改善機會：中")).toBeTruthy();
    expect(screen.getByText("改善機會：高")).toBeTruthy();
    expect(screen.getByText("查詢結果已確認")).toBeTruthy();
    expect(screen.getByText("需先確認")).toBeTruthy();
    expect(screen.queryByText(/影響：/)).toBeNull();
  });

  it("shows the pending copy while ai.status is pending", () => {
    render(
      <ImprovementAdvice
        ai={makeAi({ status: "pending", advice: [], suggested_sql: null, estimated_improvement_pct: null })}
      />,
    );
    expect(screen.getByText("AI 分析中，約需數十秒。")).toBeTruthy();
  });

  it("shows the fixed unavailable message when ai.status is unavailable", () => {
    render(
      <ImprovementAdvice
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
  });

  it("falls back to the same fixed unavailable text if the backend sends no message", () => {
    render(
      <ImprovementAdvice
        ai={makeAi({
          status: "unavailable",
          advice: [],
          suggested_sql: null,
          estimated_improvement_pct: null,
          message: null,
        })}
      />,
    );
    expect(
      screen.getByText("智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。"),
    ).toBeTruthy();
  });
});
