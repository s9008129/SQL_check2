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
              title: "直接比對原始欄位",
              explanation: "減少欄位端函數處理，讓條件直接比對原始欄位。",
              before: "SUBSTR(A.CODE, 1, 2) = '13'",
              example: "A.CODE LIKE '13%'",
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
    expect(screen.getAllByTestId("ai-advice-badge")).toHaveLength(3);
    expect(screen.getAllByText("AI 建議")).toHaveLength(3);
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

    expect(screen.getByTestId("oracle-evidence-count").textContent).toContain("改善重點 1 項");
    expect(screen.getByTestId("oracle-evidence-note").textContent).toContain("Oracle 11g 官方依據");
    expect(screen.getByTestId("oracle-evidence-note").textContent).toContain(
      "本區效能改善原則參考 Oracle 11g R2 官方",
    );
    expect(screen.getByTestId("oracle-evidence-note").textContent).toContain("Performance Tuning Guide");
    expect(screen.getByTestId("oracle-evidence-note").textContent).toContain("SQL Language Reference");
    expect(screen.getByText("為什麼這樣可能比較快")).toBeTruthy();
    expect(screen.getByText("從固定文字開頭比對")).toBeTruthy();
    expect(screen.getByText("LIKE 從固定文字開頭比對時，比較容易先縮小要找的資料範圍。")).toBeTruthy();
    expect(screen.queryByText(/13%/)).toBeNull();
    expect(screen.queryByText("系統依據")).toBeNull();
    expect(screen.getByTestId("oracle-evidence-note").textContent).toContain("Oracle 11g R2 官方");
    expect(screen.getByText("AI 分析中，約需數十秒。")).toBeTruthy();
    expect(screen.queryByText(/https:\/\//)).toBeNull();
  });


  it("keeps Oracle evidence wording friendly and hides technical document names", () => {
    render(
      <ImprovementAdvice
        ai={makeAi({ status: "pending", advice: [], suggested_sql: null, estimated_improvement_pct: null })}
        performanceEvidence={[
          {
            evidence_id: "ORACLE11G_SUBQUERY_UNNESTING",
            pattern_id: "LATEST_ROW_CORRELATED_MAX",
            statement_indexes: [0],
            source_label: "Oracle Database 11g 官方文件",
            source_document: "Oracle Database SQL Language Reference 11g Release 2",
            claim_zh_tw: "如果同一張表的相關子查詢重複出現，Oracle 可能需要反覆處理相似的工作。",
            applicability_zh_tw: "這支 SQL 重複使用 MAX 子查詢來找最新資料。",
            caveat_zh_tw: "這表示值得評估，但還不能直接改。",
            strength: "conditional",
          },
        ]}
      />,
    );

    expect(screen.getByText("避免重複找同一批資料")).toBeTruthy();
    expect(screen.getByText(/可能做了重複工作；可評估先整理一次再使用/)).toBeTruthy();
    expect(screen.queryByText(/同一時間有多筆最新資料/)).toBeNull();
    expect(screen.getByTestId("oracle-evidence-note").textContent).toContain("SQL Language Reference");
    expect(screen.queryByText(/nested subquery|unnesting|Pattern Selector|canonical|AST/)).toBeNull();
  });


  it("shows Oracle 11g authority once instead of repeating it on every evidence card", () => {
    const evidence = [
      {
        evidence_id: "ORACLE11G_TRANSFORMED_COLUMN",
        pattern_id: "SUBSTR_EQ_TO_LIKE",
        statement_indexes: [0],
        source_label: "Oracle Database 11g 官方文件",
        source_document: "Oracle Database Performance Tuning Guide 11g Release 2",
        claim_zh_tw: "technical claim",
        applicability_zh_tw: "technical applicability",
        caveat_zh_tw: "technical caveat",
        strength: "strong" as const,
      },
      {
        evidence_id: "ORACLE11G_PREFIX_LIKE_RANGE_SCAN",
        pattern_id: "SUBSTR_EQ_TO_LIKE",
        statement_indexes: [0],
        source_label: "Oracle Database 11g 官方文件",
        source_document: "Oracle Database Performance Tuning Guide 11g Release 2",
        claim_zh_tw: "technical claim",
        applicability_zh_tw: "technical applicability",
        caveat_zh_tw: "technical caveat",
        strength: "strong" as const,
      },
    ];

    render(
      <ImprovementAdvice
        ai={makeAi({ status: "pending", advice: [], suggested_sql: null, estimated_improvement_pct: null })}
        performanceEvidence={evidence}
      />,
    );

    expect(screen.getAllByText("Oracle 11g 官方依據")).toHaveLength(1);
    expect(screen.getAllByText("為什麼這樣可能比較快")).toHaveLength(1);
    expect(screen.getByText("直接比對原始欄位")).toBeTruthy();
    expect(screen.getByText("從固定文字開頭比對")).toBeTruthy();
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


it("does not repeat the AI summary or generic disclaimer when detailed advice cards are visible", () => {
  render(<ImprovementAdvice ai={makeAi({ summary: "這句摘要不應重複顯示。" })} />);
  expect(screen.queryByText("這句摘要不應重複顯示。")).toBeNull();
  expect(
    screen.queryByText("AI 建議是改善參考；真正可安全改寫的內容，仍以「系統已驗證」標示為準。"),
  ).toBeNull();
});


it("hides readability-only OR to IN advice from the performance section", () => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        advice: [
          {
            title: "簡化多值比對寫法",
            explanation: "將同一欄位的多個等於條件合併為 IN 寫法，使 SQL 更簡潔。",
            before: "A.CASE_TYPE = '01' OR A.CASE_TYPE = '02'",
            example: "A.CASE_TYPE IN ('01', '02')",
            impact: "low",
            verification: "verified",
            confidence_score: 90,
          },
          {
            title: "直接比對原始欄位",
            explanation: "減少欄位端函數處理，讓條件直接比對原始欄位。",
            before: "SUBSTR(A.AREA_CODE, 1, 3) = 'TNN'",
            example: "A.AREA_CODE LIKE 'TNN%'",
            impact: "high",
            verification: "verified",
            confidence_score: 90,
          },
        ],
      })}
    />,
  );

  expect(screen.queryByText("簡化多值比對寫法")).toBeNull();
  expect(screen.getByText("直接比對原始欄位")).toBeTruthy();
  expect(screen.getByText("AI 建議 1 項")).toBeTruthy();
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
  [92, "confidence-high"],
  [73, "confidence-medium"],
  [41, "confidence-low"],
])("uses a friendly confidence tone for score %i", (score, expectedClass) => {
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

  expect(screen.getByTestId("confidence-badge").className).toContain(expectedClass);
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

it.each([null, undefined])("falls back to overall AI confidence when item confidence is %s", (score) => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        assessment_confidence_score: 75,
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

  expect(screen.getByText("AI 信心：中 75/100")).toBeTruthy();
});


it("shows a confidence badge on every visible AI advice card", () => {
  render(
    <ImprovementAdvice
      ai={makeAi({
        assessment_confidence_score: 75,
        advice: [
          {
            title: "直接比對原始欄位",
            explanation: "減少欄位先做函數處理。",
            example: "A.CODE LIKE '13%'",
            before: "SUBSTR(A.CODE,1,2)='13'",
            impact: "high",
            verification: "verified",
            confidence_score: 95,
          },
          {
            title: "確認模糊搜尋範圍",
            explanation: "如果需求允許，可以縮小比對範圍。",
            example: null,
            impact: "medium",
            verification: "unverified",
            confidence_score: null,
          },
          {
            title: "減少重複查詢",
            explanation: "可評估先把需要的資料整理好，再和主要資料一起查。",
            example: null,
            impact: "medium",
            verification: "unverified",
            confidence_score: 70,
          },
        ],
      })}
    />,
  );

  expect(screen.getAllByTestId("confidence-badge")).toHaveLength(3);
  expect(screen.getByText("AI 信心：高 95/100")).toBeTruthy();
  expect(screen.getByText("AI 信心：中 75/100")).toBeTruthy();
  expect(screen.getByText("AI 信心：中 70/100")).toBeTruthy();
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
  expect(screen.queryByText("AI 信心怎麼看？")).toBeNull();
  expect(
    screen.queryByText("高：可優先參考；中、低：代表仍有不確定資訊，建議先確認再使用。"),
  ).toBeNull();
  expect(
    screen.queryByText("AI 信心是採用時的參考，不是保證；中、低信心的建議請更保守確認。"),
  ).toBeNull();
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
