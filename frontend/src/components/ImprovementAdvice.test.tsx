import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ImprovementAdvice from "./ImprovementAdvice";
import { makeAi } from "../test/fixtures";

describe("ImprovementAdvice", () => {
  it("renders advice cards when ai.status is ok", () => {
    render(<ImprovementAdvice ai={makeAi()} />);
    expect(screen.getByText(/智慧改善建議/)).toBeTruthy();
    expect(screen.getByText("日期條件可再簡化")).toBeTruthy();
    expect(
      screen.getByText("目前使用 TRUNC() 比對日期，可評估改成日期範圍。"),
    ).toBeTruthy();
  });

  it("shows evidence labels instead of the model's subjective impact level", () => {
    render(
      <ImprovementAdvice
        ai={makeAi({
          advice: [
            {
              title: "可確認改寫",
              explanation: "系統已有確定性規則。",
              before: "A.STATUS = 'A' OR A.STATUS = 'B'",
              example: "A.STATUS IN ('A', 'B')",
              impact: "high",
              verification: "verified",
            },
            {
              title: "需要確認",
              explanation: "改法需要額外前提。",
              before: "TRUNC(A.DT) = :D",
              example: "A.DT >= :D AND A.DT < :D + 1",
              impact: "low",
              verification: "unverified",
            },
            {
              title: "治理提醒",
              explanation: "請確認查詢範圍。",
              example: null,
              impact: "high",
            },
          ],
        })}
      />,
    );
    expect(screen.getByText("可使用此改寫")).toBeTruthy();
    expect(screen.getByText("系統已確認：這個改法不會改變查詢結果。")).toBeTruthy();
    expect(
      screen.getByTitle("系統已確認：這個改法不會改變查詢結果。正式使用前仍請測試。"),
    ).toBeTruthy();
    expect(screen.getByText("需先確認再改")).toBeTruthy();
    expect(screen.getByText("僅供參考")).toBeTruthy();
    expect(screen.queryByText("可採用")).toBeNull();
    expect(screen.queryByText("影響：高")).toBeNull();
    expect(screen.queryByText("影響：低")).toBeNull();
  });

  it("shows server-owned Oracle 11g evidence even while AI is pending", () => {
    render(
      <ImprovementAdvice
        ai={makeAi({ status: "pending", advice: [], suggested_sql: null, estimated_improvement_pct: null })}
        performanceEvidence={[
          {
            evidence_id: "ORACLE11G_PREFIX_LIKE_RANGE_SCAN",
            pattern_id: "SUBSTR_EQ_TO_LIKE",
            statement_indexes: [0],
            source_label: "Oracle Database 11g 官方文件",
            source_document: "Oracle Database Performance Tuning Guide 11g Release 2",
            claim_zh_tw: "固定前綴 LIKE 在條件適合時可成為 Index Range Scan 的候選條件。",
            applicability_zh_tw: "本案 canonical 改寫為固定前綴 LIKE。",
            caveat_zh_tw: "實際是否使用索引仍需以測試機 Execution Plan 確認。",
            strength: "strong",
          },
        ]}
      />,
    );

    expect(screen.getByTestId("oracle-evidence-count").textContent).toContain("Oracle 11g 證據 1 項");
    expect(screen.getByText("效能依據｜Oracle Database 11g 官方文件")).toBeTruthy();
    expect(screen.getByText("Oracle Database Performance Tuning Guide 11g Release 2")).toBeTruthy();
    expect(screen.getByText(/固定前綴 LIKE 在條件適合時/)).toBeTruthy();
    expect(screen.getByText(/本案判斷：/)).toBeTruthy();
    expect(screen.getByText(/限制：/)).toBeTruthy();
    expect(screen.getByText("AI 分析中，約需數十秒。")).toBeTruthy();
    expect(screen.queryByText(/https:\/\//)).toBeNull();
  });

  it("shows the pending copy while ai.status is pending", () => {
    render(
      <ImprovementAdvice
        ai={makeAi({ status: "pending", advice: [], suggested_sql: null, estimated_improvement_pct: null })}
      />,
    );
    expect(screen.getByText("AI 分析中，約需數十秒。")).toBeTruthy();
  });

  it("shows the fixed unavailable message when ai.status is unavailable", () => {
    render(
      <ImprovementAdvice
        ai={makeAi({
          status: "unavailable",
          advice: [],
          suggested_sql: null,
          estimated_improvement_pct: null,
          message: "智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。",
        })}
      />,
    );
    expect(
      screen.getByText("智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。"),
    ).toBeTruthy();
  });

  it("falls back to the same fixed unavailable text if the backend sends no message", () => {
    render(
      <ImprovementAdvice
        ai={makeAi({
          status: "unavailable",
          advice: [],
          suggested_sql: null,
          estimated_improvement_pct: null,
          message: null,
        })}
      />,
    );
    expect(
      screen.getByText("智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。"),
    ).toBeTruthy();
  });
});


it("does not repeat the AI summary when detailed advice cards are visible", () => {
  render(<ImprovementAdvice ai={makeAi({ summary: "這句摘要不應重複顯示。" })} />);
  expect(screen.queryByText("這句摘要不應重複顯示。")).toBeNull();
  expect(screen.getByText("AI 建議僅供參考，不代表實際效能提升；採用前請先測試。")).toBeTruthy();
});


it("never renders copyable SQL for an unverified advice item", () => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        advice: [
          {
            title: "評估 LIKE 比對方式",
            explanation: "請先確認實際比對需求。",
            before: "A.NAME LIKE '%明'",
            example: "A.NAME LIKE '明%'",
            impact: "low",
            verification: "unverified",
          },
        ],
      })}
    />,
  );
  expect(screen.getByText("需先確認再改")).toBeTruthy();
  expect(screen.queryByText("A.NAME LIKE '明%'")).toBeNull();
});

