import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import SummaryCards from "./SummaryCards";
import { makeAi, makeResult } from "../test/fixtures";

describe("SummaryCards — improvement colour states", () => {
  it("renders the yellow 建議改善 state", () => {
    const result = makeResult();
    const { container } = render(<SummaryCards result={result} />);
    expect(screen.getByText("68 / 100")).toBeTruthy();
    expect(screen.getByText("建議改善")).toBeTruthy();
    expect(container.querySelector(".tone-yellow")).toBeTruthy();
  });

  it("renders the green 目前良好 state", () => {
    const result = makeResult({
      improvement: { score: 20, level: "GOOD", label: "目前良好", color: "green", breakdown: [] },
    });
    render(<SummaryCards result={result} />);
    expect(screen.getByText("20 / 100")).toBeTruthy();
    expect(screen.getByText("目前良好")).toBeTruthy();
  });

  it("renders the red 優先改善 state", () => {
    const result = makeResult({
      improvement: { score: 88, level: "PRIORITY", label: "優先改善", color: "red", breakdown: [] },
    });
    render(<SummaryCards result={result} />);
    expect(screen.getByText("88 / 100")).toBeTruthy();
    expect(screen.getByText("優先改善")).toBeTruthy();
  });
});

describe("SummaryCards — compliance colour states", () => {
  it("renders the green 符合 state", () => {
    const result = makeResult();
    render(<SummaryCards result={result} />);
    expect(screen.getByText("符合中心規範")).toBeTruthy();
  });

  it("renders the red 不符合 state", () => {
    const result = makeResult({
      compliance: { status: "BLOCK", label: "不符合中心規範", notice_count: 0, block_count: 1 },
    });
    render(<SummaryCards result={result} />);
    expect(screen.getByText("不符合中心規範")).toBeTruthy();
    expect(screen.getByText("1 項不符合")).toBeTruthy();
    expect(screen.getByText("不符合中心規範").className).toContain("m-value-bad");
  });

  it("renders COST in red with ✕ when the COST rule is BLOCK, green ✓ otherwise", () => {
    const blocked = makeResult({
      cost: 350000,
      rules: [{ rule_id: "R001", name: "COST", status: "BLOCK", evidence: "350,000", note: "超過規範門檻 100,000" }],
    });
    const { unmount } = render(<SummaryCards result={blocked} />);
    expect(screen.getByText("350,000").className).toContain("m-value-bad");
    expect(screen.getByText("✕", { selector: ".tone-red .m-icon" })).toBeTruthy();
    unmount();

    render(<SummaryCards result={makeResult()} />);
    expect(screen.queryByText("C")).toBeNull();
  });

  it("no longer renders a 建議寫法 card (the compare card shows the diff)", () => {
    render(<SummaryCards result={makeResult()} />);
    expect(screen.queryByText("建議寫法")).toBeNull();
    expect(screen.queryByText("可供參考")).toBeNull();
  });
});

describe("SummaryCards — AI-dependent card", () => {
  it("shows an AI-pending state on 改善建議 while ai.status is pending", () => {
    const result = makeResult({
      ai: makeAi({ status: "pending", advice: [], suggested_sql: null, estimated_improvement_pct: null }),
    });
    render(<SummaryCards result={result} />);
    expect(screen.getByText("AI 分析中")).toBeTruthy();
  });

  it("shows 暫不提供 on 改善建議 when the AI is unavailable", () => {
    const result = makeResult({
      ai: makeAi({ status: "unavailable", advice: [], suggested_sql: null, estimated_improvement_pct: null, message: "x" }),
    });
    render(<SummaryCards result={result} />);
    expect(screen.getByText("暫不提供")).toBeTruthy();
  });
});
