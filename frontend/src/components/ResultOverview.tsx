import type { AnalyzeResponse } from "../types/api";
import { complianceStateLabel, complianceSummaryText, complianceTone } from "../lib/status";

export interface ResultOverviewProps {
  result: AnalyzeResponse;
}

export default function ResultOverview({ result }: ResultOverviewProps) {
  const adviceCount = result.ai.status === "ok" ? result.ai.advice.length : 0;
  const complianceText = complianceSummaryText(result.rules);
  const title = complianceStateLabel(result.compliance.status);

  let tone = result.compliance.status === "BLOCK" ? "red" : result.compliance.status === "REVIEW" ? "yellow" : "green";
  let detail = "目前未發現需要修正的中心規範項目。";

  if (result.compliance.status === "BLOCK") {
    detail = adviceCount > 0
      ? `請先處理不符合項目；另外有 ${adviceCount} 項 SQL 改善建議可參考。`
      : "請先處理不符合項目。";
  } else if (result.compliance.status === "REVIEW") {
    detail = "請確認目前的查詢條件是否符合中心規定。";
  } else if (result.ai.status === "pending") {
    detail = "規則檢核已完成；AI 正在整理可讀的改善建議。";
  } else if (result.ai.status === "unavailable") {
    detail = "規則檢核已完成；智慧改善建議目前暫不提供。";
  } else if (adviceCount > 0) {
    detail = "先看下方重點，再決定是否需要調整。";
  } else {
    detail = "目前沒有需要調整的項目。";
  }

  return (
    <section id="decision" className={`decision-hero decision-hero-${tone}`} aria-label="檢核結論">
      <div className="decision-copy">
        <div className="decision-kicker">
          <span>SQLCheck 分析結果</span>
          <span>申請單號 {result.application_no}</span>
        </div>
        <h1>{title}</h1>
        <p>{detail}</p>
      </div>

      <div className="decision-side">
        <span className={`status-pill status-pill-${complianceTone(result.compliance.status)}`}>
          規則引擎判定
        </span>
        <strong className="decision-signal">{complianceText}</strong>
        <span className="decision-signal-label">中心規範摘要</span>
      </div>
    </section>
  );
}
