import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import EstimateCard from "./EstimateCard";
import { makeAi } from "../test/fixtures";

const pass = { status: "PASS" as const, label: "符合中心規範", notice_count: 0, block_count: 0 };
const block = { status: "BLOCK" as const, label: "不符合中心規範", notice_count: 0, block_count: 1 };

describe("EstimateCard — 建議採用狀態", () => {
  it("renames the old predicted-effect card and never shows a high/medium/low performance gauge", () => {
    render(
      <EstimateCard
        compliance={pass}
        ai={makeAi({
          improvement_potential: "low",
          improvement_potential_basis: ["規則檢核：1 項提醒"],
          suggested_sql: { available: false, reason: "需確認。", sql: null, outcome: "advice_only" },
        })}
      />,
    );
    expect(screen.getByText("建議採用狀態")).toBeTruthy();
    expect(screen.queryByText("預估改善效果")).toBeNull();
    expect(screen.queryByText("改善空間有限，或改法尚需人工確認。")).toBeNull();
    expect(screen.getByTestId("adoption-confirm-first").textContent).toContain("請先確認");
  });

  it("shows a deterministic confirmed state when a rewrite passed server verification", () => {
    render(
      <EstimateCard
        compliance={pass}
        ai={makeAi({
          improvement_potential: "medium",
          improvement_potential_basis: ["已提供整段建議寫法，系統已確認查詢結果不變"],
          suggested_sql: {
            available: true,
            reason: "系統可確認。",
            sql: "SELECT A.ID FROM T A WHERE A.C IN ('1','2')",
            outcome: "provided",
          },
        })}
      />,
    );
    const note = screen.getByTestId("adoption-confirmed");
    expect(note.textContent).toContain("系統確認");
    expect(note.textContent).toContain("實際執行效率");
  });

  it("does not tell a BLOCK case that improvement space is limited", () => {
    render(
      <EstimateCard
        compliance={block}
        ai={makeAi({
          improvement_potential: "low",
          improvement_potential_basis: ["規則檢核：1 項不符合"],
          advice: [{ title: "確認查詢範圍", explanation: "請確認實際需求。", example: null, impact: "high" }],
          suggested_sql: { available: false, reason: "需確認查詢範圍。", sql: null, outcome: "advice_only" },
        })}
      />,
    );
    const note = screen.getByTestId("adoption-blocked");
    expect(note.textContent).toContain("需要優先處理");
    expect(note.textContent).toContain("不會自行猜測");
    expect(note.textContent).not.toContain("改善空間有限");
  });

  it("renders governance-only reminders as confirmation-first, not as clean SQL", () => {
    render(
      <EstimateCard
        compliance={pass}
        ai={makeAi({
          improvement_potential: "notice_only",
          improvement_potential_basis: ["規則檢核：1 項提醒（重要資料表）"],
          advice: [],
          suggested_sql: { available: false, reason: "請確認。", sql: null, outcome: "advice_only" },
        })}
      />,
    );
    const note = screen.getByTestId("adoption-notice-only");
    expect(note.textContent).toContain("有提醒事項");
    expect(note.textContent).not.toContain("目前未發現需要調整");
  });

  it("uses a simple clean-state message when nothing was found", () => {
    render(
      <EstimateCard
        compliance={pass}
        ai={makeAi({
          advice: [],
          improvement_potential: null,
          improvement_potential_basis: [],
          suggested_sql: { available: false, reason: "目前未發現需要調整的寫法。", sql: null, outcome: "not_needed" },
        })}
      />,
    );
    expect(screen.getByTestId("adoption-none").textContent).toContain("目前未發現需要調整");
  });

  it("shows pending and unavailable states", () => {
    const { unmount } = render(
      <EstimateCard compliance={pass} ai={makeAi({ status: "pending", advice: [], suggested_sql: null })} />,
    );
    expect(screen.getByText("AI 分析中，約需數十秒。")).toBeTruthy();
    unmount();

    render(
      <EstimateCard
        compliance={pass}
        ai={makeAi({
          status: "unavailable",
          advice: [],
          suggested_sql: null,
          message: "智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。",
        })}
      />,
    );
    expect(screen.getByText(/智慧改善建議目前暫時無法使用/)).toBeTruthy();
  });
});
