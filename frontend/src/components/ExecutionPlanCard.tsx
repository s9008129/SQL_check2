import type { ExecutionPlanAnalysis, ExecutionPlanObservation, ExecutionPlanStep } from "../types/api";

export interface ExecutionPlanCardProps {
  plan: ExecutionPlanAnalysis | null;
}

function formatNumber(value: number | null): string {
  return value == null ? "—" : value.toLocaleString("en-US");
}

/** SQL Developer PLAN_TABLE exports split the access path into OPERATION and
 * OPTIONS columns (e.g. "TABLE ACCESS" + "FULL"). Reviewers read the two as a
 * single phrase, so the table shows exactly what the plan states — combined,
 * never invented — and stays clean when OPTIONS is empty. */
function formatOperation(step: ExecutionPlanStep): string {
  const options = step.options?.trim();
  return options ? `${step.operation} ${options}` : step.operation;
}

function observationClass(item: ExecutionPlanObservation): string {
  if (item.level === "review") return "plan-observation-review";
  if (item.level === "opportunity") return "plan-observation-opportunity";
  return "plan-observation-fact";
}

export default function ExecutionPlanCard({ plan }: ExecutionPlanCardProps) {
  if (!plan) return null;

  if (!plan.recognized) {
    return (
      <section className="card card-plan card-plan-unrecognized">
        <div className="card-head">
          <div>
            <div className="card-title">Oracle 執行計畫證據</div>
            <div className="card-desc">SQL Developer 證據解析</div>
          </div>
          <span className="badge yellow">格式待確認</span>
        </div>
        <div className="card-body">
          <div className="plan-message plan-message-review">{plan.message}</div>
          <p className="plan-disclaimer">
            SQL 規則檢核仍然有效；請改貼完整的 DBMS_XPLAN／SQL Developer Plan，或上傳 TXT／CSV。
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="card card-plan">
      <div className="card-head">
        <div>
          <div className="card-title">Oracle 執行計畫證據</div>
          <div className="card-desc">把 COST 拆成可觀察的 Plan 證據，不讓 AI 猜原因。</div>
        </div>
        <span className={`badge ${plan.source === "actual" ? "green" : "blue"}`}>
          {plan.source_label}
        </span>
      </div>

      <div className="card-body">
        <div className="plan-message">{plan.message}</div>

        <div className="plan-summary-grid">
          <div className="plan-summary-item">
            <span>Plan Steps</span>
            <strong>{plan.step_count.toLocaleString("en-US")}</strong>
          </div>
          <div className="plan-summary-item">
            <span>Plan COST</span>
            <strong>{formatNumber(plan.plan_cost)}</strong>
          </div>
          <div className="plan-summary-item">
            <span>Plan Hash</span>
            <strong>{plan.plan_hash_value ?? "—"}</strong>
          </div>
          <div className="plan-summary-item">
            <span>輸入 COST 對照</span>
            <strong>
              {plan.cost_matches_input == null
                ? "無法比對"
                : plan.cost_matches_input
                  ? "一致"
                  : "不一致"}
            </strong>
          </div>
        </div>

        {plan.runtime_metrics.length > 0 && (
          <div className="plan-runtime-block">
            <div className="plan-section-title">實際執行統計</div>
            <div className="plan-runtime-grid">
              {plan.runtime_metrics.map((metric) => (
                <div className="plan-runtime-item" key={metric.key}>
                  <span>{metric.label}</span>
                  <strong>{metric.value.toLocaleString("en-US")}</strong>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="plan-section-title">系統從 Plan 看見的重點</div>
        {plan.observations.length === 0 ? (
          <div className="plan-empty">
            目前沒有需要另外標示的 Plan 證據；可展開下方步驟明細自行確認。
          </div>
        ) : (
          <div className="plan-observation-list">
            {plan.observations.map((item, index) => (
              <div
                className={`plan-observation ${observationClass(item)}`}
                key={`${item.code}-${item.step_id ?? "g"}-${index}`}
              >
                <div className="plan-observation-title">{item.title}</div>
                <div className="plan-observation-detail">{item.detail}</div>
              </div>
            ))}
          </div>
        )}

        <details className="plan-steps-details">
          <summary>查看執行計畫步驟</summary>
          <div className="plan-table-wrap">
            <table className="plan-table">
              <thead>
                <tr>
                  <th>Id</th>
                  <th>Operation</th>
                  <th>Object</th>
                  <th>E-Rows</th>
                  <th>A-Rows</th>
                  <th>Cost</th>
                  <th>Buffers</th>
                </tr>
              </thead>
              <tbody>
                {plan.steps.map((step) => (
                  <tr key={step.id}>
                    <td>{step.id}</td>
                    <td>{formatOperation(step)}</td>
                    <td>{step.object_name ?? "—"}</td>
                    <td>{formatNumber(step.estimated_rows)}</td>
                    <td>{formatNumber(step.actual_rows)}</td>
                    <td>{formatNumber(step.cost)}</td>
                    <td>{formatNumber(step.buffers)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>

        <div className="plan-disclaimer">
          {plan.source === "estimated" ? (
            <>
              這是<strong>正式資料庫 F10 Explain Plan</strong> 的估算證據；可反映 Explain 當下
              Optimizer 的預估路徑，但不代表 SQL 已實際執行，也不等於實際耗時、I/O 或列數。
            </>
          ) : (
            <>此 Plan 含 runtime 欄位；來源環境仍以作業紀錄為準。</>
          )}
          目前 Plan 證據不改變中心規範判定或「改善指數」。
        </div>
      </div>
    </section>
  );
}
