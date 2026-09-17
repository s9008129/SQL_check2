import { useMemo } from "react";
import type { AdviceItem, AiResult } from "../types/api";
import { FragmentDiff, FullSqlDiff } from "./SqlDiffView";
import { locateOriginalFragment } from "../lib/sqlDiff";
import { formatCost } from "../lib/cost";
import {
  AI_PENDING_MESSAGE,
  AI_UNAVAILABLE_MESSAGE,
  SUGGESTED_SQL_ADVICE_ONLY_MESSAGE,
  SUGGESTED_SQL_NOT_AVAILABLE_MESSAGE,
  SUGGESTED_SQL_NOT_NEEDED_MESSAGE,
  SUGGESTED_SQL_WARNING,
} from "../lib/copy";

export interface SqlCompareProps {
  originalSql: string;
  cost: number;
  ai: AiResult;
}

interface Segment {
  title: string;
  before: string | null;
  after: string;
  note: string | null;
}

// "若 TAX_CD 為 2 碼且 SUBTAX_CD 為 1 碼：WHERE ..." — the model sometimes keeps
// the business assumption as a prefix inside `example`; split it off so the
// diff compares SQL with SQL and the assumption is shown as a note.
const ASSUMPTION_PREFIX_RE = /^((?:若|假設|如果)[^：:]{1,80})[：:]\s*/;

export function splitAssumption(example: string): { sql: string; assumption: string | null } {
  const m = ASSUMPTION_PREFIX_RE.exec(example);
  if (!m) return { sql: example, assumption: null };
  return { sql: example.slice(m[0].length).trim(), assumption: m[1] };
}

/**
 * Every advice item that carries a SQL fragment becomes one "segment" for
 * the per-advice diff list. `before` comes from the model when it copied
 * the original fragment verbatim; otherwise we try to locate the closest
 * original line so the reviewer still gets a side-by-side view.
 */
function toSegments(originalSql: string, advice: AdviceItem[]): Segment[] {
  const segments: Segment[] = [];
  for (const item of advice) {
    const raw = item.example?.trim();
    if (!raw) continue;
    const { sql: after, assumption } = splitAssumption(raw);
    if (!after) continue;
    const before = item.before?.trim() || locateOriginalFragment(originalSql, after);
    const notes = [assumption ? `前提：${assumption}` : null, before ? null : "找不到對應的原始片段，僅顯示建議片段。"].filter(
      (n): n is string => n !== null,
    );
    segments.push({ title: item.title, before, after, note: notes.length ? notes.join("　") : null });
  }
  return segments;
}

/**
 * SQL 寫法比較區 (PRD §33), 2026-09-17 layout: a one-line AI verdict, then
 * — when a full rewrite exists — the whole statement as a line-aligned,
 * word-highlighted diff, then every advice item with a SQL fragment as its
 * own before/after diff. The old side-by-side editor panes were removed
 * (user request): the segment diffs already show the original fragments,
 * and the original statement is visible in the input panel.
 */
export default function SqlCompare({ originalSql, cost, ai }: SqlCompareProps) {
  const suggestedSql =
    ai.status === "ok" && ai.suggested_sql?.available && ai.suggested_sql.sql
      ? ai.suggested_sql.sql
      : null;

  const segments = useMemo(
    () => (ai.status === "ok" ? toSegments(originalSql, ai.advice) : []),
    [ai.status, ai.advice, originalSql],
  );

  const outcome = ai.suggested_sql?.outcome;

  let verdict: React.ReactNode;
  if (ai.status === "pending") {
    verdict = <div className="ai-note">{AI_PENDING_MESSAGE}</div>;
  } else if (ai.status === "unavailable") {
    verdict = <div className="ai-note">{ai.message?.trim() ? ai.message : AI_UNAVAILABLE_MESSAGE}</div>;
  } else if (suggestedSql !== null) {
    verdict = null;
  } else {
    const headline =
      outcome === "not_needed"
        ? SUGGESTED_SQL_NOT_NEEDED_MESSAGE
        : outcome === "advice_only"
          ? SUGGESTED_SQL_ADVICE_ONLY_MESSAGE
          : SUGGESTED_SQL_NOT_AVAILABLE_MESSAGE;
    const reason =
      ai.suggested_sql?.reason && ai.suggested_sql.reason !== SUGGESTED_SQL_NOT_AVAILABLE_MESSAGE
        ? ai.suggested_sql.reason
        : null;
    verdict = (
      <div className={`ai-note${outcome === "not_needed" ? " ai-note-good" : ""}`} data-testid="compare-verdict">
        <p className="verdict-headline">{headline}</p>
        {reason && <p className="verdict-reason">{reason}</p>}
      </div>
    );
  }

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="card-title">SQL 寫法比較</div>
          <div className="card-desc card-warning" role="note">
            ⚠ {SUGGESTED_SQL_WARNING}
          </div>
        </div>
        <span className="badge blue">對照查看</span>
      </div>
      <div className="card-body">
        {verdict}

        {suggestedSql !== null && (
          <div className="sql-box sql-box-light">
            <div className="sql-head">
              <span>
                原始 SQL（COST {formatCost(cost)}）與建議寫法逐行對照 · <mark className="diff-add legend">黃底</mark> 為建議修改處
              </span>
            </div>
            <FullSqlDiff original={originalSql} suggested={suggestedSql} />
          </div>
        )}

        {segments.length > 0 && (
          <div className="segment-list">
            <div className="segment-list-title">逐段對照（每一項建議的原寫法 → 建議寫法）</div>
            {segments.map((seg, i) =>
              seg.before ? (
                <FragmentDiff key={i} title={`${i + 1}. ${seg.title}`} before={seg.before} after={seg.after} note={seg.note} />
              ) : (
                <div className="fragment-diff" key={i} data-testid="fragment-diff">
                  <div className="fragment-title">
                    {i + 1}. {seg.title}
                  </div>
                  <div className="fragment-cell fragment-after">
                    <div className="fragment-label">建議片段</div>
                    <code>{seg.after}</code>
                  </div>
                  <div className="fragment-note">{seg.note}</div>
                </div>
              ),
            )}
          </div>
        )}
      </div>
    </section>
  );
}
