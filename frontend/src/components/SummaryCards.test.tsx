import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import SummaryCards from "./SummaryCards";
import { makeAi, makeResult } from "../test/fixtures";

describe("SummaryCards — improvement colour states", () => {
  it("renders the yellow 建議改善 state with the level wording as the corner icon", () => {
    const result = makeResult();
    const { container } = render(<SummaryCards result={result} />);
    expect(screen.getByText("68 / 100")).toBeTruthy();
    expect(screen.getByTestId("improvement-level").textContent).toBe("建議改善");
    expect(screen.getByText("改善指數")).toBeTruthy();
    expect(screen.queryByText("改善優先指數")).toBeNull();
    expect(screen.queryByText("67")).toBeNull();
    expect(container.querySelector(".tone-yellow")).toBeTruthy();
  });

  it("explains every breakdown component in plain language when 指數組成 is opened", () => {
    const result = makeResult({
      improvement: {
        score: 67,
        level: "IMPROVE",
        label: "建議改善",
        color: "yellow",
        breakdown: [
          { component: "rule_findings", label: "規則檢核發現的問題", score: 40, detail: "命中越多分數越高，最多 70 分。" },
          {
            component: "cost_ratio",
            label: "COST 接近門檻的程度",
            score: 10,
            detail: "目前 COST 68,888 約為規範門檻 100,000 的 69%，越接近或超過門檻加分越多，最多 15 分。",
          },
          { component: "block_floor", label: "不符合中心規範的最低指數", score: 80, detail: "只要有任何一項不符合中心規範，指數一律至少為 80。" },
        ],
      },
    });
    render(<SummaryCards result={result} />);
    expect(screen.queryByTestId("breakdown-list")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /指數組成/ }));
    const list = screen.getByTestId("breakdown-list");
    expect(list.textContent).toContain("0～100 分，綜合規則、SQL 結構與 COST 計算。");
    expect(list.textContent).toContain("+40 分");
    expect(list.textContent).toContain("目前 COST 68,888 約為規範門檻 100,000 的 69%");
    expect(list.textContent).toContain("至少 80 分");
    expect(list.textContent).not.toContain("佔規範門檻");
  });

  it("shows structure score floors as minimums, not additive points", () => {
    const result = makeResult({
      improvement: {
        score: 60,
        level: "IMPROVE",
        label: "建議改善",
        color: "yellow",
        breakdown: [
          {
            component: "structure_floor",
            label: "需優先確認的 SQL 結構",
            score: 60,
            detail: "缺少資料表關聯條件，改善優先指數至少為 60。",
          },
        ],
      },
    });
    render(<SummaryCards result={result} />);
    fireEvent.click(screen.getByRole("button", { name: /指數組成/ }));
    const list = screen.getByTestId("breakdown-list");
    expect(list.textContent).toContain("至少 60 分");
    expect(list.textContent).not.toContain("+60 分");
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
  it("renders the green 符合 state on both the compliance and the COST card", () => {
    const result = makeResult();
    const { container } = render(<SummaryCards result={result} />);
    // 2026-09-17: COST under the threshold reads 「符合中心規範」 instead of the number.
    expect(screen.getAllByText("符合中心規範")).toHaveLength(2);
    expect(screen.queryByText("68,420")).toBeNull();
    expect(container.querySelectorAll(".metric.tone-green")).toHaveLength(2);
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

  it("keeps showing the COST number in red when it is over the threshold", () => {
    const blocked = makeResult({
      cost: 350000,
      rules: [{ rule_id: "R001", name: "COST", status: "BLOCK", evidence: "350,000", note: "超過規範門檻 100,000" }],
    });
    render(<SummaryCards result={blocked} />);
    expect(screen.getByText("350,000")).toBeTruthy();
    expect(screen.getAllByText("符合中心規範")).toHaveLength(1); // compliance card only
  });

  it("no longer renders a 建議寫法 card (the compare card shows the diff)", () => {
    render(<SummaryCards result={makeResult()} />);
    expect(screen.queryByText("建議寫法")).toBeNull();
    expect(screen.queryByText("可供參考")).toBeNull();
  });
});

describe("SummaryCards — AI-dependent card", () => {
  it("is titled 智慧改善建議 with a fixed AI corner icon instead of the advice count", () => {
    const { container } = render(<SummaryCards result={makeResult()} />);
    expect(screen.getByText("智慧改善建議")).toBeTruthy();
    expect(container.querySelector(".tone-purple .m-icon")?.textContent).toBe("AI");
    expect(screen.getByText("2 項")).toBeTruthy();
  });

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


describe("SummaryCards — REVIEW wording", () => {
  it("shows the number of items that need confirmation instead of saying there are no reminders", () => {
    render(
      <SummaryCards
        result={makeResult({
          compliance: { status: "REVIEW", label: "請人工確認", notice_count: 0, block_count: 0 },
          rules: [
            { rule_id: "R002", name: "WHERE 查詢條件", status: "REVIEW", evidence: "JOIN ON", note: "請人工確認" },
          ],
        })}
      />,
    );
    expect(screen.getByText("1 項需確認")).toBeTruthy();
    expect(screen.queryByText("目前無提醒事項")).toBeNull();
  });
});


describe("SummaryCards — deterministic reminders and AI advice counts stay separate", () => {
  it("does not force AI advice count to equal rule reminder count", () => {
    render(
      <SummaryCards
        result={makeResult({
          compliance: { status: "PASS", label: "符合中心規範", notice_count: 2, block_count: 0 },
          rules: [
            { rule_id: "R004", name: "LIKE 前置萬用字元", status: "NOTICE", evidence: "1 處", note: "提醒" },
            { rule_id: "R006", name: "OR 條件", status: "NOTICE", evidence: "1 處", note: "提醒" },
          ],
          ai: makeAi({
            advice: [{ title: "評估 LIKE 比對方式", explanation: "請確認需求。", example: null, impact: "low", verification: "unverified" }],
          }),
        })}
      />,
    );
    expect(screen.getByText("2 項提醒")).toBeTruthy();
    expect(screen.getByText("1 項")).toBeTruthy();
  });
});
