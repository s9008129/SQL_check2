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
  });
});

describe("SummaryCards — AI-dependent cards", () => {
  it("shows an AI-pending state on 改善建議 and 建議寫法 while ai.status is pending", () => {
    const result = makeResult({
      ai: makeAi({ status: "pending", advice: [], suggested_sql: null, estimated_improvement_pct: null }),
    });
    render(<SummaryCards result={result} />);
    expect(screen.getAllByText("AI 分析中").length).toBeGreaterThanOrEqual(2);
  });

  it("shows 本次不提供 on 建議寫法 when suggested_sql.available is false", () => {
    const result = makeResult({
      ai: makeAi({
        suggested_sql: {
          available: false,
          reason: "為避免改變原本查詢內容，本次先提供改善方向，不自動產生建議寫法。",
          sql: null,
        },
      }),
    });
    render(<SummaryCards result={result} />);
    expect(screen.getByText("本次不提供")).toBeTruthy();
  });

  it("shows 可供參考 on 建議寫法 when a suggestion is available", () => {
    const result = makeResult();
    render(<SummaryCards result={result} />);
    expect(screen.getByText("可供參考")).toBeTruthy();
  });
});
