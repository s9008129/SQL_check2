import type { ComplianceResult, RuleRow } from "../types/api";
import { complianceSummaryText, complianceTone, ruleStatusIcon, ruleStatusLabel, ruleStatusTone } from "../lib/status";

export interface ComplianceTableProps {
  rules: RuleRow[];
  compliance: ComplianceResult;
  parseMessage: string | null;
}

/** 中心規範檢核：只呈現檢核項目與三態結果，完整 evidence/note 仍由 API 保留。 */
export default function ComplianceTable({ rules, compliance, parseMessage }: ComplianceTableProps) {
  const visibleRules = rules.filter((rule) => rule.status !== "NA");
  const badgeText = complianceSummaryText(rules);

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="card-title">中心規範檢核</div>
          <div className="card-desc">本次檢核結果</div>
        </div>
        <span className={`badge ${complianceTone(compliance.status)}`}>{badgeText}</span>
      </div>
      <div className="card-body">
        {parseMessage && <div className="ai-note">{parseMessage}</div>}
        <div className="rule-list">
          <div className="rule rule-header" aria-hidden="true">
            <div className="r-name">檢核項目</div>
            <div className="r-result">結果</div>
          </div>
          {visibleRules.map((rule) => {
            const tone = ruleStatusTone(rule.status);
            const label = ruleStatusLabel(rule.status);
            if (!label) return null;
            return (
              <div className="rule" key={rule.rule_id}>
                <div className="r-name">{rule.name}</div>
                <div className={`r-result r-result-${tone}`}>
                  <span className={`r-icon ${tone === "green" ? "pass" : tone === "yellow" ? "warn" : "fail"}`} aria-hidden="true">
                    {ruleStatusIcon(rule.status)}
                  </span>
                  <span>{label}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
