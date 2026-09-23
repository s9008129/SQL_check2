import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ResultOverview from "./ResultOverview";
import { makeAi, makeResult } from "../test/fixtures";

describe("ResultOverview", () => {
  it("summarizes a compliant case with advice in plain language", () => {
    render(<ResultOverview result={makeResult()} />);
    expect(screen.getByText("1 項建議")).toBeTruthy();
    expect(screen.getByText("先看下方重點，再決定是否需要調整。")).toBeTruthy();
  });

  it("puts deterministic safe rewrites ahead of generic AI wording", () => {
    render(
      <ResultOverview
        result={makeResult({
          verified_rewrites: [
            {
              statement_index: 0,
              rule: "or_eq_to_in",
              source_rule_id: "R006",
              title: "同欄位 OR 改為 IN",
              before: "A.STATUS='A' OR A.STATUS='B'",
              after: "A.STATUS IN ('A', 'B')",
            },
          ],
          ai: makeAi({ status: "pending", advice: [], suggested_sql: null }),
        })}
      />,
    );
    expect(
      screen.getByText("系統已確認有 1 項可安全改寫，請查看下方改寫對照。 AI 正在整理其他改善建議。"),
    ).toBeTruthy();
  });

  it("keeps deterministic safe rewrites visible when AI is unavailable", () => {
    render(
      <ResultOverview
        result={makeResult({
          verified_rewrites: [
            {
              statement_index: 0,
              rule: "substr_eq_to_like",
              source_rule_id: "R005",
              title: "SUBSTR 比對改為 LIKE",
              before: "SUBSTR(A.YEAR_CODE,1,2)='13'",
              after: "A.YEAR_CODE LIKE '13%'",
            },
          ],
          ai: makeAi({ status: "unavailable", advice: [], suggested_sql: null }),
        })}
      />,
    );
    expect(
      screen.getByText(
        "系統已確認有 1 項可安全改寫，請查看下方改寫對照。 即使智慧建議暫時無法使用，這些改寫仍由系統規則確認。",
      ),
    ).toBeTruthy();
  });

  it("puts explicit non-compliance first", () => {
    render(
      <ResultOverview
        result={makeResult({
          compliance: { status: "BLOCK", label: "不符合中心規範", notice_count: 0, block_count: 2 },
          rules: [
            { rule_id: "R001", name: "COST", status: "BLOCK", evidence: "125,000", note: "超過門檻" },
            { rule_id: "R002", name: "WHERE 查詢條件", status: "BLOCK", evidence: "未提供", note: "缺少條件" },
          ],
        })}
      />,
    );
    expect(screen.getByText("2 項不符合")).toBeTruthy();
  });

  it("does not translate REVIEW into compliant", () => {
    render(
      <ResultOverview
        result={makeResult({
          compliance: { status: "REVIEW", label: "請人工確認", notice_count: 0, block_count: 0 },
          rules: [
            { rule_id: "R002", name: "WHERE 查詢條件", status: "REVIEW", evidence: "JOIN ON", note: "請確認" },
          ],
          ai: makeAi({ advice: [] }),
        })}
      />,
    );
    expect(screen.getByText("1 項建議")).toBeTruthy();
    expect(screen.queryByText(/^符合中心規範/)).toBeNull();
  });
});


it("uses a short plain-language REVIEW explanation", () => {
  render(
    <ResultOverview
      result={makeResult({
        compliance: { status: "REVIEW", label: "請人工確認", notice_count: 0, block_count: 0 },
        rules: [{ rule_id: "R002", name: "WHERE 查詢條件", status: "REVIEW", evidence: "JOIN ON", note: "請確認" }],
        ai: makeAi({ advice: [] }),
      })}
    />,
  );
  expect(screen.getByText("請確認目前的查詢條件是否符合中心規定。")).toBeTruthy();
  expect(screen.queryByText(/複雜結構/)).toBeNull();
});
