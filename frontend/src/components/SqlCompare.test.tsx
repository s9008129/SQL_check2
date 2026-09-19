import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import SqlCompare from "./SqlCompare";
import { makeAi } from "../test/fixtures";

describe("SqlCompare — merged suggestion/adoption block", () => {
  it("hides the block when there is no concrete SQL to compare", () => {
    const { container } = render(
      <SqlCompare
        originalSql="SELECT 1 FROM DUAL"
        ai={makeAi({
          advice: [{ title: "確認查詢範圍", explanation: "請確認範圍。", example: null, impact: "low" }],
          suggested_sql: { available: false, reason: "目前未發現需要調整的寫法。", sql: null, outcome: "not_needed" },
        })}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows one 建議寫法 block with an 已確認 badge for a verified full rewrite", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.C = '1' OR A.C = '2'"
        ai={makeAi({
          advice: [],
          suggested_sql: {
            available: true,
            reason: "可提供改寫。",
            sql: "SELECT A.X FROM T A WHERE A.C IN ('1','2')",
            outcome: "provided",
          },
        })}
      />,
    );
    expect(screen.getByText("建議寫法")).toBeTruthy();
    expect(screen.getByText("已確認")).toBeTruthy();
    expect(screen.getByRole("table", { name: "原寫法與已確認建議寫法逐行對照" })).toBeTruthy();
    expect(screen.queryByText("建議採用狀態")).toBeNull();
  });

  it("hides unverified fragments even if an old API response still contains one", () => {
    const { container } = render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.NAME LIKE '%明'"
        ai={makeAi({
          advice: [
            {
              title: "評估 LIKE 比對方式",
              explanation: "先確認實際比對需求。",
              before: "A.NAME LIKE '%明'",
              example: "A.NAME LIKE '明%'",
              impact: "low",
              verification: "unverified",
            },
          ],
          suggested_sql: { available: false, reason: "需確認比對需求。", sql: null, outcome: "advice_only" },
        })}
      />,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByText("A.NAME LIKE '明%'")).toBeNull();
  });

  it("shows verified advice fragments in the concise 寫法對照 block", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.C = '1' OR A.C = '2'"
        ai={makeAi({
          advice: [
            {
              title: "合併相同欄位條件",
              explanation: "可改成 IN。",
              before: "A.C = '1' OR A.C = '2'",
              example: "A.C IN ('1','2')",
              impact: "low",
              verification: "verified",
            },
          ],
          suggested_sql: { available: false, reason: "局部建議。", sql: null, outcome: "advice_only" },
        })}
      />,
    );
    expect(screen.getByText("寫法對照")).toBeTruthy();
    expect(screen.getByText("建議寫法（已確認）")).toBeTruthy();
    expect(screen.queryByText(/每一項建議都會標示/)).toBeNull();
  });
});
