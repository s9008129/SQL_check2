import type { AdviceItem, AiResult } from "../types/api";
import { AI_PENDING_MESSAGE, AI_UNAVAILABLE_MESSAGE } from "../lib/copy";
import { looksLikeSqlFragment } from "../lib/sqlDiff";

export interface ImprovementAdviceProps {
  ai: AiResult;
}

type EvidenceLevel = "confirmed" | "review" | "info";

const EVIDENCE_META: Record<EvidenceLevel, { label: string; tone: string; badge: string; title: string }> = {
  confirmed: {
    label: "已確認",
    tone: "a-confirmed",
    badge: "green",
    title: "此建議的 SQL 改寫已通過系統的確定性驗證。",
  },
  review: {
    label: "需確認",
    tone: "a-review",
    badge: "yellow",
    title: "改善方向具參考價值，但系統無法只靠 SQL 文字確認查詢結果完全相同。",
  },
  info: {
    label: "提醒",
    tone: "a-info",
    badge: "purple",
    title: "這是撰寫或治理上的提醒，不代表本案已證明存在效能問題。",
  },
};

export function adviceEvidenceLevel(item: AdviceItem): EvidenceLevel {
  if (item.verification === "verified" || item.verification === "corrected") return "confirmed";
  if (item.verification === "unverified") return "review";

  const example = item.example?.trim() ?? "";
  if (item.before?.trim() && example) return "review";
  if (example && looksLikeSqlFragment(example)) return "review";
  return "info";
}

/**
 * 智慧改善建議：不再把 Gemma 的 high/medium/low impact 當成主要視覺訊號。
 * 模型看不到 execution plan / index / statistics，因此畫面改以伺服器可驗證的
 * 「系統可確認／需人工確認／觀念提醒」呈現可信度與採用方式。
 */
export default function ImprovementAdvice({ ai }: ImprovementAdviceProps) {
  return (
    <section className="card card-ai">
      <div className="card-head">
        <div>
          <div className="card-title"><span className="ai-spark" aria-hidden="true">✦</span> 智慧改善建議</div>
        </div>
        {ai.status === "ok" && <span className="badge purple">{ai.advice.length} 項建議</span>}
      </div>
      <div className="card-body">
        {ai.status === "pending" && <div className="ai-note">{AI_PENDING_MESSAGE}</div>}

        {ai.status === "unavailable" && (
          <div className="ai-note">{ai.message?.trim() ? ai.message : AI_UNAVAILABLE_MESSAGE}</div>
        )}

        {ai.status === "ok" && (
          <>
            {ai.advice.length === 0 ? (
              <div className="ai-note">{ai.summary?.trim() || "目前沒有額外的改善建議。"}</div>
            ) : (
              <div className="advice-grid">
                {ai.advice.map((item, index) => {
                  const evidence = EVIDENCE_META[adviceEvidenceLevel(item)];
                  return (
                    <div className={`advice-box ${evidence.tone}`} key={`${item.title}-${index}`}>
                      <div className="advice-title-row">
                        <h4>{item.title}</h4>
                        <span className={`badge ${evidence.badge} evidence-badge`} title={evidence.title}>
                          {evidence.label}
                        </span>
                      </div>
                      <p>{item.explanation}</p>
                      {item.example && <code>{item.example}</code>}
                    </div>
                  );
                })}
              </div>
            )}
            {ai.advice.length > 0 && <div className="ai-disclaimer">AI 建議僅供參考，採用前請先測試。</div>}
          </>
        )}
      </div>
    </section>
  );
}
