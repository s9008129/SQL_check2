import type { AiResult } from "../types/api";
import {
  AI_PENDING_MESSAGE,
  AI_UNAVAILABLE_MESSAGE,
  ESTIMATE_NOT_NEEDED_MESSAGE,
  POTENTIAL_CAVEAT,
  POTENTIAL_HINT,
  POTENTIAL_LABEL,
} from "../lib/copy";

export interface EstimateCardProps {
  ai: AiResult;
}

/**
 * 預估改善效果區. 2026-09-17 user decision: the model's percentage was never
 * measured (no plan, no statistics, no rewritten COST), so the card now shows
 * the server-derived improvement-potential LEVEL (高／中／低), the facts it
 * was derived from, and a plain caveat. No number is rendered.
 */
export default function EstimateCard({ ai }: EstimateCardProps) {
  const level = ai.improvement_potential ?? null;
  const basis = ai.improvement_potential_basis ?? [];

  let body: React.ReactNode;
  if (ai.status === "pending") {
    body = <div className="ai-note">{AI_PENDING_MESSAGE}</div>;
  } else if (ai.status === "unavailable") {
    body = <div className="ai-note">{ai.message?.trim() ? ai.message : AI_UNAVAILABLE_MESSAGE}</div>;
  } else if (level === null) {
    body = (
      <div className="ai-note ai-note-good" data-testid="potential-none">
        {ESTIMATE_NOT_NEEDED_MESSAGE}
      </div>
    );
  } else {
    body = (
      <div className="estimate-wrap potential-wrap" data-testid="potential">
        <div className={`potential-badge potential-${level}`} aria-label={`改善潛力 ${POTENTIAL_LABEL[level]}`}>
          <div className="potential-value">{POTENTIAL_LABEL[level]}</div>
          <div className="estimate-label">改善潛力</div>
        </div>
        <div className="estimate-copy">
          <h3>改善潛力：{POTENTIAL_LABEL[level]}</h3>
          <p>{POTENTIAL_HINT[level]}</p>
          {basis.length > 0 && (
            <ul className="potential-basis" aria-label="推算依據">
              {basis.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
          <div className="estimate-note potential-caveat">⚠ {POTENTIAL_CAVEAT}</div>
        </div>
      </div>
    );
  }

  return (
    <section className="card card-estimate">
      <div className="card-head">
        <div>
          <div className="card-title">預估改善效果</div>
          <div className="card-desc">依規則檢核結果與 AI 建議推算的改善潛力等級</div>
        </div>
        <span className="badge green">改善潛力</span>
      </div>
      <div className="card-body">{body}</div>
    </section>
  );
}
