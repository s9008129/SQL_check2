/**
 * Central mapping from backend status/level/color enums to the fixed UI
 * "tone" vocabulary (PRD §28.4): green=符合/目前良好, yellow=提醒/建議改善,
 * red=不符合/優先改善, blue=一般資訊/COST, purple=智慧改善建議,
 * gray=次要/不適用. The server always sends the final judgment
 * (compliance.status, improvement.level/color, rule status) — this module
 * only decides which CSS tone class renders that judgment, it never
 * re-derives the judgment itself.
 */
import type { ComplianceStatus, ImprovementColor, RuleRow, RuleStatus } from "../types/api";

export type Tone = "green" | "yellow" | "red" | "blue" | "purple" | "gray";

export function complianceTone(status: ComplianceStatus): Tone {
  switch (status) {
    case "PASS":
      return "green";
    case "REVIEW":
      return "yellow";
    case "BLOCK":
      return "red";
    default:
      return "gray";
  }
}

export function complianceStateLabel(status: ComplianceStatus): string {
  switch (status) {
    case "PASS":
      return "符合";
    case "REVIEW":
      return "建議";
    case "BLOCK":
      return "不符合";
    default:
      return "建議";
  }
}

export function complianceSummaryText(rules: Pick<RuleRow, "status">[]): string {
  const suggestions = rules.filter((rule) => rule.status === "NOTICE" || rule.status === "REVIEW").length;
  const blocks = rules.filter((rule) => rule.status === "BLOCK").length;
  if (blocks > 0 && suggestions > 0) return `${blocks} 項不符合 · ${suggestions} 項建議`;
  if (blocks > 0) return `${blocks} 項不符合`;
  if (suggestions > 0) return `${suggestions} 項建議`;
  return "全部符合";
}

export function ruleStatusTone(status: RuleStatus): Tone {
  switch (status) {
    case "PASS":
      return "green";
    case "NOTICE":
    case "REVIEW":
      return "yellow";
    case "BLOCK":
      return "red";
    case "NA":
      return "gray";
    default:
      return "gray";
  }
}

export function ruleStatusLabel(status: RuleStatus): string | null {
  switch (status) {
    case "PASS":
      return "符合";
    case "NOTICE":
    case "REVIEW":
      return "建議";
    case "BLOCK":
      return "不符合";
    case "NA":
      return null;
    default:
      return null;
  }
}

export function ruleStatusIcon(status: RuleStatus): string {
  switch (status) {
    case "PASS":
      return "✓";
    case "NOTICE":
      return "!";
    case "REVIEW":
      return "?";
    case "BLOCK":
      return "✕";
    case "NA":
      return "–";
    default:
      return "–";
  }
}

/** improvement.color from the API is already one of these three — pass through. */
export function improvementTone(color: ImprovementColor): Tone {
  return color;
}

export function complianceIcon(status: ComplianceStatus): string {
  switch (status) {
    case "PASS":
      return "✓";
    case "REVIEW":
      return "?";
    case "BLOCK":
      return "✕";
    default:
      return "•";
  }
}
