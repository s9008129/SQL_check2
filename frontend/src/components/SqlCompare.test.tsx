import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import SqlCompare from "./SqlCompare";
import { makeAi } from "../test/fixtures";

describe("SqlCompare — deterministic rewrite diff", () => {
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

  it("shows the full rewrite in a collapsed 完整 SQL details block", () => {
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
    expect(screen.getByText("改寫對照")).toBeTruthy();
    expect(screen.getByText("查詢結果不變")).toBeTruthy();
    expect(screen.getByText("系統已確認這個改法不會改變查詢結果。")).toBeTruthy();
    expect(screen.getByText("完整 SQL")).toBeTruthy();
    expect(screen.getByRole("table", { name: "原寫法與改後寫法逐行對照" })).toBeTruthy();
    expect(screen.getByText("完整 SQL").parentElement?.hasAttribute("open")).toBe(false);
    expect(screen.queryByText("建議採用狀態")).toBeNull();
  });

  it("renders deterministic verified rewrites while AI is pending", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.C = '1' OR A.C = '2'"
        ai={makeAi({ status: "pending", advice: [], suggested_sql: null })}
        verifiedRewrites={[
          {
            statement_index: 0,
            rule: "or_eq_to_in",
            source_rule_id: "R006",
            title: "同欄位 OR 改為 IN",
            before: "A.C = '1' OR A.C = '2'",
            after: "A.C IN ('1', '2')",
          },
        ]}
      />,
    );
    expect(screen.getByText("改寫對照")).toBeTruthy();
    expect(screen.getByText("重點改寫")).toBeTruthy();
    expect(screen.getByText("改後寫法")).toBeTruthy();
  });

  it("renders deterministic verified rewrites while AI is unavailable", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE SUBSTR(A.C, 6, 3) = '551'"
        ai={makeAi({ status: "unavailable", advice: [], suggested_sql: null })}
        verifiedRewrites={[
          {
            statement_index: 0,
            rule: "substr_eq_to_like",
            source_rule_id: "R005",
            title: "SUBSTR 比對改為 LIKE",
            before: "SUBSTR(A.C, 6, 3) = '551'",
            after: "A.C LIKE '_____551%'",
          },
        ]}
      />,
    );
    expect(screen.getByText(/SUBSTR 比對改為 LIKE/)).toBeTruthy();
    expect(screen.getByText("改後寫法")).toBeTruthy();
  });

  it("shows no diff when verified_rewrites is empty and AI has no validated full SQL", () => {
    const { container } = render(
      <SqlCompare
        originalSql="SELECT 1 FROM DUAL"
        ai={makeAi({ status: "pending", advice: [], suggested_sql: null })}
        verifiedRewrites={[]}
      />,
    );
    expect(container.firstChild).toBeNull();
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
    expect(screen.getByText("重點改寫")).toBeTruthy();
    expect(screen.getByText("改後寫法")).toBeTruthy();
    expect(screen.queryByText(/每一項建議都會標示/)).toBeNull();
  });

  it("uses the new compare copy and does not render the retired labels", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.C = '1' OR A.C = '2'"
        ai={makeAi({ advice: [], suggested_sql: { available: true, reason: "改寫。", sql: "SELECT A.X FROM T A WHERE A.C IN ('1','2')" } })}
      />,
    );
    expect(screen.getByText("查詢結果不變")).toBeTruthy();
    expect(screen.getByText("系統已確認這個改法不會改變查詢結果。")).toBeTruthy();
    expect(screen.getByText("改後寫法")).toBeTruthy();
    expect(screen.queryByText("結果相同")).toBeNull();
    expect(screen.queryByText("改後寫法（結果相同）")).toBeNull();
  });

  it("uses only deterministic fragments when the new payload field is present", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.C = '1' OR A.C = '2'"
        ai={makeAi({
          advice: [
            {
              title: "模型重複建議",
              explanation: "可改成 IN。",
              before: "A.C = '1' OR A.C = '2'",
              example: "A.C IN ('1', '2')",
              impact: "medium",
              verification: "verified",
            },
          ],
          suggested_sql: { available: false, reason: "局部建議。", sql: null },
        })}
        verifiedRewrites={[
          {
            statement_index: 0,
            rule: "or_eq_to_in",
            source_rule_id: "R006",
            title: "同欄位 OR 改為 IN",
            before: "A.C = '1' OR A.C = '2'",
            after: "A.C IN ('1', '2')",
          },
        ]}
      />,
    );
    expect(screen.getAllByTestId("fragment-diff")).toHaveLength(1);
  });

  it("does not duplicate differently formatted AI advice when deterministic before text has newlines", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.C = '1' OR A.C = '2'"
        ai={makeAi({
          advice: [
            {
              title: "模型重複建議",
              explanation: "可改成 IN。",
              before: "A.C = '1'\n OR A.C = '2'",
              example: "A.C IN ('1', '2')",
              impact: "medium",
              verification: "verified",
            },
          ],
          suggested_sql: { available: false, reason: "局部建議。", sql: null },
        })}
        verifiedRewrites={[
          {
            statement_index: 0,
            rule: "or_eq_to_in",
            source_rule_id: "R006",
            title: "同欄位 OR 改為 IN",
            before: "A.C = '1' OR A.C = '2'",
            after: "A.C IN ('1', '2')",
          },
        ]}
      />,
    );
    expect(screen.getAllByTestId("fragment-diff")).toHaveLength(1);
  });

  it("does not duplicate differently formatted AI advice when comma spacing differs", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.C = '1' OR A.C = '2'"
        ai={makeAi({
          advice: [
            {
              title: "模型重複建議",
              explanation: "可改成 IN。",
              before: "A.C = '1' OR A.C = '2'",
              example: "A.C IN ('1','2')",
              impact: "medium",
              verification: "verified",
            },
          ],
          suggested_sql: { available: false, reason: "局部建議。", sql: null },
        })}
        verifiedRewrites={[
          {
            statement_index: 0,
            rule: "or_eq_to_in",
            source_rule_id: "R006",
            title: "同欄位 OR 改為 IN",
            before: "A.C = '1' OR A.C = '2'",
            after: "A.C IN ('1', '2')",
          },
        ]}
      />,
    );
    expect(screen.getAllByTestId("fragment-diff")).toHaveLength(1);
  });

  it("keeps a legacy verified AI fragment when verified_rewrites is undefined", () => {
    render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.C = '1' OR A.C = '2'"
        ai={makeAi({
          advice: [
            {
              title: "舊版 AI 建議",
              explanation: "可改成 IN。",
              before: "A.C = '1' OR A.C = '2'",
              example: "A.C IN ('1', '2')",
              impact: "medium",
              verification: "verified",
            },
          ],
          suggested_sql: { available: false, reason: "局部建議。", sql: null },
        })}
      />,
    );
    expect(screen.getAllByTestId("fragment-diff")).toHaveLength(1);
    expect(screen.getByText("1. 舊版 AI 建議")).toBeTruthy();
  });

  it("does not manufacture a deterministic fragment from AI when verified_rewrites is empty", () => {
    const { container } = render(
      <SqlCompare
        originalSql="SELECT A.X FROM T A WHERE A.C = '1' OR A.C = '2'"
        ai={makeAi({
          advice: [
            {
              title: "模型建議",
              explanation: "可改成 IN。",
              before: "A.C = '1' OR A.C = '2'",
              example: "A.C IN ('1', '2')",
              impact: "medium",
              verification: "verified",
            },
          ],
          suggested_sql: { available: false, reason: "局部建議。", sql: null },
        })}
        verifiedRewrites={[]}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("copies the validated full SQL and shows 已複製 temporarily", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
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
    fireEvent.click(screen.getByRole("button", { name: "複製改後 SQL" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("SELECT A.X FROM T A WHERE A.C IN ('1','2')"));
    expect(screen.getByRole("button", { name: "已複製" })).toBeTruthy();
  });
});
