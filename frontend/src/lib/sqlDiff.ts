import { diffLines, diffWordsWithSpace } from "diff";

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

// ---------------------------------------------------------------------------
// 2026-09-17: word-level, side-by-side diff (user request: 精準的左右對比,
// highlight every differing token in a bright colour so a reviewer can see
// exactly which characters the AI changed, not just "this line differs").
// ---------------------------------------------------------------------------
export type TokenKind = "same" | "added" | "removed";

export interface DiffToken {
  value: string;
  kind: TokenKind;
}

/**
 * Word-level diff of two fragments. Returns the tokens that belong on the
 * left (original: same + removed) and on the right (suggested: same +
 * added) so each side can be rendered independently with its own marks.
 * Case-insensitive on purpose: SQL keywords/identifiers are case-
 * insensitive in Oracle and the AI often normalizes casing, which is not a
 * change worth highlighting.
 */
export function computeWordDiff(before: string, after: string): { left: DiffToken[]; right: DiffToken[] } {
  const parts = diffWordsWithSpace(before, after, { ignoreCase: true });
  const left: DiffToken[] = [];
  const right: DiffToken[] = [];
  for (const part of parts) {
    if (part.added) right.push({ value: part.value, kind: "added" });
    else if (part.removed) left.push({ value: part.value, kind: "removed" });
    else {
      left.push({ value: part.value, kind: "same" });
      right.push({ value: part.value, kind: "same" });
    }
  }
  return { left, right };
}

export type AlignedRowKind = "same" | "changed" | "added" | "removed";

export interface AlignedSide {
  lineNo: number;
  tokens: DiffToken[];
}

export interface AlignedRow {
  kind: AlignedRowKind;
  left: AlignedSide | null;
  right: AlignedSide | null;
}

function splitLines(text: string): string[] {
  const lines = text.split("\n");
  if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

/**
 * Full-SQL aligned diff: pairs each removed line with the added line at the
 * same position inside a hunk (the typical "this condition was rewritten"
 * case) and word-diffs the pair; leftover lines on either side become
 * whole-line added/removed rows. Unchanged lines are kept so the reviewer
 * still sees the complete statement on both sides.
 */
export function computeAlignedDiff(original: string, suggested: string): AlignedRow[] {
  const parts = diffLines(original, suggested);
  const rows: AlignedRow[] = [];
  let leftNo = 1;
  let rightNo = 1;
  let pendingRemoved: string[] = [];
  let pendingAdded: string[] = [];

  const flush = () => {
    const n = Math.max(pendingRemoved.length, pendingAdded.length);
    for (let i = 0; i < n; i++) {
      const before = pendingRemoved[i];
      const after = pendingAdded[i];
      if (before !== undefined && after !== undefined) {
        const { left, right } = computeWordDiff(before, after);
        rows.push({
          kind: "changed",
          left: { lineNo: leftNo++, tokens: left },
          right: { lineNo: rightNo++, tokens: right },
        });
      } else if (before !== undefined) {
        rows.push({ kind: "removed", left: { lineNo: leftNo++, tokens: [{ value: before, kind: "removed" }] }, right: null });
      } else if (after !== undefined) {
        rows.push({ kind: "added", left: null, right: { lineNo: rightNo++, tokens: [{ value: after, kind: "added" }] } });
      }
    }
    pendingRemoved = [];
    pendingAdded = [];
  };

  for (const part of parts) {
    const lines = splitLines(part.value);
    if (part.removed) {
      pendingRemoved.push(...lines);
    } else if (part.added) {
      pendingAdded.push(...lines);
    } else {
      flush();
      for (const line of lines) {
        rows.push({
          kind: "same",
          left: { lineNo: leftNo++, tokens: [{ value: line, kind: "same" }] },
          right: { lineNo: rightNo++, tokens: [{ value: line, kind: "same" }] },
        });
      }
    }
  }
  flush();
  return rows;
}

/**
 * Best-effort locator for an advice `example` that came without a `before`
 * fragment: pick the original line sharing the most identifier-ish tokens
 * with the example (needs at least two shared tokens to count). Returns
 * null when nothing plausible matches so the caller can fall back to
 * showing the example on its own.
 */
/**
 * 2026-09-17 blind-spot fix: the model occasionally puts prose in `example`
 * (「若業務上只需比對開頭，可改為 `A.NAME LIKE '股份%'`；…」). Such text must
 * not be diffed as if it were SQL. Heuristic: after removing quoted string
 * literals (which legitimately hold Chinese, e.g. '%股份'), a SQL fragment
 * contains no CJK characters and no full-width punctuation.
 */
export function looksLikeSqlFragment(text: string): boolean {
  const withoutLiterals = text.replace(/'(?:[^']|'')*'/g, "''");
  return !/[㐀-鿿＀-￯　-〿]/.test(withoutLiterals);
}

export function locateOriginalFragment(originalSql: string, example: string): string | null {
  const tokenize = (s: string) =>
    new Set(
      s
        .toLowerCase()
        .split(/[^a-z0-9_.]+/)
        .filter((t) => t.length >= 2 && !/^(and|or|the|where|select|from)$/.test(t)),
    );
  const wanted = tokenize(example);
  if (wanted.size === 0) return null;
  let best: { line: string; score: number } | null = null;
  for (const line of splitLines(originalSql)) {
    const have = tokenize(line);
    let score = 0;
    for (const t of wanted) if (have.has(t)) score++;
    if (score >= 2 && (!best || score > best.score)) best = { line: line.trim(), score };
  }
  return best ? best.line : null;
}
