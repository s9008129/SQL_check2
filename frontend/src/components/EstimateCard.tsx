import type { AiResult } from "../types/api";
import {
  AI_PENDING_MESSAGE,
  AI_UNAVAILABLE_MESSAGE,
  ESTIMATE_FOOTNOTE,
  ESTIMATE_NOT_AVAILABLE_MESSAGE,
  ESTIMATE_NOT_NEEDED_MESSAGE,
} from "../lib/copy";

export interface EstimateCardProps {
  ai: AiResult;
}

type Band = "gray" | "blue" | "green";

/** PRD §18.4 — colour expresses improvement potential, not risk; UI-only banding. */
function bandFor(pct: number): Band {
  if (pct >= 50) return "green";
  if (pct >= 20) return "blue";
  return "gray";
}

/** 預估改善效果區 (PRD §18 / §32): 單一大型視覺化元件，只顯示一個百分比，絕不顯示第二個 COST。 */
export default function EstimateCard({ ai }: EstimateCardProps) {
  const pct = ai.estimated_improvement_pct;

  let body: React.ReactNode;
  if (ai.status === "pending") {
    body = <div className="ai-note">{AI_PENDING_MESSAGE}</div>;
  } else if (ai.status === "unavailable") {
    body = <div className="ai-note">{ai.message?.trim() ? ai.message : AI_UNAVAILABLE_MESSAGE}</div>;
  } else if (ai.suggested_sql?.outcome === "not_needed" && !pct) {
    // AI judged the SQL already good: say so positively instead of the
    // "not provided" copy, which reads like a refusal.
    body = <div className="ai-note ai-note-good">{ESTIMATE_NOT_NEEDED_MESSAGE}</div>;
  } else if (pct === null || pct === undefined) {
    body = <div className="ai-note">{ESTIMATE_NOT_AVAILABLE_MESSAGE}</div>;
  } else {
    const band = bandFor(pct);
    body = (
      <div className="estimate-wrap">
        <div
          className={`estimate-ring tone-${band}`}
          style={{ "--pct": pct } as React.CSSProperties}
          aria-label={`AI 預估效能改善幅度 ${pct}%`}
        >
          <div className="estimate-center">
            <div className={`estimate-value tone-${band}`}>{pct}%</div>
            <div className="estimate-label">預估改善幅度</div>
          </div>
        </div>
        <div className="estimate-copy">
          <h3>AI 預估效能改善幅度約 {pct}%</h3>
          <p>依目前 SQL 寫法與改善建議進行整體判斷，這個數字用來快速呈現可能的改善效果。</p>
          {band !== "gray" && (
            <div className={`estimate-chip tone-${band}`}>↑ 預估有改善空間</div>
          )}
          <div className="estimate-note">{ESTIMATE_FOOTNOTE}</div>
        </div>
      </div>
    );
  }

  return (
    <section className="card card-estimate">
      <div className="card-head">
        <div>
          <div className="card-title">預估改善效果</div>
          <div className="card-desc">以 AI 建議方向估算可能的效能改善幅度</div>
        </div>
        <span className="badge green">AI 預估</span>
      </div>
      <div className="card-body">{body}</div>
    </section>
  );
}
