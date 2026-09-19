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
