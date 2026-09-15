import type { ComplianceResult, RuleRow } from "../types/api";
import { complianceTone, ruleStatusIcon, ruleStatusTone } from "../lib/status";

export interface ComplianceTableProps {
  rules: RuleRow[];
  compliance: ComplianceResult;
  parseMessage: string | null;
}

function summarize(rules: RuleRow[]) {
  const pass = rules.filter((r) => r.status === "PASS").length;
  const notice = rules.filter((r) => r.status === "NOTICE" || r.status === "REVIEW").length;
  const block = rules.filter((r) => r.status === "BLOCK").length;
  return { pass, notice, block };
}

/** 中心規則比對區 (PRD §30): 只呈現規則事實 — 狀態、檢核項目、本次內容、簡短說明。 */
export default function ComplianceTable({ rules, compliance, parseMessage }: ComplianceTableProps) {
  const { pass, notice, block } = summarize(rules);
  const badgeText =
    block > 0
      ? `${block} 項不符合${notice > 0 ? ` · ${notice} 項提醒` : ""}`
      : notice > 0
        ? `${pass} 符合 · ${notice} 提醒`
        : `${pass} 項全部符合`;

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="card-title">中心規則比對</div>
          <div className="card-desc">依本次 SQL 與 COST 顯示檢核結果</div>
        </div>
        <span className={`badge ${complianceTone(compliance.status)}`}>{badgeText}</span>
      </div>
      <div className="card-body">
        {parseMessage && <div className="ai-note">{parseMessage}</div>}
        <div className="rule-list">
          {rules.map((rule) => (
            <div className="rule" key={rule.rule_id}>
              <div className={`r-icon ${ruleStatusTone(rule.status) === "green" ? "pass" : ruleStatusTone(rule.status) === "yellow" ? "warn" : ruleStatusTone(rule.status) === "red" ? "fail" : "neutral"}`}>
                {ruleStatusIcon(rule.status)}
              </div>
              <div className="r-name">{rule.name}</div>
              <div className="r-evidence">{rule.evidence}</div>
              <div className="r-note">{rule.note}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
