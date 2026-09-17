/**
 * Fixed, PRD-mandated Traditional Chinese copy strings, centralized so
 * every component quotes the exact same wording (PRD §17.5, §25.4, §33,
 * §51). Never phrase these differently in-line in a component.
 */

// PRD §25.4 / §33 — right-hand SQL-compare panel when the backend decided
// (by design, e.g. non-SELECT or too-complex SELECT) not to produce a
// suggested rewrite.
export const SUGGESTED_SQL_NOT_AVAILABLE_MESSAGE =
  "為避免改變原本查詢內容，本次先提供改善方向，不自動產生建議寫法。";

// PRD §51 — AI degrade copy, used when ai.status === "unavailable" (Ollama
// down, or the client-side 200s watchdog gave up on the second /api/analyze
// call). Different reason, different panel, from SUGGESTED_SQL_NOT_AVAILABLE_MESSAGE above.
export const AI_UNAVAILABLE_MESSAGE =
  "智慧改善建議目前暫時無法使用，仍可依上方規則檢核結果進行確認。";

// 2026-09-17 — red warning under the SQL compare card title (user request:
// suggestions are AI output and must be tried on a test DB first).
export const SUGGESTED_SQL_WARNING = "AI 建議寫法僅供參考，採用前務必先於測試機驗證。";

// 2026-09-17 — the three genuinely different "no rewrite" situations get
// their own copy, so "SQL is already fine" never reads like a refusal.
export const SUGGESTED_SQL_NOT_NEEDED_MESSAGE = "AI 檢視後認為目前寫法已良好，本次不需要改寫。";
// 2026-09-17 user feedback: keep this plain and short — the model's own
// `reason` (rendered right under it) states the concrete point to confirm.
export const SUGGESTED_SQL_ADVICE_ONLY_MESSAGE =
  "改善方向請見上方「智慧改善建議」與下方逐段對照，採用前請先確認：";

// PRD §17.5 / §32.3 — shown instead of a percentage/gauge when
// ai.estimated_improvement_pct is null.
export const ESTIMATE_NOT_AVAILABLE_MESSAGE = "本次不提供效能改善幅度預估";
// Shown when the AI judged the SQL already good (outcome not_needed).
export const ESTIMATE_NOT_NEEDED_MESSAGE = "目前寫法良好，AI 未發現明顯的改善空間。";

// PRD §18.3 — the one allowed caption line under the estimate gauge.
export const ESTIMATE_FOOTNOTE =
  "AI 依目前 SQL 寫法與改善建議進行預估，實際效果仍以後續執行結果為準。";

// Lightweight loading copy while ai.status === "pending" (PRD §51's spirit:
// AI is never a single point of failure, so the rest of the page is fully
// usable while this is showing).
export const AI_PENDING_MESSAGE = "AI 分析中，約需數十秒。";

// Mirrors backend/app/services/cost_utils.py::COST_FRIENDLY_ERROR — used
// only for the fast client-side pre-check; the backend's own 422 `detail`
// text always wins when present.
export const COST_FRIENDLY_ERROR =
  "COST 請輸入大於等於 0 的數字，可包含千分位逗號（例如 68,420）。";

export const APPLICATION_NO_REQUIRED_ERROR = "請輸入申請單號。";
export const SQL_REQUIRED_ERROR = "請輸入 SQL。";

// PRD §53 — SQL parser total failure.
export const PARSE_FAILED_MESSAGE =
  "SQL 結構較複雜，目前無法完整解析，請確認 SQL 內容後再試一次。";

export const GENERIC_NETWORK_ERROR = "網路連線發生問題，請稍後再試一次。";
