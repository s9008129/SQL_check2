import { describe, expect, it } from "vitest";
import { confidenceLabel, confidenceLevel, normalizeConfidenceScore } from "./confidence";

describe("confidence helpers", () => {
  it.each([
    [100, "high", "高"],
    [80, "high", "高"],
    [79, "medium", "中"],
    [60, "medium", "中"],
    [59, "low", "低"],
    [0, "low", "低"],
  ])("maps %s to the fixed level boundary", (score, level, label) => {
    expect(confidenceLevel(score)).toBe(level);
    expect(confidenceLabel(score)).toBe(label);
  });

  it.each([null, undefined, -1, 101, Number.NaN, 95.5, "95"]) (
    "hides malformed score %s",
    (score) => {
      expect(normalizeConfidenceScore(score)).toBeNull();
      expect(confidenceLevel(score)).toBeNull();
      expect(confidenceLabel(score)).toBeNull();
    },
  );
});
