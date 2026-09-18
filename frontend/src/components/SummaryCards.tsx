import { useState } from "react";
import type { AnalyzeResponse, RuleRow } from "../types/api";
import { formatCost } from "../lib/cost";
import { complianceTone, improvementTone, type Tone } from "../lib/status";

export interface SummaryCardsProps {
  result: AnalyzeResponse;
}

interface MetricProps {
  tone: Tone;
  icon: string;
  label: string;
  value: string;
  valueStyle?: React.CSSProperties;
  sub: React.ReactNode;
  /** 2026-09-17: every 「不符合」 reads red, including the big value text. */
  bad?: boolean;
}

function Metric({ tone, icon, label, value, valueStyle, sub, bad }: MetricProps) {
  return (
    <div className={`metric tone-${tone}`}>
      <div className="m-top">
        <div className="m-label">{label}</div>
        <div className="m-icon">{icon}</div>
      </div>
      <div className={`m-value${bad ? " m-value-bad" : ""}`} style={valueStyle}>
        {value}
      </div>
      <div className="m-sub">{sub}</div>
    </div>
  );
}

function findCostRule(rules: RuleRow[]): RuleRow | undefined {
  return rules.find((r) => r.rule_id === "R001") ?? rules.find((r) => r.name.includes("COST"));
}

const COMPLIANT_VALUE_STYLE: React.CSSProperties = { fontSize: 22 };

/**
 * 頂部 4 張摘要 Card (PRD §29): 中心規範／COST／改善指數／智慧改善建議。
 * 2026-09-17 (afternoon): the 「建議寫法」 card was removed (the compare card
 * below already shows the per-segment diff) and every 「不符合」 is rendered
 * in the red tone.
 * 2026-09-17 (evening, user feedback on the printed report):
 * - every 「符合」 card is tinted green (`.metric.tone-green`, see app.css);
 * - COST under the threshold no longer shows the number at all — it reads
 *   「符合中心規範」 like the compliance card (the number is still visible in
 *   the rule table and, when over the threshold, stays here in red);
 * - 「改善優先指數」 is now 「改善指數」, its corner icon shows the level
 *   wording (建議改善…) instead of repeating the number, and the breakdown
 *   explains each component in plain language (`detail` from the API);
 * - the AI card is titled 「智慧改善建議」 with a fixed 「AI」 corner icon.
 */
export default function SummaryCards({ result }: SummaryCardsProps) {
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const { compliance, improvement, ai, cost, rules } = result;
  const costRule = findCostRule(rules);
  const costBlocked = costRule?.status === "BLOCK";
  const costNotApplicable = costRule?.status === "NA";
  const costCompliant = !costBlocked && !costNotApplicable;
  const aiPending = ai.status === "pending";
  const aiUnavailable = ai.status === "unavailable";
  const improvementColor = improvementTone(improvement.color);

  return (
    <section className="summary" aria-label="檢核摘要">
      <Metric
        tone={complianceTone(compliance.status)}
        icon={compliance.status === "PASS" ? "✓" : compliance.status === "BLOCK" ? "✕" : "?"}
        label="中心規範"
        value={compliance.label}
        valueStyle={COMPLIANT_VALUE_STYLE}
        bad={compliance.status === "BLOCK"}
        sub={
          compliance.block_count > 0
            ? `${compliance.block_count} 項不符合`
            : compliance.notice_count > 0
              ? `${compliance.notice_count} 項提醒`
              : "目前無提醒事項"
        }
      />

      <Metric
        tone={costBlocked ? "red" : costNotApplicable ? "gray" : "green"}
        icon={costBlocked ? "✕" : costNotApplicable ? "–" : "✓"}
        label="COST"
        value={costCompliant ? "符合中心規範" : formatCost(cost)}
        valueStyle={costCompliant ? COMPLIANT_VALUE_STYLE : undefined}
        bad={costBlocked}
        sub={costRule?.note ?? "—"}
      />

      <div className={`metric tone-${improvementColor}`}>
        <div className="m-top">
          <div className="m-label">改善優先指數</div>
          <div className="m-icon m-icon-text" data-testid="improvement-level">
            {improvement.label}
          </div>
        </div>
        <div className="score-line">
          <div className={`m-value${improvementColor === "red" ? " m-value-bad" : ""}`}>{improvement.score} / 100</div>
        </div>
        <div className="m-sub">分數越高，代表越需要優先檢視與改善</div>
        {improvement.breakdown.length > 0 && (
          <>
            <button
              type="button"
              className="breakdown-toggle"
              aria-expanded={breakdownOpen}
              onClick={() => setBreakdownOpen((v) => !v)}
            >
              指數組成 {breakdownOpen ? "▴" : "▾"}
            </button>
            {breakdownOpen && (
              <div className="breakdown-list" data-testid="breakdown-list">
                <p className="breakdown-intro">指數為 0～100 分，由下列項目加總而成；每一項都有加分上限，加總後超過 100 以 100 計。</p>
                {improvement.breakdown.map((item) => (
                  <div className="breakdown-row" key={item.component}>
                    <div className="breakdown-head">
                      <span className="breakdown-label">{item.label}</span>
                      <span className="breakdown-score">
                        {item.component === "block_floor" ? `至少 ${item.score} 分` : `+${item.score} 分`}
                      </span>
                    </div>
                    {item.detail && <div className="breakdown-detail">{item.detail}</div>}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <Metric
        tone="purple"
        icon="AI"
        label="智慧改善建議"
        value={aiPending ? "AI 分析中" : aiUnavailable ? "暫不提供" : `${ai.advice.length} 項`}
        sub={
          aiPending
            ? "約需數十秒"
            : aiUnavailable
              ? "AI 智慧建議暫時無法使用"
              : (ai.advice[0]?.title ?? "目前沒有額外建議")
        }
      />
    </section>
  );
}
