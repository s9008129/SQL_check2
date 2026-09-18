import type { AiResult } from "../types/api";
import {
  AI_PENDING_MESSAGE,
  AI_UNAVAILABLE_MESSAGE,
  ESTIMATE_NOT_NEEDED_MESSAGE,
  ESTIMATE_NOTICE_ONLY_MESSAGE,
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
 * 2026-09-17 (evening): "notice_only" is the server's state for governance
 * reminders (e.g. R007 重要資料表) that carry no confirmed SQL-writing point.
 * It renders as an amber note asking for human confirmation — never as
 * 「目前寫法良好」, which stays reserved for level === null.
 */
export default function EstimateCard({ ai }: EstimateCardProps) {
  const level = ai.improvement_potential ?? null;
  const basis = ai.improvement_potential_basis ?? [];

  const basisList =
    basis.length > 0 ? (
      <ul className="potential-basis" aria-label="推算依據">
        {basis.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    ) : null;

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
  } else if (level === "notice_only") {
    body = (
      <div className="ai-note ai-note-notice" data-testid="potential-notice-only">
        {ESTIMATE_NOTICE_ONLY_MESSAGE}
        {basisList}
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
          <h3>{POTENTIAL_HINT[level]}</h3>
          {basisList}
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
          <div className="card-desc">依程式規則檢核與系統驗證結果推算的等級</div>
        </div>
      </div>
      <div className="card-body">{body}</div>
    </section>
  );
}
