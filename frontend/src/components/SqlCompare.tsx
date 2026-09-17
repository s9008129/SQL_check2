import { useMemo, useState } from "react";
import type { Extension } from "@codemirror/state";
import type { AiResult } from "../types/api";
import SqlEditor from "./SqlEditor";
import { computeSqlLineDiff } from "../lib/sqlDiff";
import { diffHighlightExtension } from "../lib/diffHighlight";
import { formatCost } from "../lib/cost";
import {
  AI_PENDING_MESSAGE,
  AI_UNAVAILABLE_MESSAGE,
  SUGGESTED_SQL_ADVICE_ONLY_MESSAGE,
  SUGGESTED_SQL_NOT_AVAILABLE_MESSAGE,
  SUGGESTED_SQL_NOT_NEEDED_MESSAGE,
} from "../lib/copy";

export interface SqlCompareProps {
  originalSql: string;
  cost: number;
  ai: AiResult;
}

/**
 * SQL 寫法比較區 (PRD §33): 原始 SQL 永遠保留、建議寫法只供參考，兩者並排顯示並以
 * `diff` 套件做行級 highlight。無法提供建議寫法時，右側改顯示 PRD 固定文案，而不是
 * 硬塞第二個編輯器。
 */
export default function SqlCompare({ originalSql, cost, ai }: SqlCompareProps) {
  const suggestedSql =
    ai.status === "ok" && ai.suggested_sql?.available && ai.suggested_sql.sql
      ? ai.suggested_sql.sql
      : null;

  const diff = useMemo(
    () => (suggestedSql !== null ? computeSqlLineDiff(originalSql, suggestedSql) : null),
    [originalSql, suggestedSql],
  );

  const originalExtensions = useMemo<Extension[]>(
    () => (diff ? [diffHighlightExtension(diff.originalLineClasses)] : []),
    [diff],
  );
  const suggestedExtensions = useMemo<Extension[]>(
    () => (diff ? [diffHighlightExtension(diff.suggestedLineClasses)] : []),
    [diff],
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

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="card-title">SQL 寫法比較</div>
          <div className="card-desc">原始 SQL 保留，建議寫法只供參考</div>
        </div>
        <span className="badge blue">對照查看</span>
      </div>
      <div className="card-body">
        <div className="sql-grid">
          <div className="sql-box">
            <div className="sql-head">
              <span>原始 SQL</span>
              <span>COST {formatCost(cost)}</span>
            </div>
            <SqlEditor
              value={originalSql}
              readOnly
              variant="dark"
              minHeightPx={180}
              ariaLabel="原始 SQL"
              extraExtensions={originalExtensions}
            />
          </div>

          <div className="sql-box suggested">
            <div className="sql-head">
              <span>建議寫法</span>
              {suggestedSql && (
                <button className="copy-btn" type="button" onClick={() => void handleCopy()}>
                  {copied ? "已複製" : "複製"}
                </button>
              )}
            </div>
            {ai.status === "pending" ? (
              <div className="sql-fallback">{AI_PENDING_MESSAGE}</div>
            ) : ai.status === "unavailable" ? (
              <div className="sql-fallback">
                {ai.message?.trim() ? ai.message : AI_UNAVAILABLE_MESSAGE}
              </div>
            ) : suggestedSql === null ? (
              <div className={`sql-fallback${ai.suggested_sql?.outcome === "not_needed" ? " sql-fallback-good" : ""}`}>
                {/* Three genuinely different situations, three messages
                    (2026-09-17): the SQL is already fine; improvements
                    exist but need a business assumption (advice only);
                    or the server gated / rejected a rewrite (PRD §25.4
                    fixed copy). */}
                <p>
                  {ai.suggested_sql?.outcome === "not_needed"
                    ? SUGGESTED_SQL_NOT_NEEDED_MESSAGE
                    : ai.suggested_sql?.outcome === "advice_only"
                      ? SUGGESTED_SQL_ADVICE_ONLY_MESSAGE
                      : SUGGESTED_SQL_NOT_AVAILABLE_MESSAGE}
                </p>
                {/* Only show the backend's reason as a second line when it
                    actually adds information (never repeat the fixed copy). */}
                {ai.suggested_sql?.reason && ai.suggested_sql.reason !== SUGGESTED_SQL_NOT_AVAILABLE_MESSAGE && (
                  <p className="sql-fallback-reason">{ai.suggested_sql.reason}</p>
                )}
              </div>
            ) : (
              <SqlEditor
                value={suggestedSql}
                readOnly
                variant="dark"
                minHeightPx={180}
                ariaLabel="建議寫法"
                extraExtensions={suggestedExtensions}
              />
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
