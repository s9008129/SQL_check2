/**
 * TypeScript mirror of backend/app/schemas.py (Pydantic models). Field
 * names, optionality and literal unions must stay in sync with that file
 * field-for-field.
 *
 * Rule of thumb used throughout this file: a Python field annotated
 * `X | None` becomes `X | null` here (the JSON key is always present, the
 * value can be null). A Python field annotated plainly `X` (even if it
 * carries a `= default` for convenience when constructing the model in
 * Python) becomes a required, non-null `X` here, because the actual
 * response is always built by business logic with a concrete value.
 */

export type RuleStatus = "PASS" | "NOTICE" | "BLOCK" | "REVIEW" | "NA";
export type ComplianceStatus = "PASS" | "BLOCK" | "REVIEW";
export type ImprovementLevel = "GOOD" | "IMPROVE" | "PRIORITY";
export type AiStatus = "ok" | "pending" | "unavailable";
export type ImpactLevel = "low" | "medium" | "high";
export type ImprovementColor = "green" | "yellow" | "red";
export type ImprovementBreakdownComponent =
  | "rule_findings"
  | "structure"
  | "cost_ratio"
  | "structure_floor"
  | "block_floor";

// ---------------------------------------------------------------------------
// GET /api/health
// ---------------------------------------------------------------------------
export interface HealthResponse {
  status: "ok";
  ai_available: boolean;
}

// ---------------------------------------------------------------------------
// POST /api/extract-sql
// ---------------------------------------------------------------------------
export interface ExtractSqlResponse {
  status: "ok";
  filename: string;
  sql: string;
  statement_count: number;
  needs_confirmation: boolean;
  message: string;
}

// ---------------------------------------------------------------------------
// POST /api/analyze — request
// ---------------------------------------------------------------------------
export interface AnalyzeRequest {
  application_no: string;
  cost: string | number;
  sql: string;
  include_ai: boolean;
}

// ---------------------------------------------------------------------------
// POST /api/analyze — response building blocks
// ---------------------------------------------------------------------------
export interface Finding {
  rule_id: string;
  status: "NOTICE" | "BLOCK" | "REVIEW";
  fact: string;
  statement_index: number;
  table: string | null;
}

export interface RuleRow {
  rule_id: string;
  name: string;
  status: RuleStatus;
  evidence: string;
  note: string;
}

export interface ComplianceResult {
  status: ComplianceStatus;
  label: string;
  notice_count: number;
  block_count: number;
}

export interface ImprovementBreakdownItem {
  component: ImprovementBreakdownComponent;
  label: string;
  score: number;
  /** Plain-language explanation of what this component measures (optional for older payloads). */
  detail?: string | null;
}

export interface ImprovementResult {
  score: number;
  level: ImprovementLevel;
  label: string;
  color: ImprovementColor;
  breakdown: ImprovementBreakdownItem[];
}

export interface StatementSummary {
  index: number;
  statement_type: string;
  parse_status: "ok" | "failed";
  tables: string[];
}

export interface VerifiedRewrite {
  statement_index: number;
  rule: string;
  source_rule_id: string;
  title: string;
  before: string;
  after: string;
}

export interface AdviceItem {
  title: string;
  explanation: string;
  example: string | null;
  impact: ImpactLevel | null;
  /** Model self-assessment of whether this advice applies to the current SQL. */
  confidence_score?: number | null;
  // Original fragment that `example` replaces (verbatim); optional on the
  // wire for backward compatibility with an older backend.
  before?: string | null;
  /** Server verdict on before→example: query-result-preserving / corrected to a proven form / not proven. */
  verification?: "verified" | "corrected" | "unverified" | null;
  /** Caveat the rule's equivalence depends on, if any. */
  assumption?: string | null;
}

export type RewriteOutcome = "provided" | "not_needed" | "advice_only" | "gated" | "rejected";

export interface SuggestedSql {
  available: boolean;
  reason: string;
  sql: string | null;
  /** Model self-assessment for the complete rewrite; only meaningful when provided. */
  confidence_score?: number | null;
  // Why there is / isn't a rewrite (mirrors backend RewriteOutcome). Optional
  // on the wire for backward compatibility with a not-yet-redeployed backend.
  outcome?: RewriteOutcome;
}

/**
 * Server-derived improvement potential. "notice_only" means the only findings
 * were governance reminders (e.g. R007 重要資料表) with no confirmed SQL
 * writing-level improvement point — it must never be rendered as 「寫法良好」.
 */
export type ImprovementPotential = "high" | "medium" | "low" | "notice_only";

export interface AiResult {
  status: AiStatus;
  summary: string | null;
  advice: AdviceItem[];
  suggested_sql: SuggestedSql | null;
  /** Backward-compatible wire field; current server returns null because no post-change percentage is measured. */
  estimated_improvement_pct: number | null;
  /** Server-derived improvement-potential level; null = nothing to improve found. */
  improvement_potential?: ImprovementPotential | null;
  /** What the level was derived from, one plain sentence per line. */
  improvement_potential_basis?: string[];
  message: string | null;
  /** Why status is "unavailable" (diagnostic; `message` is what to show). */
  degrade_code?: string | null;
}

export interface AnalyzeResponse {
  application_no: string;
  cost: number;
  compliance: ComplianceResult;
  improvement: ImprovementResult;
  rules: RuleRow[];
  findings: Finding[];
  statements: StatementSummary[];
  /**
   * Deterministic rewrite candidates; optional for older backend responses.
   * Present (including []) means the new backend checked deterministically;
   * undefined means legacy payload fallback is allowed.
   */
  verified_rewrites?: VerifiedRewrite[];
  parse_message: string | null;
  ai: AiResult;
}
