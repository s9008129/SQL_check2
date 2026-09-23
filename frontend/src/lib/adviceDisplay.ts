import type { AdviceItem, VerifiedRewrite } from "../types/api";

const READABILITY_ONLY_RE =
  /(?:可讀性|更?簡潔|較?簡潔|容易閱讀|較易閱讀|易於閱讀|便於閱讀|方便閱讀|容易維護|較易維護|易於維護|便於維護|方便維護|格式更一致)/i;

const PERFORMANCE_SIGNAL_RE =
  /(?:效能|COST|函數|搜尋|查找|查詢範圍|縮小範圍|萬用字元|索引|重複|讀取|處理|轉換|資料量|JOIN|子查詢)/i;

function looksLikeOrToInCleanup(item: AdviceItem): boolean {
  const before = item.before?.trim() ?? "";
  const after = item.example?.trim() ?? "";
  return Boolean(before && after && /\bOR\b/i.test(before) && /\bIN\s*\(/i.test(after));
}

/**
 * Reviewer-facing advice is performance-only.
 *
 * SQLCheck can internally verify syntax-preserving cleanups such as same-column
 * OR→IN, but those do not become "智慧改善建議" unless there is a separate,
 * concrete performance reason. Readability/maintenance-only prose is likewise
 * hidden from the business-facing result.
 */
export function isPerformanceAdvice(item: AdviceItem): boolean {
  if (looksLikeOrToInCleanup(item)) return false;

  const text = `${item.title} ${item.explanation}`;
  if (READABILITY_ONLY_RE.test(text) && !PERFORMANCE_SIGNAL_RE.test(text)) return false;

  return true;
}

export function performanceAdviceItems(items: AdviceItem[]): AdviceItem[] {
  return items.filter(isPerformanceAdvice);
}

export function isPerformanceRewrite(rewrite: VerifiedRewrite): boolean {
  return rewrite.rule !== "or_eq_to_in";
}

export function performanceRewriteItems(items: VerifiedRewrite[] | undefined): VerifiedRewrite[] {
  return (items ?? []).filter(isPerformanceRewrite);
}