it("shows verified evidence and AI confidence as separate badges", () => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        advice: [
          {
            title: "可確認改寫",
            explanation: "同欄位條件可整理。",
            example: "A.STATUS IN ('A', 'B')",
            impact: "high",
            verification: "verified",
            confidence_score: 92,
          },
        ],
      })}
    />,
  );

  expect(screen.getByText("可使用此改寫")).toBeTruthy();
  expect(screen.getByText("AI 信心：高 92/100")).toBeTruthy();
});

it("keeps high AI confidence separate from an unverified evidence badge", () => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        advice: [
          {
            title: "需要確認",
            explanation: "改法需要額外前提。",
            example: null,
            impact: "high",
            verification: "unverified",
            confidence_score: 96,
          },
        ],
      })}
    />,
  );

  expect(screen.getByText("需先確認再改")).toBeTruthy();
  expect(screen.getByText("AI 信心：高 96/100")).toBeTruthy();
  expect(screen.queryByText("可使用此改寫")).toBeNull();
});

it.each([
  ["AI 信心：中 73/100", 73],
  ["AI 信心：低 41/100", 41],
])("renders %s inline", (text, score) => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        advice: [
          {
            title: "方向提醒",
            explanation: "請先確認業務條件。",
            example: null,
            impact: "low",
            confidence_score: score,
          },
        ],
      })}
    />,
  );

  expect(screen.getByText(text)).toBeTruthy();
});

it.each([null, undefined])("does not render a badge for %s confidence", (score) => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        advice: [
          {
            title: "方向提醒",
            explanation: "請先確認業務條件。",
            example: null,
            impact: "low",
            confidence_score: score,
          },
        ],
      })}
    />,
  );

  expect(screen.queryByTestId("confidence-badge")).toBeNull();
});


it("shows overall AI assessment confidence even when no rewrite or advice is needed", () => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        summary: "目前未發現需要調整的寫法。",
        assessment_confidence_score: 91,
        advice: [],
        suggested_sql: {
          available: false,
          reason: "目前未發現需要調整的寫法。",
          sql: null,
          confidence_score: null,
          outcome: "not_needed",
        },
      })}
    />,
  );

  expect(screen.getByText("AI 判讀信心：高（91/100）")).toBeTruthy();
  expect(screen.getByText("目前未發現需要調整的寫法。")).toBeTruthy();
  expect(screen.queryByTestId("assessment-confidence-note")).toBeNull();
  expect(
    screen.getByText("AI 信心僅描述模型在目前證據下的自評；不代表實際效能、正確率或系統驗證結果。"),
  ).toBeTruthy();
});

it.each([
  [82, "AI 判讀信心：高（82/100）"],
  [73, "AI 判讀信心：中（73/100）"],
  [41, "AI 判讀信心：低（41/100）"],
])("renders overall confidence band for score %i", (score, expected) => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        assessment_confidence_score: score,
      })}
    />,
  );
  expect(screen.getByText(expected)).toBeTruthy();
});

it("keeps overall confidence separate from verified/review evidence labels", () => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        assessment_confidence_score: 92,
        advice: [
          {
            title: "需要確認",
            explanation: "仍需欄位型態資訊。",
            example: null,
            impact: "medium",
            verification: "unverified",
            confidence_score: 72,
          },
        ],
      })}
    />,
  );

  expect(screen.getByText("AI 判讀信心：高（92/100）")).toBeTruthy();
  expect(screen.getByText("需先確認再改")).toBeTruthy();
  expect(screen.getByText("AI 信心：中 72/100")).toBeTruthy();
  expect(screen.queryByText("可使用此改寫")).toBeNull();
});
