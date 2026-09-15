/**
 * COST input parsing/formatting (PRD §8.3 / §17.1 / §17.2).
 *
 * The user types the original Oracle COST value once, with or without
 * thousands separators ("68420" or "68,420"). This module only formats
 * and does a light client-side sanity check; the backend
 * (backend/app/services/cost_utils.py) remains the real validation
 * authority — its friendly 422 `detail` message must be surfaced as-is
 * rather than replaced by a client-side guess.
 */

/** Parse a raw COST input string into a non-negative integer, or null if invalid. */
export function parseCostInput(raw: string): number | null {
  const text = raw.replace(/,/g, "").replace(/\s/g, "").trim();
  if (text === "") return null;
  if (!/^\d+$/.test(text)) return null;
  const n = Number(text);
  if (!Number.isFinite(n) || n < 0) return null;
  return Math.round(n);
}

/** Format an integer with zh-TW thousands separators, e.g. 68420 -> "68,420". */
export function formatCost(n: number): string {
  return new Intl.NumberFormat("zh-TW").format(n);
}

/**
 * Reformat a raw COST input on blur: valid input gets comma-formatted,
 * invalid/partial input is returned unchanged so the user can keep editing.
 */
export function formatCostInputOnBlur(raw: string): string {
  const n = parseCostInput(raw);
  return n === null ? raw : formatCost(n);
}
