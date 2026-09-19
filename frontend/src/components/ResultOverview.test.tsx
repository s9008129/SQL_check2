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
