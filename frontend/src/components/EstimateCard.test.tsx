import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import EstimateCard from "./EstimateCard";
import { makeAi } from "../test/fixtures";

describe("EstimateCard (improvement-potential level, 2026-09-17)", () => {
  it("renders the level, its basis and the caveat, never a percentage", () => {
    const { container } = render(
      <EstimateCard
        ai={makeAi({
          estimated_improvement_pct: 45,
          improvement_potential: "high",
          improvement_potential_basis: ["規則檢核：1 項提醒", "AI 建議：高影響（系統已確認查詢結果不變）"],
        })}
      />,
    );
    const block = screen.getByTestId("potential");
    expect(block.textContent).toContain("改善潛力：高");
    expect(block.textContent).toContain("規則檢核：1 項提醒");
    expect(block.textContent).toContain("未經任何實際量測");
    expect(block.textContent).toContain("測試機覆核與測試");
    expect(screen.queryByText(/%/)).toBeNull();
    expect(container.querySelector(".potential-high")).toBeTruthy();
  });

  it("says the SQL is fine when no level was derived", () => {
    render(<EstimateCard ai={makeAi({ improvement_potential: null, improvement_potential_basis: [] })} />);
    expect(screen.getByTestId("potential-none").textContent).toContain("目前寫法良好");
    expect(screen.queryByTestId("potential")).toBeNull();
  });

  it("shows the pending copy while ai.status is pending", () => {
    render(
      <EstimateCard
        ai={makeAi({ status: "pending", advice: [], suggested_sql: null, estimated_improvement_pct: null })}
      />,
    );
    expect(screen.getByText("AI 分析中，約需數十秒。")).toBeTruthy();
  });

  it("shows the backend's specific unavailable message when ai.status is unavailable", () => {
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
