import type { AiResult, ImpactLevel } from "../types/api";
import { AI_PENDING_MESSAGE, AI_UNAVAILABLE_MESSAGE } from "../lib/copy";

export interface ImprovementAdviceProps {
  ai: AiResult;
}

// 2026-09-17: card tint now carries meaning — it follows the AI's impact
// level (high = red-soft, medium = yellow-soft, low = blue-soft) instead of
// cycling through decorative colours by position.
const IMPACT_TONE: Record<ImpactLevel, string> = {
  high: "a-high",
  medium: "a-medium",
  low: "a-low",
};
const DEFAULT_TONE = "a-low";

const IMPACT_LABEL: Record<ImpactLevel, string> = {
  low: "影響：低",
  medium: "影響：中",
  high: "影響：高",
};

const IMPACT_BADGE_TONE: Record<ImpactLevel, string> = {
  low: "gray",
  medium: "yellow",
  high: "red",
};

/** 智慧改善建議區 (PRD §26 / §31): 2–3 個簡潔彩色卡片，說明可以留意什麼、為什麼、怎麼改。 */
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
            {ai.advice.length === 0 ? (
              <div className="ai-note">目前沒有額外的改善建議。</div>
            ) : (
              <div className="advice-grid">
                {ai.advice.map((item, index) => (
                  <div className={`advice-box ${item.impact ? IMPACT_TONE[item.impact] : DEFAULT_TONE}`} key={`${item.title}-${index}`}>
                    <h4>
                      {item.title}
                      {item.impact && (
                        <span
                          className={`badge ${IMPACT_BADGE_TONE[item.impact]}`}
                          style={{ marginLeft: 8 }}
                        >
                          {IMPACT_LABEL[item.impact]}
                        </span>
                      )}
                    </h4>
                    <p>{item.explanation}</p>
                    {item.example && <code>{item.example}</code>}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
