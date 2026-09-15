import { diffLines } from "diff";

export type DiffLineTag = "added" | "removed";

export interface SqlLineDiff {
  originalLineClasses: Map<number, DiffLineTag>;
  suggestedLineClasses: Map<number, DiffLineTag>;
}

/**
 * Line-level diff between the original SQL and the AI-suggested rewrite,
 * expressed as 1-based line-number -> tag maps so a CodeMirror extension
 * can shade individual lines (PRD §33 "可顯示簡單 Diff highlight").
 */
export function computeSqlLineDiff(original: string, suggested: string): SqlLineDiff {
  const parts = diffLines(original, suggested);
  const originalLineClasses = new Map<number, DiffLineTag>();
  const suggestedLineClasses = new Map<number, DiffLineTag>();

  let originalLine = 1;
  let suggestedLine = 1;

  for (const part of parts) {
    const lineCount = part.value.split("\n").length - (part.value.endsWith("\n") ? 1 : 0);
    if (part.added) {
      for (let i = 0; i < lineCount; i++) suggestedLineClasses.set(suggestedLine + i, "added");
      suggestedLine += lineCount;
    } else if (part.removed) {
      for (let i = 0; i < lineCount; i++) originalLineClasses.set(originalLine + i, "removed");
      originalLine += lineCount;
    } else {
      originalLine += lineCount;
      suggestedLine += lineCount;
    }
  }

  return { originalLineClasses, suggestedLineClasses };
}
