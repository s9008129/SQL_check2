import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ComplianceTable from "./ComplianceTable";
import { makeResult } from "../test/fixtures";

describe("ComplianceTable", () => {
  it("renders a PASS row's evidence and note", () => {
    const result = makeResult();
    render(<ComplianceTable rules={result.rules} compliance={result.compliance} parseMessage={null} />);
    expect(screen.getByText("COST < 100,000")).toBeTruthy();
    expect(screen.getByText("68,420")).toBeTruthy();
    expect(screen.getByText("符合規範門檻")).toBeTruthy();
  });

  it("renders a NOTICE row's evidence and note", () => {
    const result = makeResult();
    render(<ComplianceTable rules={result.rules} compliance={result.compliance} parseMessage={null} />);
    expect(screen.getByText("TRUNC(TXN_DATE)")).toBeTruthy();
    expect(screen.getByText("提醒：可評估改成日期範圍")).toBeTruthy();
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

  it("shows a red badge and 不符合 count when any rule BLOCKs", () => {
    const result = makeResult({
      compliance: { status: "BLOCK", label: "不符合中心規範", notice_count: 0, block_count: 1 },
      rules: [
        {
          rule_id: "R001",
          name: "COST < 100,000",
          status: "BLOCK",
          evidence: "125,320",
          note: "超過規範門檻",
        },
      ],
    });
    const { container } = render(
      <ComplianceTable rules={result.rules} compliance={result.compliance} parseMessage={null} />,
    );
    expect(container.querySelector(".badge.red")).toBeTruthy();
    expect(screen.getByText("1 項不符合")).toBeTruthy();
  });
});


it("labels REVIEW separately from ordinary reminders", () => {
  render(
    <ComplianceTable
      compliance={{ status: "REVIEW", label: "請人工確認", notice_count: 0, block_count: 0 }}
      parseMessage={null}
      rules={[
        { rule_id: "R001", name: "COST", status: "PASS", evidence: "42,000", note: "低於門檻" },
        { rule_id: "R002", name: "WHERE 查詢條件", status: "REVIEW", evidence: "JOIN ON", note: "請人工確認" },
      ]}
    />,
  );
  expect(screen.getByText("1 項需確認")).toBeTruthy();
  expect(screen.queryByText(/1 提醒/)).toBeNull();
});


it("annotates resolved R005/R006 NOTICE rows without changing NOTICE status", () => {
  const result = makeResult({
    rules: [
      {
        rule_id: "R005",
        name: "條件欄位使用函數",
        status: "NOTICE",
        evidence: "SUBSTR(CODE)",
        note: "提醒：可評估調整",
      },
      {
        rule_id: "R006",
        name: "OR 條件",
        status: "NOTICE",
        evidence: "同欄位 OR",
        note: "提醒：可評估調整",
      },
    ],
  });
  render(
    <ComplianceTable
      rules={result.rules}
      compliance={result.compliance}
      parseMessage={null}
      verifiedRewrites={[
        {
          statement_index: 0,
          rule: "substr_eq_to_like",
          source_rule_id: "R005",
          title: "SUBSTR 比對改為 LIKE",
          before: "SUBSTR(A.C, 1, 3) = '107'",
          after: "A.C LIKE '107%'",
        },
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
  expect(screen.getAllByText("已提供結果相同的改寫，可參考上方「改寫對照」。")).toHaveLength(2);
  expect(screen.getByText("2 項提醒")).toBeTruthy();
});
