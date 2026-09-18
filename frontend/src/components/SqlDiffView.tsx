import { useMemo } from "react";
import type { DiffToken } from "../lib/sqlDiff";
import { computeAlignedDiff, computeWordDiff } from "../lib/sqlDiff";

function Tokens({ tokens }: { tokens: DiffToken[] }) {
  return (
    <>
      {tokens.map((t, i) =>
        t.kind === "same" ? (
          <span key={i}>{t.value}</span>
        ) : (
          <mark key={i} className={t.kind === "added" ? "diff-add" : "diff-del"}>
            {t.value}
          </mark>
        ),
      )}
    </>
  );
}

export interface FullSqlDiffProps {
  original: string;
  suggested: string;
}

/**
 * Whole-statement, line-aligned, word-highlighted diff (2026-09-17 user
 * request): every differing token on the right gets a bright yellow mark,
 * the token it replaced on the left gets a red mark, and whole added /
 * removed lines are shaded so the reviewer can see exactly what changed.
 */
export function FullSqlDiff({ original, suggested }: FullSqlDiffProps) {
  const rows = useMemo(() => computeAlignedDiff(original, suggested), [original, suggested]);
  return (
    <div className="diff-table" role="table" aria-label="原始 SQL 與 AI 建議寫法逐行對照">
      <div className="diff-col-head" role="row">
        <span>原始 SQL</span>
        <span>系統已確認的建議寫法</span>
      </div>
      {rows.map((row, i) => (
        <div className={`diff-row diff-row-${row.kind}`} role="row" key={i}>
          <div className={`diff-cell${row.left ? "" : " diff-cell-empty"}`} role="cell">
            {row.left && (
              <>
                <span className="diff-ln">{row.left.lineNo}</span>
                <code>
                  <Tokens tokens={row.left.tokens} />
                </code>
              </>
            )}
          </div>
          <div className={`diff-cell${row.right ? "" : " diff-cell-empty"}`} role="cell">
            {row.right && (
              <>
                <span className="diff-ln">{row.right.lineNo}</span>
                <code>
                  <Tokens tokens={row.right.tokens} />
                </code>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export interface FragmentDiffProps {
  title: string;
  before: string;
  after: string;
  note?: string | null;
  /** Server verdict on the fragment (see AdviceItem.verification). */
  verification?: "verified" | "corrected" | "unverified" | null;
}

// 2026-09-17: the label must say how much the reader can trust the fragment.
// Only rule-derived rewrites are called 建議寫法; anything the system could
// not prove equivalent is a sketch.
export const FRAGMENT_LABEL: Record<NonNullable<FragmentDiffProps["verification"]>, string> = {
  verified: "系統已確認的建議寫法",
  corrected: "系統修正後的建議寫法",
  unverified: "示意方向（請勿直接套用）",
};

/**
 * One advice item's before/after fragment, side by side with word-level
 * marks — used for every advice that changes SQL text, whether or not a
 * full rewrite was produced, so "僅提供方向" still shows exactly what to
 * change where.
 */
export function FragmentDiff({ title, before, after, note, verification }: FragmentDiffProps) {
  const { left, right } = useMemo(() => computeWordDiff(before, after), [before, after]);
  const label = verification ? FRAGMENT_LABEL[verification] : "建議片段（需確認後再用）";
  return (
    <div className={`fragment-diff${verification ? ` fragment-${verification}` : ""}`} data-testid="fragment-diff">
      <div className="fragment-title">{title}</div>
      <div className="fragment-grid">
        <div className="fragment-cell">
          <div className="fragment-label">原寫法</div>
          <code>
            <Tokens tokens={left} />
          </code>
        </div>
        <div className={`fragment-cell fragment-after${verification === "unverified" ? " fragment-after-unverified" : ""}`}>
          <div className="fragment-label">{label}</div>
          <code>
            <Tokens tokens={right} />
          </code>
        </div>
      </div>
      {note && <div className="fragment-note">{note}</div>}
    </div>
  );
}
