import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ImprovementAdvice from "./ImprovementAdvice";
import { makeAi } from "../test/fixtures";

describe("ImprovementAdvice", () => {
  it("renders advice cards when ai.status is ok", () => {
    render(<ImprovementAdvice ai={makeAi()} />);
    expect(screen.getByText(/智慧改善建議/)).toBeTruthy();
    expect(screen.getByText("日期條件可再簡化")).toBeTruthy();
    expect(
      screen.getByText("目前使用 TRUNC() 比對日期，可評估改成日期範圍。"),
    ).toBeTruthy();
  });

  it("shows evidence labels instead of the model's subjective impact level", () => {
    render(
      <ImprovementAdvice
        ai={makeAi({
          advice: [
            {
              title: "可確認改寫",
              explanation: "系統已有確定性規則。",
              before: "A.STATUS = 'A' OR A.STATUS = 'B'",
              example: "A.STATUS IN ('A', 'B')",
              impact: "high",
              verification: "verified",
            },
            {
              title: "需要確認",
              explanation: "改法需要額外前提。",
              before: "TRUNC(A.DT) = :D",
              example: "A.DT >= :D AND A.DT < :D + 1",
              impact: "low",
              verification: "unverified",
            },
            {
              title: "治理提醒",
              explanation: "請確認查詢範圍。",
              example: null,
              impact: "high",
            },
          ],
        })}
      />,
    );
    expect(screen.getByText("已確認")).toBeTruthy();
    expect(screen.getByText("需確認")).toBeTruthy();
    expect(screen.getByText("提醒")).toBeTruthy();
    expect(screen.queryByText("影響：高")).toBeNull();
    expect(screen.queryByText("影響：低")).toBeNull();
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


it("does not repeat the AI summary when detailed advice cards are visible", () => {
  render(<ImprovementAdvice ai={makeAi({ summary: "這句摘要不應重複顯示。" })} />);
  expect(screen.queryByText("這句摘要不應重複顯示。")).toBeNull();
  expect(screen.getByText("AI 建議僅供參考，採用前請先測試。")).toBeTruthy();
});


it("never renders copyable SQL for an unverified advice item", () => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        advice: [
          {
            title: "評估 LIKE 比對方式",
            explanation: "請先確認實際比對需求。",
            before: "A.NAME LIKE '%明'",
            example: "A.NAME LIKE '明%'",
            impact: "low",
            verification: "unverified",
          },
        ],
      })}
    />,
  );
  expect(screen.getByText("需確認")).toBeTruthy();
  expect(screen.queryByText("A.NAME LIKE '明%'")).toBeNull();
});
