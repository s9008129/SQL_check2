import type { AnalyzeResponse } from "../types/api";

export interface ResultOverviewProps {
  result: AnalyzeResponse;
}

export default function ResultOverview({ result }: ResultOverviewProps) {
  const reviewCount = result.rules.filter((r) => r.status === "REVIEW").length;
  const adviceCount = result.ai.status === "ok" ? result.ai.advice.length : 0;

  let tone = "green";
  let title = "符合中心規範";
  let detail = "目前未發現需要修正的中心規範項目。";

  if (result.compliance.status === "BLOCK") {
    tone = "red";
    title = `有 ${result.compliance.block_count} 項中心規範需要修正`;
    detail = adviceCount > 0
      ? `請先處理不符合項目；另外有 ${adviceCount} 項 SQL 改善建議可參考。`
      : "請先處理不符合項目，再確認其他提醒。";
  } else if (result.compliance.status === "REVIEW") {
    tone = "yellow";
    title = reviewCount > 0 ? `有 ${reviewCount} 項需要人工確認` : "有項目需要人工確認";
    detail = "請確認目前的查詢條件是否符合中心規定。";
  } else if (result.ai.status === "pending") {
    detail = "規則檢核已完成；AI 正在整理可讀的改善建議。";
  } else if (result.ai.status === "unavailable") {
    detail = "規則檢核已完成；智慧改善建議目前暫不提供。";
  } else if (adviceCount > 0) {
    title = `符合中心規範，另有 ${adviceCount} 項建議`;
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
