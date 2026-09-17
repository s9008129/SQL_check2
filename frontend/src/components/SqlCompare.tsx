import { useMemo, useState } from "react";
import type { AdviceItem, AiResult } from "../types/api";
import SqlEditor from "./SqlEditor";
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

/**
 * Every advice item that carries a SQL fragment becomes one "segment" for
 * the per-advice diff list. `before` comes from the model when it copied
 * the original fragment verbatim; otherwise we try to locate the closest
 * original line so the reviewer still gets a side-by-side view.
 */
// "若 TAX_CD 為 2 碼且 SUBTAX_CD 為 1 碼：WHERE ..." — the model sometimes keeps
// the business assumption as a prefix inside `example`; split it off so the
// diff compares SQL with SQL and the assumption is shown as a note.
const ASSUMPTION_PREFIX_RE = /^((?:若|假設|如果)[^：:]{1,80})[：:]\s*/;

export function splitAssumption(example: string): { sql: string; assumption: string | null } {
  const m = ASSUMPTION_PREFIX_RE.exec(example);
  if (!m) return { sql: example, assumption: null };
  return { sql: example.slice(m[0].length).trim(), assumption: m[1] };
}

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
 * SQL 寫法比較區 (PRD §33): 原始 SQL 永遠保留、建議寫法只供參考。2026-09-17:
 * a full rewrite is shown as a line-aligned, word-highlighted diff; every
 * advice item with a SQL fragment is additionally listed as its own
 * before/after diff, so 「僅提供方向」 still shows precisely what to change.
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

  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (!suggestedSql) return;
    try {
      await navigator.clipboard.writeText(suggestedSql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      window.alert("請手動選取並複製建議寫法。");
    }
  }

  const outcome = ai.suggested_sql?.outcome;

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
        {suggestedSql !== null ? (
          <div className="sql-box sql-box-light">
            <div className="sql-head">
              <span>
                原始 SQL（COST {formatCost(cost)}）與建議寫法逐行對照 · <mark className="diff-add legend">黃底</mark> 為建議修改處
              </span>
              <button className="copy-btn" type="button" onClick={() => void handleCopy()}>
                {copied ? "已複製" : "複製建議寫法"}
              </button>
            </div>
            <FullSqlDiff original={originalSql} suggested={suggestedSql} />
          </div>
        ) : (
          <div className="sql-grid">
            <div className="sql-box">
              <div className="sql-head">
                <span>原始 SQL</span>
                <span>COST {formatCost(cost)}</span>
              </div>
              <SqlEditor value={originalSql} readOnly variant="dark" minHeightPx={180} ariaLabel="原始 SQL" />
            </div>

            <div className="sql-box suggested">
              <div className="sql-head">
                <span>建議寫法</span>
              </div>
              {ai.status === "pending" ? (
                <div className="sql-fallback">{AI_PENDING_MESSAGE}</div>
              ) : ai.status === "unavailable" ? (
                <div className="sql-fallback">{ai.message?.trim() ? ai.message : AI_UNAVAILABLE_MESSAGE}</div>
              ) : (
                <div className={`sql-fallback${outcome === "not_needed" ? " sql-fallback-good" : ""}`}>
                  {/* Three genuinely different situations, three messages:
                      the SQL is already fine; improvements exist but need a
                      business assumption (advice only, see segment diffs
                      below); or the server gated / rejected a rewrite (PRD
                      §25.4 fixed copy). */}
                  <p>
                    {outcome === "not_needed"
                      ? SUGGESTED_SQL_NOT_NEEDED_MESSAGE
                      : outcome === "advice_only"
                        ? SUGGESTED_SQL_ADVICE_ONLY_MESSAGE
                        : SUGGESTED_SQL_NOT_AVAILABLE_MESSAGE}
                  </p>
                  {ai.suggested_sql?.reason && ai.suggested_sql.reason !== SUGGESTED_SQL_NOT_AVAILABLE_MESSAGE && (
                    <p className="sql-fallback-reason">{ai.suggested_sql.reason}</p>
                  )}
                </div>
              )}
            </div>
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
