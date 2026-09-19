import { useMemo } from "react";
import type { AdviceItem, AiResult } from "../types/api";
import { FragmentDiff, FullSqlDiff } from "./SqlDiffView";
import { locateOriginalFragment, looksLikeSqlFragment } from "../lib/sqlDiff";

export interface SqlCompareProps {
  originalSql: string;
  ai: AiResult;
}

interface Segment {
  title: string;
  before: string | null;
  after: string;
  note: string | null;
  verification: AdviceItem["verification"];
}

const VERIFICATION_NOTE: Record<NonNullable<AdviceItem["verification"]>, string | null> = {
  verified: null,
  corrected: "AI 原本寫法已由系統修正。",
  unverified: null,
};

const ASSUMPTION_PREFIX_RE = /^((?:若|假設|如果)[^：:]{1,80})[：:]\s*/;

export function splitAssumption(example: string): { sql: string; assumption: string | null } {
  const m = ASSUMPTION_PREFIX_RE.exec(example);
  if (!m) return { sql: example, assumption: null };
  return { sql: example.slice(m[0].length).trim(), assumption: m[1] };
}

function toSegments(originalSql: string, advice: AdviceItem[]): Segment[] {
  const segments: Segment[] = [];
  for (const item of advice) {
    // Defense in depth: old/corrupt API responses must never surface
    // unverified copyable SQL in the comparison panel.
    if (item.verification !== "verified" && item.verification !== "corrected") continue;
    const raw = item.example?.trim();
    if (!raw) continue;
    const { sql: after, assumption } = splitAssumption(raw);
    if (!after || !looksLikeSqlFragment(after)) continue;
    const before = item.before?.trim() || locateOriginalFragment(originalSql, after);
    const verification = item.before?.trim() ? (item.verification ?? null) : null;
    const notes = [
      assumption ? `前提：${assumption}` : null,
      item.assumption ? `前提：${item.assumption}` : null,
      verification ? VERIFICATION_NOTE[verification] : null,
      before ? null : "找不到對應的原寫法。",
    ].filter((n): n is string => n !== null);
    segments.push({ title: item.title, before, after, note: notes.length ? notes.join("　") : null, verification });
  }
  return segments;
}

export default function SqlCompare({ originalSql, ai }: SqlCompareProps) {
  const suggestedSql =
    ai.status === "ok" && ai.suggested_sql?.available && ai.suggested_sql.sql
      ? ai.suggested_sql.sql
      : null;

  const segments = useMemo(
    () => (ai.status === "ok" ? toSegments(originalSql, ai.advice) : []),
    [ai.status, ai.advice, originalSql],
  );

  if (ai.status !== "ok" || (suggestedSql === null && segments.length === 0)) {
    return null;
  }

  const statusTone = "green";
  const statusText = "已確認";

  return (
    <section className={`card card-compare card-compare-${statusTone}`}>
      <div className="card-head">
        <div className="card-title">建議寫法</div>
        <span className={`badge ${statusTone}`}>{statusText}</span>
      </div>
      <div className="card-body">
        {suggestedSql !== null && (
          <div className="sql-box sql-box-light">
            <div className="sql-head">
              <span>
                原寫法與建議寫法對照 · <mark className="diff-add legend">黃底</mark> 為修改處
              </span>
            </div>
            <FullSqlDiff original={originalSql} suggested={suggestedSql} />
          </div>
        )}

        {segments.length > 0 && (
          <div className="segment-list">
            <div className="segment-list-title">寫法對照</div>
            {segments.map((seg, i) =>
              seg.before ? (
                <FragmentDiff
                  key={i}
                  title={`${i + 1}. ${seg.title}`}
                  before={seg.before}
                  after={seg.after}
                  note={seg.note}
                  verification={seg.verification}
                />
              ) : (
                <div className="fragment-diff fragment-unverified" key={i} data-testid="fragment-diff">
                  <div className="fragment-title">
                    {i + 1}. {seg.title}
                  </div>
                  <div className="fragment-cell fragment-after fragment-after-unverified">
                    <div className="fragment-label">參考寫法（需確認）</div>
                    <code>{seg.after}</code>
                  </div>
                  {seg.note && <div className="fragment-note">{seg.note}</div>}
                </div>
              ),
            )}
          </div>
        )}
      </div>
    </section>
  );
}
