import type { AdviceItem, AiResult, PerformanceEvidence } from "../types/api";
import { AI_PENDING_MESSAGE, AI_UNAVAILABLE_MESSAGE, VERIFIED_REWRITE_EXPLANATION } from "../lib/copy";
import { assessmentConfidenceText, confidenceBadgeText } from "../lib/confidence";
import { looksLikeSqlFragment } from "../lib/sqlDiff";

export interface ImprovementAdviceProps {
  ai: AiResult;
  performanceEvidence?: PerformanceEvidence[];
}

type EvidenceLevel = "confirmed" | "review" | "info";

const EVIDENCE_META: Record<EvidenceLevel, { label: string; tone: string; badge: string; title: string; explanation: string | null }> = {
  confirmed: {
    label: "可使用此改寫",
    tone: "a-confirmed",
    badge: "green",
    title: `${VERIFIED_REWRITE_EXPLANATION}正式使用前仍請測試。`,
    explanation: VERIFIED_REWRITE_EXPLANATION,
  },
  review: {
    label: "需先確認再改",
    tone: "a-review",
    badge: "yellow",
    title: "改善方向具參考價值，但系統無法只靠 SQL 文字確認查詢結果是否一致。",
    explanation: null,
  },
  info: {
    label: "僅供參考",
    tone: "a-info",
    badge: "purple",
    title: "這是撰寫或治理上的提醒，不代表本案已證明存在效能問題。",
    explanation: null,
  },
};

function canShowConcreteExample(item: AdviceItem): boolean {
  return item.verification === "verified" || item.verification === "corrected";
}

export function ConfidenceBadge({ score }: { score: unknown }) {
  const text = confidenceBadgeText(score);
  if (!text) return null;
  return (
    <span className="badge purple confidence-badge" data-testid="confidence-badge">
      {text}
    </span>
  );
}

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
export default function ImprovementAdvice({ ai, performanceEvidence = [] }: ImprovementAdviceProps) {
  const assessmentConfidence =
    ai.status === "ok" ? assessmentConfidenceText(ai.assessment_confidence_score) : null;
  const hasConfidence =
    ai.status === "ok" &&
    (assessmentConfidence !== null ||
      ai.advice.some((item) => confidenceBadgeText(item.confidence_score) !== null) ||
      (ai.suggested_sql?.available === true &&
        ai.suggested_sql.outcome === "provided" &&
        confidenceBadgeText(ai.suggested_sql.confidence_score) !== null));

  return (
    <section className="card card-ai">
      <div className="card-head">
        <div>
          <div className="card-title"><span className="ai-spark" aria-hidden="true">✦</span> 智慧改善建議</div>
        </div>
        {(ai.status === "ok" || performanceEvidence.length > 0) && (
          <div className="advice-badges">
            {performanceEvidence.length > 0 && (
              <span className="badge green" data-testid="oracle-evidence-count">
                Oracle 11g 證據 {performanceEvidence.length} 項
              </span>
            )}
            {ai.status === "ok" && <span className="badge purple">{ai.advice.length} 項建議</span>}
            {assessmentConfidence && (
              <span
                className="badge purple assessment-confidence-badge"
                data-testid="assessment-confidence-badge"
                title="AI 對目前可見 SQL 文字與系統提供證據的自評；不是 SQL 正確率，也不代表可直接執行。"
              >
                {assessmentConfidence}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="card-body">
        {performanceEvidence.length > 0 && (
          <div className="advice-grid" data-testid="performance-evidence-list">
            {performanceEvidence.map((item) => (
              <div
                className={`advice-box ${item.strength === "strong" ? "a-confirmed" : "a-review"}`}
                key={`${item.pattern_id}-${item.evidence_id}-${item.statement_indexes.join("-")}`}
                data-testid="performance-evidence"
              >
                <div className="advice-title-row">
                  <h4>效能依據｜{item.source_label}</h4>
                  <span className={`badge ${item.strength === "strong" ? "green" : "yellow"}`}>
                    {item.strength === "strong" ? "官方依據" : "官方依據・需實測"}
                  </span>
                </div>
                <div className="evidence-explanation">{item.source_document}</div>
                <p>{item.claim_zh_tw}</p>
                <p><strong>本案判斷：</strong>{item.applicability_zh_tw}</p>
                <p><strong>限制：</strong>{item.caveat_zh_tw}</p>
              </div>
            ))}
          </div>
        )}

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
                        <div className="advice-badges">
                          <span className={`badge ${evidence.badge} evidence-badge`} title={evidence.title}>
                            {evidence.label}
                          </span>
                          <ConfidenceBadge score={item.confidence_score} />
                        </div>
                      </div>
                      {evidence.explanation && <div className="evidence-explanation">{evidence.explanation}</div>}
                      <p>{item.explanation}</p>
                      {item.example && canShowConcreteExample(item) && <code>{item.example}</code>}
                    </div>
                  );
                })}
              </div>
            )}
            {(ai.advice.length > 0 || hasConfidence) && (
              <div className="ai-disclaimer">
                <span>AI 建議僅供參考，不代表實際效能提升；採用前請先測試。</span>
                {hasConfidence && (
                  <span className="confidence-disclaimer">
                    AI 信心僅描述模型在目前證據下的自評；不代表實際效能、正確率或系統驗證結果。
                  </span>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
