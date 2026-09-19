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
export const SUGGESTED_SQL_WARNING = "AI 建議僅供參考，採用前請先測試。";

// 2026-09-17 — the three genuinely different "no rewrite" situations get
// their own copy, so "SQL is already fine" never reads like a refusal.
export const SUGGESTED_SQL_NOT_NEEDED_MESSAGE = "目前未發現需要調整的寫法。";
// 2026-09-17 user feedback: keep this plain and short — the model's own
// `reason` (rendered right under it) states the concrete point to confirm.
export const SUGGESTED_SQL_ADVICE_ONLY_MESSAGE = "有可參考的寫法，請先確認業務條件。";

// Shown when nothing to improve was found (level null / outcome not_needed).
export const ESTIMATE_NOT_NEEDED_MESSAGE = "目前未發現需要調整的地方。";

// 2026-09-17 (evening user decision): governance-only reminders (重要資料表
// R007 …) are a "please look at this", not a confirmed SQL writing problem.
// This copy must never read like 「目前寫法良好」.
export const ESTIMATE_NOTICE_ONLY_MESSAGE =
  "有提醒事項，請確認實際查詢需求後再決定是否調整。";

// The adoption-status card explains trust/actionability, not measured
// performance improvement.
export const POTENTIAL_CAVEAT =
  "此處說明建議目前可採用的程度，不代表實際效能提升幅度；效能仍需於測試環境確認。";
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
