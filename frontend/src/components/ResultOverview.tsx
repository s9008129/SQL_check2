import type { AnalyzeResponse } from "../types/api";
import { complianceSummaryText } from "../lib/status";
import { performanceAdviceItems, performanceRewriteItems } from "../lib/adviceDisplay";

export interface ResultOverviewProps {
  result: AnalyzeResponse;
}

export default function ResultOverview({ result }: ResultOverviewProps) {
  const adviceCount = result.ai.status === "ok" ? performanceAdviceItems(result.ai.advice).length : 0;
  const verifiedRewriteCount = performanceRewriteItems(result.verified_rewrites).length;
  const complianceText = complianceSummaryText(result.rules);

  let tone = result.compliance.status === "BLOCK" ? "red" : result.compliance.status === "REVIEW" ? "yellow" : "green";
  let title = complianceText;
  let detail = "目前未發現需要修正的中心規範項目。";

  if (result.compliance.status === "BLOCK") {
    detail = adviceCount > 0
      ? `請先處理不符合項目；另外有 ${adviceCount} 項 SQL 改善建議可參考。`
      : "請先處理不符合項目。";
  } else if (result.compliance.status === "REVIEW") {
    detail = "請確認目前的查詢條件是否符合中心規定。";
  } else if (verifiedRewriteCount > 0) {
    const rewriteText = `系統已確認有 ${verifiedRewriteCount} 項可安全改寫，請查看下方改寫對照。`;
    if (result.ai.status === "pending") {
      detail = `${rewriteText} AI 正在整理其他改善建議。`;
    } else if (result.ai.status === "unavailable") {
      detail = `${rewriteText} 即使智慧建議暫時無法使用，這些改寫仍由系統規則確認。`;
    } else {
      detail = rewriteText;
    }
  } else if (result.ai.status === "pending") {
    detail = "規則檢核已完成；AI 正在整理效能改善建議。";
  } else if (result.ai.status === "unavailable") {
    detail = "規則檢核已完成；智慧改善建議目前暫不提供。";
  } else if (adviceCount > 0) {
    detail = "先看下方重點，再決定是否需要調整。";
  } else {
    detail = "目前沒有需要調整的項目。";
  }

  return (
    <section className={`result-overview result-overview-${tone}`} aria-label="檢核結論">
      <div className="result-overview-kicker">先看結論</div>
      <div className="result-overview-title">{title}</div>
      <div className="result-overview-detail">{detail}</div>
    </section>
  );
}
