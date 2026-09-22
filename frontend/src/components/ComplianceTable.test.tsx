import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ComplianceTable from "./ComplianceTable";
import { makeResult } from "../test/fixtures";

describe("ComplianceTable", () => {
  it("renders a simple item/result row and hides generic evidence and notes", () => {
    const result = makeResult({
      rules: [
        {
          rule_id: "R001",
          name: "COST",
          status: "PASS",
          evidence: "未發現",
          note: "目前無需調整",
        },
      ],
    });
    render(<ComplianceTable rules={result.rules} compliance={result.compliance} parseMessage={null} />);
    expect(screen.getByText("檢核項目")).toBeTruthy();
    expect(screen.getByText("結果")).toBeTruthy();
    expect(screen.getByText("COST")).toBeTruthy();
    expect(screen.getByText("符合")).toBeTruthy();
    expect(screen.queryByText("未發現")).toBeNull();
    expect(screen.queryByText("目前無需調整")).toBeNull();
  });

  it("maps NOTICE and REVIEW to the yellow 建議 state", () => {
    const result = makeResult({
      rules: [
        { rule_id: "R004", name: "LIKE 前置萬用字元", status: "NOTICE", evidence: "1 處", note: "提醒" },
        { rule_id: "R002", name: "WHERE 查詢條件", status: "REVIEW", evidence: "JOIN ON", note: "需確認" },
      ],
    });
    render(
      <ComplianceTable
        rules={result.rules}
        compliance={{ status: "REVIEW", label: "請人工確認", notice_count: 1, block_count: 0 }}
        parseMessage={null}
      />,
    );
    expect(screen.getAllByText("建議")).toHaveLength(2);
    expect(screen.getByText("2 項建議")).toBeTruthy();
    expect(screen.queryByText("提醒")).toBeNull();
    expect(screen.getAllByText("需確認")).toHaveLength(2);
  });

  it("maps BLOCK to red 不符合 and hides NA rows", () => {
    const result = makeResult({
      rules: [
        { rule_id: "R001", name: "COST", status: "BLOCK", evidence: "125,000", note: "超過門檻" },
        { rule_id: "R009", name: "不適用項目", status: "NA", evidence: "—", note: "—" },
      ],
    });
    const { container } = render(
      <ComplianceTable
        rules={result.rules}
        compliance={{ status: "BLOCK", label: "不符合中心規範", notice_count: 0, block_count: 1 }}
        parseMessage={null}
      />,
    );
    expect(screen.getByText("不符合")).toBeTruthy();
    expect(screen.getByText("1 項不符合")).toBeTruthy();
    expect(screen.queryByText("不適用項目")).toBeNull();
    expect(container.querySelectorAll(".rule")).toHaveLength(2); // header + visible COST row
  });

  it("shows the parse_message note when present, and hides it when null", () => {
    const result = makeResult();
    const parseMessage = "SQL 結構較複雜，目前無法完整解析，請確認 SQL 內容後再試一次。";
    const { rerender } = render(
      <ComplianceTable rules={result.rules} compliance={result.compliance} parseMessage={parseMessage} />,
    );
    expect(screen.getByText(parseMessage)).toBeTruthy();

    rerender(<ComplianceTable rules={result.rules} compliance={result.compliance} parseMessage={null} />);
    expect(screen.queryByText(parseMessage)).toBeNull();
  });

  it("uses the requested three-state header count for all pass and block-plus-suggestions", () => {
    const allPass = makeResult({
      rules: [{ rule_id: "R001", name: "COST", status: "PASS", evidence: "42,000", note: "符合" }],
      compliance: { status: "PASS", label: "符合中心規範", notice_count: 0, block_count: 0 },
    });
    const { unmount } = render(
      <ComplianceTable rules={allPass.rules} compliance={allPass.compliance} parseMessage={null} />,
    );
    expect(screen.getByText("全部符合")).toBeTruthy();
    unmount();

    const mixed = makeResult({
      rules: [
        { rule_id: "R001", name: "COST", status: "BLOCK", evidence: "125,000", note: "超過門檻" },
        { rule_id: "R004", name: "LIKE 前置萬用字元", status: "NOTICE", evidence: "1 處", note: "提醒" },
        { rule_id: "R002", name: "WHERE 查詢條件", status: "REVIEW", evidence: "JOIN ON", note: "需確認" },
      ],
      compliance: { status: "BLOCK", label: "不符合中心規範", notice_count: 1, block_count: 1 },
    });
    render(<ComplianceTable rules={mixed.rules} compliance={mixed.compliance} parseMessage={null} />);
    expect(screen.getByText("1 項不符合 · 2 項建議")).toBeTruthy();
  });

  it("does not render the retired resolved-rewrite annotation", () => {
    const result = makeResult({
      rules: [{ rule_id: "R006", name: "OR 條件", status: "NOTICE", evidence: "同欄位 OR", note: "提醒" }],
    });
    render(<ComplianceTable rules={result.rules} compliance={result.compliance} parseMessage={null} />);
    expect(screen.queryByText(/已提供結果相同的改寫/)).toBeNull();
    expect(screen.getByText("建議")).toBeTruthy();
  });
});


it("surfaces non-pass rules before the complete rule disclosure", () => {
  const result = makeResult({
    rules: [
      { rule_id: "R001", name: "COST", status: "PASS", evidence: "42,000", note: "符合" },
      { rule_id: "R004", name: "LIKE 前置萬用字元", status: "NOTICE", evidence: "1 處", note: "提醒" },
    ],
    compliance: { status: "PASS", label: "符合中心規範", notice_count: 1, block_count: 0 },
  });
  const { container } = render(
    <ComplianceTable rules={result.rules} compliance={result.compliance} parseMessage={null} />,
  );

  expect(screen.getByText("優先查看 1 項")).toBeTruthy();
  expect(screen.getByText("1 項符合")).toBeTruthy();
  expect(screen.getByText("需確認")).toBeTruthy();
  expect((container.querySelector("details.rule-details") as HTMLDetailsElement).open).toBe(false);
});
