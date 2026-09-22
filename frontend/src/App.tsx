import { useRef, useState } from "react";
import InputPanel from "./components/InputPanel";
import SummaryCards from "./components/SummaryCards";
import ResultOverview from "./components/ResultOverview";
import ComplianceTable from "./components/ComplianceTable";
import ImprovementAdvice from "./components/ImprovementAdvice";
import ExecutionPlanCard from "./components/ExecutionPlanCard";
import SqlCompare from "./components/SqlCompare";
import PrintFooter from "./components/PrintFooter";
import { analyze, ApiError } from "./api/client";
import type { AiResult, AnalyzeResponse } from "./types/api";
import { formatCostInputOnBlur } from "./lib/cost";
import { validateAnalyzeInput } from "./lib/validate";
import { AI_UNAVAILABLE_MESSAGE, GENERIC_NETWORK_ERROR } from "./lib/copy";

type Phase = "idle" | "loading-initial" | "loading-ai" | "done" | "error";

const AI_TIMEOUT_MS = 200_000;

function degradedAi(): AiResult {
  return {
    status: "unavailable",
    summary: null,
    advice: [],
    suggested_sql: null,
    estimated_improvement_pct: null,
    message: AI_UNAVAILABLE_MESSAGE,
  };
}

export default function App() {
  const [applicationNo, setApplicationNo] = useState("");
  const [costText, setCostText] = useState("");
  const [sql, setSql] = useState("");
  const [executionPlan, setExecutionPlan] = useState("");
  const [submittedSql, setSubmittedSql] = useState("");

  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const inputSectionRef = useRef<HTMLElement | null>(null);
  const resultSectionRef = useRef<HTMLElement | null>(null);

  function scrollToInput() {
    inputSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function runAnalysis(
    applicationNoValue: string,
    costValue: string,
    sqlValue: string,
    executionPlanValue: string,
  ) {
    setPhase("loading-initial");
    setErrorMessage(null);
    setResult(null);
    setSubmittedSql(sqlValue);

    const baseBody = {
      application_no: applicationNoValue,
      cost: costValue,
      sql: sqlValue,
      execution_plan: executionPlanValue.trim() || null,
    };

    let first: AnalyzeResponse;
    try {
      first = await analyze({ ...baseBody, include_ai: false });
    } catch (err) {
      setPhase("error");
      setErrorMessage(err instanceof ApiError ? err.detail : GENERIC_NETWORK_ERROR);
      return;
    }

    setResult(first);
    setPhase("loading-ai");
    resultSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });

    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), AI_TIMEOUT_MS);
    try {
      const second = await analyze({ ...baseBody, include_ai: true }, controller.signal);
      setResult(second);
    } catch {
      setResult((prev) => (prev ? { ...prev, ai: degradedAi() } : prev));
    } finally {
      window.clearTimeout(timer);
      setPhase("done");
    }
  }

  function handleSubmit() {
    const error = validateAnalyzeInput({ applicationNo, cost: costText, sql });
    setValidationError(error);
    if (error) return;
    void runAnalysis(applicationNo.trim(), costText, sql, executionPlan);
  }

  function handleClear() {
    setApplicationNo("");
    setCostText("");
    setSql("");
    setExecutionPlan("");
    setSubmittedSql("");
    setResult(null);
    setPhase("idle");
    setErrorMessage(null);
    setValidationError(null);
  }

  function handleCostBlur() {
    setCostText((prev) => formatCostInputOnBlur(prev));
  }

  function handleFileExtracted(newSql: string) {
    setSql(newSql);
    setValidationError(null);
  }

  const submitting = phase === "loading-initial" || phase === "loading-ai";

  return (
    <>
      <header className="topbar no-print">
        <div className="topbar-inner">
          <div className="brand">
            <div className="brand-mark" aria-hidden="true">SQL</div>
            <div>
              <div className="brand-title">SQLCheck AI</div>
              <div className="brand-sub">SQL 智慧檢核與改善助手</div>
            </div>
          </div>

          {result && (
            <nav className="section-nav" aria-label="結果區段導覽">
              <a href="#decision">結論</a>
              <a href="#signals">摘要</a>
              <a href="#evidence">證據</a>
              <a href="#improvements">改善</a>
              <a href="#details">明細</a>
            </nav>
          )}

          <div className="top-actions">
            <button className="ghost-btn" type="button" onClick={scrollToInput}>
              回到輸入區
            </button>
            <button className="print-btn" type="button" onClick={() => window.print()}>
              列印 / 存成 PDF
            </button>
          </div>
        </div>
      </header>

      <main className="layout">
        <aside className="sidebar no-print" id="inputArea" ref={inputSectionRef}>
          <InputPanel
            applicationNo={applicationNo}
            onApplicationNoChange={setApplicationNo}
            costText={costText}
            onCostTextChange={setCostText}
            onCostBlur={handleCostBlur}
            sql={sql}
            onSqlChange={setSql}
            executionPlan={executionPlan}
            onExecutionPlanChange={setExecutionPlan}
            onFileExtracted={handleFileExtracted}
            onSubmit={handleSubmit}
            onClear={handleClear}
            submitting={submitting}
            validationError={validationError}
          />
        </aside>

        <section className="main" id="resultArea" ref={resultSectionRef}>
          {phase === "error" && (
            <div className="error-banner" role="alert">
              <strong>無法完成檢核</strong>
              <p>{errorMessage}</p>
            </div>
          )}

          {!result && phase !== "error" && (
            <section className="empty-state" aria-label="開始使用 SQLCheck">
              <div className="section-eyebrow">SQL Analysis Workbench</div>
              <h1>先輸入 SQL，再由系統把結論、證據與改善方向整理好。</h1>
              <p>必填只有申請單號、COST 與 SQL；SQL Developer 執行計畫是選填的測試機證據。</p>
              <div className="empty-steps" aria-label="分析流程">
                <div><strong>01</strong><span>規則先判定</span><small>中心規範由確定性規則引擎負責</small></div>
                <div><strong>02</strong><span>證據再展開</span><small>需要時檢視規則與測試機 Plan</small></div>
                <div><strong>03</strong><span>最後看改善</span><small>AI 只負責白話解釋與建議</small></div>
              </div>
            </section>
          )}

          {result && (
            <>
              <ResultOverview result={result} />
              <SummaryCards result={result} />

              <section id="evidence" className="story-section" aria-labelledby="evidence-title">
                <header className="section-header">
                  <div className="section-eyebrow">Evidence</div>
                  <h2 id="evidence-title">判定依據</h2>
                  <p>先看確定性規則；有提供 SQL Developer Plan 時，再補上測試機執行證據。</p>
                </header>

                <ComplianceTable
                  rules={result.rules}
                  compliance={result.compliance}
                  parseMessage={result.parse_message}
                />
                <ExecutionPlanCard plan={result.execution_plan} />
              </section>

              <section id="improvements" className="story-section" aria-labelledby="improvements-title">
                <header className="section-header">
                  <div className="section-eyebrow">Interpretation</div>
                  <h2 id="improvements-title">改善方向</h2>
                  <p>把規則與 SQL 結構轉成白話建議；可否直接改寫仍以系統驗證結果為準。</p>
                </header>

                <ImprovementAdvice ai={result.ai} />
              </section>

              <div id="details" className="story-section story-section-compact">
                <SqlCompare
                  originalSql={submittedSql}
                  ai={result.ai}
                  verifiedRewrites={result.verified_rewrites}
                />
              </div>

              <PrintFooter applicationNo={result.application_no} onScrollToInput={scrollToInput} />
            </>
          )}
        </section>
      </main>
    </>
  );
}
