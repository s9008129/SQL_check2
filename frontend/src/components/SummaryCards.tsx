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

/**
 * 頂部 4 張摘要 Card (PRD §29): 中心規範／COST／改善優先指數／改善建議。
 * 2026-09-17: the 「建議寫法」 card was removed (the compare card below
 * already shows the per-segment diff), COST now carries the same ✓／✕ red-or-
 * green semantics as the rule table (there is no third state for COST), and
 * every 「不符合」 is rendered in the red tone.
 */
export default function SummaryCards({ result }: SummaryCardsProps) {
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const { compliance, improvement, ai, cost, rules } = result;
  const costRule = findCostRule(rules);
  const costBlocked = costRule?.status === "BLOCK";
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
        valueStyle={{ fontSize: 22 }}
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
        tone={costBlocked ? "red" : costRule?.status === "NA" ? "gray" : "green"}
        icon={costBlocked ? "✕" : costRule?.status === "NA" ? "–" : "✓"}
        label="COST"
        value={formatCost(cost)}
        bad={costBlocked}
        sub={costRule?.note ?? "—"}
      />

      <div className={`metric tone-${improvementColor}`}>
        <div className="m-top">
          <div className="m-label">改善優先指數</div>
          <div className="m-icon">{improvement.score}</div>
        </div>
        <div className="score-line">
          <div className={`m-value${improvementColor === "red" ? " m-value-bad" : ""}`}>{improvement.score} / 100</div>
        </div>
        <div className="m-sub">
          <span
            className="score-state"
            style={{
              color: improvementColor === "green" ? "#16784a" : improvementColor === "red" ? "#b83139" : "#9b6d00",
            }}
          >
            {improvement.label}
          </span>{" "}
          · 分數越高，代表值得優先檢視的項目越多
        </div>
        {improvement.breakdown.length > 0 && (
          <>
            <button type="button" className="breakdown-toggle" onClick={() => setBreakdownOpen((v) => !v)}>
              指數組成 {breakdownOpen ? "▴" : "▾"}
            </button>
            {breakdownOpen && (
              <div className="breakdown-list">
                {improvement.breakdown.map((item) => (
                  <div className="breakdown-row" key={item.component}>
                    <span>{item.label}</span>
                    <span>{item.score}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <Metric
        tone="purple"
        icon={aiPending ? "…" : String(ai.advice.length)}
        label="改善建議"
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
