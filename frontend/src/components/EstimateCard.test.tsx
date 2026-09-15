import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import EstimateCard from "./EstimateCard";
import { makeAi } from "../test/fixtures";

describe("EstimateCard", () => {
  it("renders the percentage when a value is present", () => {
    render(<EstimateCard ai={makeAi({ estimated_improvement_pct: 45 })} />);
    expect(screen.getByText("45%")).toBeTruthy();
  });

  it("shows the fixed not-available copy when estimated_improvement_pct is null", () => {
    render(<EstimateCard ai={makeAi({ estimated_improvement_pct: null })} />);
    expect(screen.getByText("本次不提供效能改善幅度預估")).toBeTruthy();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("shows the pending copy while ai.status is pending", () => {
    render(
      <EstimateCard
        ai={makeAi({ status: "pending", advice: [], suggested_sql: null, estimated_improvement_pct: null })}
      />,
    );
    expect(screen.getByText("AI 分析中，約需數十秒。")).toBeTruthy();
  });

  it("shows the fixed unavailable copy when ai.status is unavailable", () => {
    render(
      <EstimateCard
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
});
