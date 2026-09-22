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
