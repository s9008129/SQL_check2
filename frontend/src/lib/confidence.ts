export type ConfidenceLevel = "high" | "medium" | "low";

/**
 * Accept only a genuine integer in the server's confidence range. Runtime API
 * data is intentionally treated as unknown so malformed legacy/provider data
 * is hidden instead of being clamped into a misleading score.
 */
export function normalizeConfidenceScore(score: unknown): number | null {
  if (typeof score !== "number" || !Number.isInteger(score) || score < 0 || score > 100) {
    return null;
  }
  return score;
}

export function confidenceLevel(score: unknown): ConfidenceLevel | null {
  const normalized = normalizeConfidenceScore(score);
  if (normalized === null) return null;
  if (normalized >= 80) return "high";
  if (normalized >= 60) return "medium";
  return "low";
}

export function confidenceLabel(score: unknown): string | null {
  switch (confidenceLevel(score)) {
    case "high":
      return "高";
    case "medium":
      return "中";
    case "low":
      return "低";
    default:
      return null;
  }
}

export function confidenceBadgeText(score: unknown): string | null {
  const normalized = normalizeConfidenceScore(score);
  const label = confidenceLabel(normalized);
  return normalized === null || label === null ? null : `AI 信心：${label} ${normalized}/100`;
}
