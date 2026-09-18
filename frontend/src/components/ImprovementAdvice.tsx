import type { AiResult, ImpactLevel } from "../types/api";
import { AI_PENDING_MESSAGE, AI_UNAVAILABLE_MESSAGE } from "../lib/copy";

export interface ImprovementAdviceProps {
  ai: AiResult;
}

// 2026-09-17 (evening user decision): every AI advice card keeps the same
// AI-owned purple/neutral surface — a large red card made an "AI 認為影響高"
// suggestion look as severe as a 不符合 finding. The impact level is now
// carried by a thin left colour bar (a-high/a-medium/a-low, see app.css)
// plus the small badge below; the surface itself must stay neutral.
const IMPACT_TONE: Record<ImpactLevel, string> = {
  high: "a-high",
  medium: "a-medium",
  low: "a-low",
};
const DEFAULT_TONE = "a-low";

const IMPACT_LABEL: Record<ImpactLevel, string> = {
  low: "改善機會：低",
  medium: "改善機會：中",
  high: "改善機會：高",
};

const IMPACT_BADGE_TONE: Record<ImpactLevel, string> = {
  low: "gray",
  medium: "yellow",
  high: "red",
};

function adoptionLabel(item: AiResult["advice"][number]): { text: string; tone: string } {
  if (item.verification === "verified") return { text: "查詢結果已確認", tone: "blue" };
  if (item.verification === "corrected") return { text: "系統已修正寫法", tone: "blue" };
  if (item.example) return { text: "需確認後再改", tone: "yellow" };
  return { text: "需先確認", tone: "gray" };
}

/** 智慧改善建議：先讓業務 SQL 撰寫者知道「值不值得看」與「能不能直接採用」。 */
export default function ImprovementAdvice({ ai }: ImprovementAdviceProps) {
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="card-title">智慧改善建議</div>
        </div>
        {ai.status === "ok" && <span className="badge purple">{ai.advice.length} 項建議</span>}
      </div>
      <div className="card-body">
        {ai.status === "pending" && (
          <div className="ai-note">{AI_PENDING_MESSAGE}</div>
        )}

        {ai.status === "unavailable" && (
          <div className="ai-note">{ai.message?.trim() ? ai.message : AI_UNAVAILABLE_MESSAGE}</div>
        )}

        {ai.status === "ok" && (
          <>
            {ai.summary && <p className="advice-summary">{ai.summary}</p>}
            {ai.advice.length > 0 && (
              <div className="ai-note" role="note">
                「改善機會」代表這項寫法值得檢視的程度，不代表實際效能提升幅度；是否能直接採用請看每張卡片的採用狀態。
              </div>
            )}
            {ai.advice.length === 0 ? (
              <div className="ai-note">目前沒有額外的改善建議。</div>
            ) : (
              <div className="advice-grid">
                {ai.advice.map((item, index) => {
                  const adoption = adoptionLabel(item);
                  return (
                    <div className={`advice-box ${item.impact ? IMPACT_TONE[item.impact] : DEFAULT_TONE}`} key={`${item.title}-${index}`}>
                      <h4>{item.title}</h4>
                      <div className="advice-meta">
                        {item.impact && <span className={`badge ${IMPACT_BADGE_TONE[item.impact]}`}>{IMPACT_LABEL[item.impact]}</span>}
                        <span className={`badge ${adoption.tone}`}>{adoption.text}</span>
                      </div>
                      <p>{item.explanation}</p>
                      {item.example && <code>{item.example}</code>}
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
