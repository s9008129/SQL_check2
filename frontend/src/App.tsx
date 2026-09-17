import { useRef, useState } from "react";
import InputPanel from "./components/InputPanel";
import SummaryCards from "./components/SummaryCards";
import ComplianceTable from "./components/ComplianceTable";
import ImprovementAdvice from "./components/ImprovementAdvice";
import EstimateCard from "./components/EstimateCard";
import SqlCompare from "./components/SqlCompare";
import PrintFooter from "./components/PrintFooter";
import { analyze, ApiError } from "./api/client";
import type { AiResult, AnalyzeResponse } from "./types/api";
import { formatCostInputOnBlur } from "./lib/cost";
import { validateAnalyzeInput } from "./lib/validate";
import { complianceIcon, complianceTone } from "./lib/status";
import { AI_UNAVAILABLE_MESSAGE, GENERIC_NETWORK_ERROR } from "./lib/copy";

type Phase = "idle" | "loading-initial" | "loading-ai" | "done" | "error";

// Client-side watchdog on the second (include_ai:true) /api/analyze call —
// if Ollama/Gemma is slow or stuck, degrade locally instead of hanging.
// 2026-09-16: raised from 150s to 200s alongside backend's
// OLLAMA_TIMEOUT_SECONDS going from 120s to 180s (app.yaml's num_predict
// was tripled to 3072, so the longest real replies take longer) — this
// must stay comfortably above the backend's own timeout, or the frontend
// would give up and show "unavailable" before the backend's second retry
// attempt even had a chance to finish.
// 2026-09-17: the backend now enforces ONE overall deadline of
// OLLAMA_TIMEOUT_SECONDS (180s) per analysis, retries included, so this
// watchdog only needs to stay above that single number.
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

  async function runAnalysis(applicationNoValue: string, costValue: string, sqlValue: string) {
    setPhase("loading-initial");
    setErrorMessage(null);
    setResult(null);
    setSubmittedSql(sqlValue);

    const baseBody = { application_no: applicationNoValue, cost: costValue, sql: sqlValue };

    // Step 1: fast, deterministic-only pass. Rendered in full immediately —
    // compliance/cost/improvement/rules/findings never change after this.
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

    // Step 2: fires automatically, no user action. On success the whole
    // result is replaced — never a partial merge. 2026-09-17: the AI pass no
    // longer changes improvement.score/breakdown at all (the index is fully
    // deterministic); only the AI-dependent sections (advice, suggested SQL,
    // improvement potential) differ from the first response.
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), AI_TIMEOUT_MS);
    try {
      const second = await analyze({ ...baseBody, include_ai: true }, controller.signal);
      setResult(second);
    } catch {
      // Network error or our own watchdog abort: keep step 1's result, only
      // degrade the ai-dependent sections locally.
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
    void runAnalysis(applicationNo.trim(), costText, sql);
  }

  function handleClear() {
    setApplicationNo("");
    setCostText("");
    setSql("");
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
            <div className="brand-mark">SQL</div>
            <div>
              <div className="brand-title">SQLCheck AI</div>
              <div className="brand-sub">SQL 效能優化助手</div>
            </div>
          </div>
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
            <div className="empty-hint">
              請於左側輸入申請單號、COST 與 SQL，並點選「開始檢核」查看結果。
            </div>
          )}

          {result && (
            <>
              <div className="hero">
                <div>
                  <div className="eyebrow">
                    申請單號 <span>{result.application_no}</span>
                  </div>
                  <h1>SQL 效能檢核結果</h1>
                  <p>依中心規範與智慧改善建議產生的檢核結果。</p>
                </div>
                <span className={`status-pill status-pill-${complianceTone(result.compliance.status)}`}>
                  {complianceIcon(result.compliance.status)} {result.compliance.label}
                </span>
              </div>

              <SummaryCards result={result} />
              <ComplianceTable
                rules={result.rules}
                compliance={result.compliance}
                parseMessage={result.parse_message}
              />
              <ImprovementAdvice ai={result.ai} />
              <EstimateCard ai={result.ai} />
              <SqlCompare originalSql={submittedSql} ai={result.ai} />
              <PrintFooter applicationNo={result.application_no} onScrollToInput={scrollToInput} />
            </>
          )}
        </section>
      </main>
    </>
  );
}
