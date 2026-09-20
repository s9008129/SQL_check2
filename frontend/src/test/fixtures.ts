import type { AiResult, AnalyzeResponse } from "../types/api";

/**
 * Shared test fixtures. Not a *.test.ts file itself (vitest's default
 * include pattern won't pick it up), just builders the real test files
 * import so each test only has to override the one or two fields it cares
 * about.
 */

export function makeAi(overrides: Partial<AiResult> = {}): AiResult {
  return {
    status: "ok",
    summary: "目前符合中心規範，另有 2 項改善建議。",
    assessment_confidence_score: 86,
    advice: [
      {
        title: "日期條件可再簡化",
        explanation: "目前使用 TRUNC() 比對日期，可評估改成日期範圍。",
        example: "TXN_DATE >= :START_DATE AND TXN_DATE < :END_DATE",
        impact: "medium",
      },
      {
        title: "查詢 HOUT120 時可再確認範圍",
        explanation: "建議確認日期與其他查詢條件是否已縮小範圍，避免一次帶出過多資料。",
        example: null,
        impact: "low",
      },
    ],
    suggested_sql: {
      available: true,
      reason: "可提供簡單改寫供參考。",
      sql: "SELECT A.TAX_ID, A.TXN_DATE\nFROM HOUT120 A\nWHERE A.TXN_DATE >= :START_DATE\n  AND A.TXN_DATE < :NEXT_DATE;",
    },
    estimated_improvement_pct: 45,
    message: null,
    ...overrides,
  };
}

export function makeResult(overrides: Partial<AnalyzeResponse> = {}): AnalyzeResponse {
  return {
    application_no: "115000218",
    cost: 68420,
    compliance: { status: "PASS", label: "符合中心規範", notice_count: 2, block_count: 0 },
    improvement: {
      score: 68,
      level: "IMPROVE",
      label: "建議改善",
      color: "yellow",
      breakdown: [
        { component: "rule_findings", label: "規則檢核", score: 40 },
        { component: "structure", label: "SQL 結構", score: 28 },
      ],
    },
    rules: [
      {
        rule_id: "R001",
        name: "COST < 100,000",
        status: "PASS",
        evidence: "68,420",
        note: "符合規範門檻",
      },
      {
        rule_id: "R005",
        name: "日期欄位使用函數",
        status: "NOTICE",
        evidence: "TRUNC(TXN_DATE)",
        note: "提醒：可評估改成日期範圍",
      },
    ],
    findings: [],
    statements: [{ index: 0, statement_type: "SELECT", parse_status: "ok", tables: ["HOUT120"] }],
    parse_message: null,
    ai: makeAi(),
    ...overrides,
  };
}
