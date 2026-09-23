import type { ExecutionPlanAnalysis, ExecutionPlanObservation, ExecutionPlanStep } from "../types/api";

export interface ExecutionPlanCardProps {
  plan: ExecutionPlanAnalysis | null;
}

type PlanTone = "green" | "yellow" | "purple" | "blue" | "gray";

type FriendlyStep = {
  title: string;
  tag: string;
  tone: PlanTone;
};

type FriendlyObservation = {
  title: string;
  detail: string;
  tone: PlanTone;
};

function formatNumber(value: number | null): string {
  return value == null ? "—" : value.toLocaleString("en-US");
}

/** SQL Developer PLAN_TABLE exports may split OPERATION + OPTIONS. */
function formatOperation(step: ExecutionPlanStep): string {
  const options = step.options?.trim();
  return options ? `${step.operation} ${options}` : step.operation;
}

function friendlyStep(step: ExecutionPlanStep): FriendlyStep {
  const operation = formatOperation(step).toUpperCase();

  if (operation.includes("TABLE ACCESS FULL")) {
    return { title: "讀取整張表", tag: "全表讀取", tone: "yellow" };
  }
  if (operation.includes("INDEX")) {
    return { title: "使用索引找資料", tag: "索引", tone: "green" };
  }
  if (operation.includes("SORT ORDER BY")) {
    return { title: "排序資料", tag: "排序", tone: "purple" };
  }
  if (operation.includes("HASH UNIQUE") || operation.includes("SORT UNIQUE")) {
    return { title: "移除重複資料", tag: "去重", tone: "purple" };
  }
  if (operation.includes("GROUP BY")) {
    return { title: "彙整資料", tag: "彙整", tone: "purple" };
  }
  if (operation.includes("HASH JOIN") || operation.includes("MERGE JOIN") || operation.includes("NESTED LOOPS")) {
    return { title: "關聯資料", tag: "資料關聯", tone: "blue" };
  }
  if (operation.includes("FILTER")) {
    return { title: "套用查詢條件", tag: "條件篩選", tone: "blue" };
  }
  if (operation.includes("VIEW")) {
    return { title: "處理中間結果", tag: "中間結果", tone: "gray" };
  }
  return { title: "處理資料", tag: "執行步驟", tone: "gray" };
}

function topCostSteps(steps: ExecutionPlanStep[]): ExecutionPlanStep[] {
  const candidates = steps.filter((step) => step.id !== 0 && step.cost != null);
  return [...candidates]
    .sort((left, right) => (right.cost ?? -1) - (left.cost ?? -1) || left.id - right.id)
    .slice(0, 3);
}

function friendlyObservation(
  item: ExecutionPlanObservation,
  steps: ExecutionPlanStep[],
): FriendlyObservation {
  const step = item.step_id == null ? null : steps.find((candidate) => candidate.id === item.step_id) ?? null;
  const target = step?.object_name ? step.object_name : item.step_id == null ? null : `Step ${item.step_id}`;

  switch (item.code) {
    case "TABLE_ACCESS_FULL":
      return {
        title: "有步驟會讀取整張表",
        detail: `${target ?? "其中一個步驟"}會讀取整張表。這不一定有問題，但可以先留意它的 COST。`,
        tone: "yellow",
      };
    case "FUNCTION_FILTER_PREDICATE":
      return {
        title: "查詢條件先處理了欄位",
        detail: `${target ?? "其中一個步驟"}的條件有函數處理，值得回頭看是否能簡化。`,
        tone: "blue",
      };
    case "CARDINALITY_GAP":
      return {
        title: "預估筆數和實際筆數差很多",
        detail: `${target ?? "其中一個步驟"}的預估與實際差距較大，可再確認查詢條件是否符合預期。`,
        tone: "yellow",
      };
    case "VERIFIED_REWRITE_PLAN_MATCH":
      return {
        title: "安全改寫和 F10 重點有對上",
        detail: "SQLCheck 已找到可安全改寫的條件，F10 也看到同一段寫法，適合優先比較改寫前後的 COST。",
        tone: "green",
      };
    case "COST_MISMATCH":
      return {
        title: "COST 和輸入值不同",
        detail: "請先確認這份執行計畫是不是和目前檢核的 SQL 來自同一次測試。",
        tone: "yellow",
      };
    default:
      return {
        title: "還有一項可留意的地方",
        detail: "需要時可展開完整技術明細確認。",
        tone: "gray",
      };
  }
}

