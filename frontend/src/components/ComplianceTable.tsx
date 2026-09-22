import type { ComplianceResult, RuleRow } from "../types/api";
import { complianceSummaryText, complianceTone, ruleStatusIcon, ruleStatusLabel, ruleStatusTone } from "../lib/status";

export interface ComplianceTableProps {
  rules: RuleRow[];
  compliance: ComplianceResult;
  parseMessage: string | null;
}

/**
 * 中心規範檢核採 exception-first：
 * 先讓使用者看需要處理／確認的項目，完整規則仍保留在 disclosure 內供稽核。
 */
export default function ComplianceTable({ rules, compliance, parseMessage }: ComplianceTableProps) {
  const visibleRules = rules.filter((rule) => rule.status !== "NA");
  const badgeText = complianceSummaryText(rules);
  const attentionRules = visibleRules.filter((rule) => rule.status !== "PASS");
  const passCount = visibleRules.length - attentionRules.length;

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="card-title">中心規範檢核</div>
          <div className="card-desc">先顯示需要處理或確認的項目；完整規則可再展開。</div>
        </div>
        <span className={`badge ${complianceTone(compliance.status)}`}>{badgeText}</span>
      </div>

      <div className="card-body">
        {parseMessage && <div className="ai-note">{parseMessage}</div>}

        {attentionRules.length === 0 ? (
          <div className="rule-priority-summary rule-priority-summary-good">
            <div>
              <strong>目前沒有需要優先處理的規則</strong>
              <span>可在下方展開完整規則，確認每一項檢核結果。</span>
            </div>
            <span className="rule-pass-count">{passCount} 項符合</span>
          </div>
        ) : (
          <>
            <div className="rule-priority-summary">
              <div>
                <strong>{"優先查看 " + attentionRules.length + " 項"}</strong>
                <span>先處理不符合，再確認提醒項目；其餘規則收在完整明細。</span>
              </div>
              <span className="rule-pass-count">{passCount} 項符合</span>
            </div>
            <div className="rule-priority-list" aria-label="需要優先查看的規則">
              {attentionRules.map((rule) => (
                <div className="rule-priority-item" key={"priority-" + rule.rule_id}>
                  <span>{rule.name}</span>
                  <strong className={rule.status === "BLOCK" ? "priority-block" : "priority-review"}>
                    {rule.status === "BLOCK" ? "需處理" : "需確認"}
                  </strong>
                </div>
              ))}
            </div>
          </>
        )}

        <details className="rule-details">
          <summary>查看全部 {visibleRules.length} 項規則</summary>
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
                    <span
                      className={`r-icon ${tone === "green" ? "pass" : tone === "yellow" ? "warn" : "fail"}`}
                      aria-hidden="true"
                    >
                      {ruleStatusIcon(rule.status)}
                    </span>
                    <span>{label}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </details>
      </div>
    </section>
  );
}
