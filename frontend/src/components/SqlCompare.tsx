import { useMemo, useState } from "react";
import type { AdviceItem, AiResult, VerifiedRewrite } from "../types/api";
import { ConfidenceBadge } from "./ImprovementAdvice";
import { FragmentDiff, FullSqlDiff } from "./SqlDiffView";
import { locateOriginalFragment, looksLikeSqlFragment } from "../lib/sqlDiff";
import { REWRITE_COMPARE_EXPLANATION } from "../lib/copy";

export interface SqlCompareProps {
  originalSql: string;
  ai: AiResult;
  verifiedRewrites?: VerifiedRewrite[];
}

interface Segment {
  title: string;
  before: string;
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
    if (!before) continue;
    const verification = item.verification ?? null;
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

function toVerifiedRewriteSegments(rewrites: VerifiedRewrite[]): Segment[] {
  return rewrites.map((rewrite) => ({
    title: rewrite.title,
    before: rewrite.before,
    after: rewrite.after,
    note: null,
    verification: "verified",
  }));
}

export default function SqlCompare({ originalSql, ai, verifiedRewrites }: SqlCompareProps) {
  const [copied, setCopied] = useState(false);
  const suggestedSql =
    ai.status === "ok" && ai.suggested_sql?.available && ai.suggested_sql.sql
      ? ai.suggested_sql
      : null;
  const suggestedSqlText = suggestedSql?.sql ?? null;
  const fullRewriteConfidence =
    suggestedSql?.outcome === "provided" ? suggestedSql.confidence_score : null;

  const segments = useMemo(
    () => {
      // New API responses own this fragment list. An intentionally empty
      // array means the deterministic pass ran and found no rewrite; it must
      // not be repopulated from legacy AI advice. Only an absent field is an
      // old-backend payload and may use the legacy fallback.
      if (verifiedRewrites !== undefined) return toVerifiedRewriteSegments(verifiedRewrites);
      return ai.status === "ok" ? toSegments(originalSql, ai.advice) : [];
    },
    [ai.status, ai.advice, originalSql, verifiedRewrites],
  );

  if (suggestedSqlText === null && segments.length === 0) {
    return null;
  }

  const statusTone = "green";
  const statusText = "查詢結果不變";

  async function copySuggestedSql() {
    if (!suggestedSqlText || !navigator.clipboard?.writeText) return;
    try {
      await navigator.clipboard.writeText(suggestedSqlText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard permission failures should not affect the diff itself.
    }
  }

  return (
    <section className={`card card-compare card-compare-${statusTone}`}>
      <div className="card-head">
        <div>
          <div className="card-title">改寫對照</div>
          <div className="card-desc">{REWRITE_COMPARE_EXPLANATION}</div>
        </div>
        <div className="compare-head-badges">
          <span className={`badge ${statusTone}`}>{statusText}</span>
          <ConfidenceBadge score={fullRewriteConfidence} />
        </div>
      </div>
      <div className="card-body">
        {segments.length > 0 && (
          <div className="segment-list">
            <div className="segment-list-title">重點改寫</div>
            {segments.map((seg, i) => (
              <FragmentDiff
                key={i}
                title={`${i + 1}. ${seg.title}`}
                before={seg.before}
                after={seg.after}
                note={seg.note}
                verification={seg.verification}
              />
            ))}
          </div>
        )}

        {suggestedSqlText !== null && (
          <details className="full-sql-details">
            <summary>完整 SQL</summary>
            <div className="sql-box sql-box-light">
              <div className="sql-head">
                <span>
                  原寫法與改後寫法對照 · <mark className="diff-add legend">黃底</mark> 為修改處
                </span>
                <button className="copy-btn copy-sql-btn" type="button" onClick={() => void copySuggestedSql()}>
                  {copied ? "已複製" : "複製改後 SQL"}
                </button>
              </div>
              <FullSqlDiff original={originalSql} suggested={suggestedSqlText} />
            </div>
          </details>
        )}
      </div>
    </section>
  );
}
