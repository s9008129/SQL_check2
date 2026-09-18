import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import EstimateCard from "./EstimateCard";
import { makeAi } from "../test/fixtures";

describe("EstimateCard (improvement-potential level, 2026-09-17)", () => {
  it("renders the level, its hint, its basis and the caveat, never a percentage", () => {
    const { container } = render(
      <EstimateCard
        ai={makeAi({
          estimated_improvement_pct: 45,
          improvement_potential: "high",
          improvement_potential_basis: ["規則檢核：1 項提醒"],
        })}
      />,
    );
    const block = screen.getByTestId("potential");
    expect(block.textContent).toContain("高");
    expect(block.textContent).toContain("有明確且已確認可行的改善點，建議優先處理。");
    expect(block.textContent).toContain("規則檢核：1 項提醒");
    expect(block.textContent).toContain("此改善等級由程式規則檢核與系統驗證結果推算，未經測試機實際驗證。");
    expect(screen.queryByText(/%/)).toBeNull();
    expect(container.querySelector(".potential-high")).toBeTruthy();
    // 2026-09-17 (evening): the phrase appears exactly once — inside the
    // circle. No 「改善潛力：」 heading, no repeat in the card description,
    // and no head badge.
    expect((container.textContent?.match(/改善潛力/g) ?? []).length).toBe(1);
    expect(container.querySelector(".card-head .badge")).toBeNull();
  });

  it("renders governance-only reminders as a human-confirmation note, never as 「目前寫法良好」", () => {
    const { container } = render(
      <EstimateCard
        ai={makeAi({
          improvement_potential: "notice_only",
          improvement_potential_basis: ["規則檢核：1 項提醒（重要資料表）"],
        })}
      />,
    );
    const note = screen.getByTestId("potential-notice-only");
    expect(note.textContent).toContain("規則檢核有提醒事項，但未確認具體的 SQL 改善點，建議人工確認。");
    expect(note.textContent).toContain("規則檢核：1 項提醒（重要資料表）");
    expect(note.textContent).not.toContain("目前寫法良好");
    // Amber "please confirm" surface, never the green 「良好」 one.
    expect(note.className).toContain("ai-note-notice");
    expect(note.className).not.toContain("ai-note-good");
    expect(container.querySelector(".potential-high")).toBeNull();
    expect(screen.queryByText(/%/)).toBeNull();
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
