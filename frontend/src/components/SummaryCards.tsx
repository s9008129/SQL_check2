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
}

function Metric({ tone, icon, label, value, valueStyle, sub }: MetricProps) {
  return (
    <div className={`metric tone-${tone}`}>
      <div className="m-top">
        <div className="m-label">{label}</div>
        <div className="m-icon">{icon}</div>
      </div>
      <div className="m-value" style={valueStyle}>
        {value}
      </div>
      <div className="m-sub">{sub}</div>
    </div>
  );
}

function findCostRule(rules: RuleRow[]): RuleRow | undefined {
  return rules.find((r) => r.rule_id === "R001") ?? rules.find((r) => r.name.includes("COST"));
}

/** 頂部 5 張摘要 Card (PRD §29): 中心規範／COST／改善優先指數／改善建議／建議寫法。 */
export default function SummaryCards({ result }: SummaryCardsProps) {
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const { compliance, improvement, ai, cost, rules } = result;
  const costRule = findCostRule(rules);
  const aiPending = ai.status === "pending";
  const aiUnavailable = ai.status === "unavailable";
  const suggestedAvailable = ai.status === "ok" && !!ai.suggested_sql?.available;
  const outcome = ai.status === "ok" ? ai.suggested_sql?.outcome : undefined;
  const notNeeded = !suggestedAvailable && outcome === "not_needed";
  const adviceOnly = !suggestedAvailable && outcome === "advice_only";

  return (
    <section className="summary" aria-label="檢核摘要">
      <Metric
        tone={complianceTone(compliance.status)}
        icon={compliance.status === "PASS" ? "✓" : compliance.status === "BLOCK" ? "✕" : "?"}
        label="中心規範"
        value={compliance.label}
        valueStyle={{ fontSize: 22 }}
        sub={
          compliance.block_count > 0
            ? `${compliance.block_count} 項不符合`
            : compliance.notice_count > 0
              ? `${compliance.notice_count} 項提醒`
              : "目前無提醒事項"
        }
      />

      <Metric
        tone="blue"
        icon="C"
        label="COST"
        value={formatCost(cost)}
        sub={costRule?.note ?? "—"}
      />

      <div className="metric tone-yellow">
        <div className="m-top">
          <div className="m-label">改善優先指數</div>
          <div className="m-icon">{improvement.score}</div>
        </div>
        <div className="score-line">
          <div className="m-value">{improvement.score} / 100</div>
        </div>
        <div className="m-sub">
          <span
            className="score-state"
            style={{
              color:
                improvementTone(improvement.color) === "green"
                  ? "#16784a"
                  : improvementTone(improvement.color) === "red"
                    ? "#b83139"
                    : "#9b6d00",
            }}
          >
            {improvement.label}
          </span>{" "}
          · 分數越高，代表值得優先檢視的項目越多
        </div>
        {improvement.breakdown.length > 0 && (
          <>
            <button
              type="button"
              className="breakdown-toggle"
              onClick={() => setBreakdownOpen((v) => !v)}
            >
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

      <Metric
        tone={
          aiPending
            ? "purple"
            : aiUnavailable
              ? "gray"
              : suggestedAvailable || notNeeded
                ? "green"
                : adviceOnly
                  ? "yellow"
                  : "gray"
        }
        icon={suggestedAvailable || notNeeded ? "✓" : "·"}
        label="建議寫法"
        value={
          aiPending
            ? "AI 分析中"
            : aiUnavailable
              ? "暫不提供"
              : suggestedAvailable
                ? "可供參考"
                : notNeeded
                  ? "無需改寫"
                  : adviceOnly
                    ? "僅提供方向"
                    : "本次不提供"
        }
        valueStyle={{ fontSize: 21 }}
        sub={
          aiPending
            ? "約需數十秒"
            : aiUnavailable
              ? "AI 智慧建議暫時無法使用"
              : suggestedAvailable
                ? "原始 SQL 完整保留"
                : notNeeded
                  ? "目前寫法已良好"
                  : (ai.suggested_sql?.reason ?? "本次先提供改善方向")
        }
      />
    </section>
  );
}
