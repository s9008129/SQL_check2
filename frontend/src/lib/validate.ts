import { parseCostInput } from "./cost";
import {
  APPLICATION_NO_REQUIRED_ERROR,
  COST_FRIENDLY_ERROR,
  SQL_REQUIRED_ERROR,
} from "./copy";

export interface AnalyzeInput {
  applicationNo: string;
  cost: string;
  sql: string;
}

/**
 * Minimal client-side pre-check before firing POST /api/analyze — required
 * fields + a non-negative COST. This is only a fast fail to save a round
 * trip; the backend (AnalyzeRequest validators in backend/app/schemas.py)
 * is the real authority and its own 422 `detail` message is what gets
 * shown when the backend disagrees.
 */
export function validateAnalyzeInput(input: AnalyzeInput): string | null {
  if (!input.applicationNo.trim()) return APPLICATION_NO_REQUIRED_ERROR;
  if (!input.sql.trim()) return SQL_REQUIRED_ERROR;
  if (parseCostInput(input.cost) === null) return COST_FRIENDLY_ERROR;
  return null;
}
