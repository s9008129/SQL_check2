import type { ComplianceResult, RuleRow, VerifiedRewrite } from "../types/api";
import { complianceTone, ruleStatusIcon, ruleStatusTone } from "../lib/status";

export interface ComplianceTableProps {
  rules: RuleRow[];
  compliance: ComplianceResult;
  parseMessage: string | null;
  verifiedRewrites?: VerifiedRewrite[];
}

function summarize(rules: RuleRow[]) {
  const pass = rules.filter((r) => r.status === "PASS").length;
  const notice = rules.filter((r) => r.status === "NOTICE").length;
  const review = rules.filter((r) => r.status === "REVIEW").length;
  const block = rules.filter((r) => r.status === "BLOCK").length;
  return { pass, notice, review, block };
}

/** 中心規則比對區 (PRD §30): 只呈現規則事實 — 狀態、檢核項目、本次內容、簡短說明。 */
export default function ComplianceTable({ rules, compliance, parseMessage, verifiedRewrites = [] }: ComplianceTableProps) {
  const { pass, notice, review, block } = summarize(rules);
  const resolvedRuleIds = new Set(verifiedRewrites.map((rewrite) => rewrite.source_rule_id));
  const parts = [
    block > 0 ? `${block} 項不符合` : null,
    review > 0 ? `${review} 項需確認` : null,
    notice > 0 ? `${notice} 項提醒` : null,
  ].filter((x): x is string => x !== null);
  const badgeText = parts.length > 0 ? parts.join(" · ") : `${pass} 項全部符合`;

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
          {rules.map((rule) => (
            <div className="rule" key={rule.rule_id}>
              <div className={`r-icon ${ruleStatusTone(rule.status) === "green" ? "pass" : ruleStatusTone(rule.status) === "yellow" ? "warn" : ruleStatusTone(rule.status) === "red" ? "fail" : "neutral"}`}>
                {ruleStatusIcon(rule.status)}
              </div>
              <div className="r-name">{rule.name}</div>
              <div className="r-evidence">{rule.evidence}</div>
              <div className="r-note">
                {rule.note}
                {rule.status === "NOTICE" && resolvedRuleIds.has(rule.rule_id) && (
                  <div className="r-annotation">已提供結果相同的改寫，可參考上方「改寫對照」。</div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