export default function ExecutionPlanCard({ plan }: ExecutionPlanCardProps) {
  if (!plan) return null;

  if (!plan.recognized) {
    return (
      <section className="card card-plan card-plan-unrecognized">
        <div className="card-head">
          <div>
            <div className="card-title">SQL Developer 執行計畫</div>
            <div className="card-desc">目前還無法整理這份 F10 內容。</div>
          </div>
          <span className="badge yellow">格式待確認</span>
        </div>
        <div className="card-body">
          <div className="plan-message plan-message-review">
            請貼上 SQL Developer F10 的完整執行計畫，或上傳 TXT／CSV。
          </div>
        </div>
      </section>
    );
  }

  const prioritySteps = topCostSteps(plan.steps);
  const sourceBadge = plan.source === "actual" ? "含實際統計" : "SQL Developer F10｜估算";
  const friendlyObservations = plan.observations.map((item) => friendlyObservation(item, plan.steps));

  return (
    <section className="card card-plan">
      <div className="card-head">
        <div>
          <div className="card-title">SQL Developer 執行計畫重點</div>
          <div className="card-desc">把 F10 結果整理成幾個重點，先看最值得注意的地方。</div>
        </div>
        <span className={`badge ${plan.source === "actual" ? "green" : "blue"}`}>
          {sourceBadge}
        </span>
      </div>

      <div className="card-body">
        <div className="plan-message">
          {plan.source === "actual"
            ? "這份 SQL Developer 執行計畫含實際統計，可一起參考。"
            : "這是 SQL Developer 的 F10 Explain Plan，顯示資料庫預估會怎麼執行這支 SQL。"}
        </div>

        <div className="plan-summary-grid plan-summary-grid-business">
          <div className="plan-summary-item plan-summary-cost">
            <span>F10 COST</span>
            <strong>{formatNumber(plan.plan_cost)}</strong>
          </div>
          <div className="plan-summary-item">
            <span>執行步驟</span>
            <strong>{plan.step_count.toLocaleString("en-US")}</strong>
          </div>
          <div className="plan-summary-item">
            <span>輸入 COST</span>
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
          <details className="plan-runtime-details">
            <summary>
              <span>查看實際執行統計</span>
              <span className="badge green">{plan.runtime_metrics.length} 項</span>
            </summary>
            <div className="plan-runtime-grid">
              {plan.runtime_metrics.map((metric) => (
                <div className="plan-runtime-item" key={metric.key}>
                  <span>{metric.label}</span>
                  <strong>{metric.value.toLocaleString("en-US")}</strong>
                </div>
              ))}
            </div>
          </details>
        )}

        <div className="plan-section-heading">
          <div>
            <div className="plan-section-title">先看 COST 較高的 {prioritySteps.length} 個步驟</div>
            <div className="plan-section-help">依 F10 顯示的 COST 排序，先幫你抓重點；不是實際耗時排行。</div>
          </div>
          <span className="badge blue">Top {prioritySteps.length}</span>
        </div>

        {prioritySteps.length === 0 ? (
          <div className="plan-empty">這份執行計畫沒有可排序的步驟 COST，可展開完整明細查看。</div>
        ) : (
          <div className="plan-priority-list" data-testid="plan-priority-list">
            {prioritySteps.map((step, index) => {
              const friendly = friendlyStep(step);
              return (
                <details className={`plan-priority-item plan-priority-${friendly.tone}`} key={step.id}>
                  <summary>
                    <span className="plan-priority-rank">{index + 1}</span>
                    <span className="plan-priority-main">
                      <strong>{friendly.title}</strong>
                      <small>{step.object_name ? `資料表 ${step.object_name}` : `Step ${step.id}`}</small>
                    </span>
                    <span className={`badge ${friendly.tone}`}>{friendly.tag}</span>
                    <span className="plan-priority-cost">COST {formatNumber(step.cost)}</span>
                  </summary>
                  <div className="plan-priority-detail">
                    <p>
                      這一步的 COST 是 <strong>{formatNumber(step.cost)}</strong>
                      {step.estimated_rows == null ? "。" : `，預估會處理 ${formatNumber(step.estimated_rows)} 筆資料。`}
                    </p>
                    <div className="plan-tech-line">
                      技術明細：Step {step.id} · {formatOperation(step)}
                      {step.object_name ? ` · ${step.object_name}` : ""}
                    </div>
                  </div>
                </details>
              );
            })}
          </div>
        )}

        {friendlyObservations.length > 0 && (
          <details className="plan-notes-details">
            <summary>
              <span>查看其他系統提醒</span>
              <span className="badge yellow">{friendlyObservations.length} 項</span>
            </summary>
            <div className="plan-observation-list">
              {friendlyObservations.map((item, index) => (
                <div className={`plan-observation plan-observation-${item.tone}`} key={index}>
                  <div className="plan-observation-title">{item.title}</div>
                  <div className="plan-observation-detail">{item.detail}</div>
                </div>
              ))}
            </div>
          </details>
        )}

        <details className="plan-steps-details">
          <summary>查看完整技術明細（進階）</summary>
          {plan.plan_hash_value && (
            <div className="plan-tech-meta">
              Plan Hash：<strong>{plan.plan_hash_value}</strong>
            </div>
          )}
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
          {plan.source === "estimated"
            ? "F10 是估算結果，適合用來比較改寫前後的執行方式。"
            : "這份執行計畫含實際統計，可和 SQL 改寫結果一起參考。"}
        </div>
      </div>
    </section>
  );
}
