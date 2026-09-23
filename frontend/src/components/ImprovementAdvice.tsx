import type { AdviceItem, AiResult, PerformanceEvidence } from "../types/api";
import { AI_PENDING_MESSAGE, AI_UNAVAILABLE_MESSAGE, VERIFIED_REWRITE_EXPLANATION } from "../lib/copy";
import { assessmentConfidenceText, confidenceBadgeText } from "../lib/confidence";
import { looksLikeSqlFragment } from "../lib/sqlDiff";

export interface ImprovementAdviceProps {
  ai: AiResult;
  performanceEvidence?: PerformanceEvidence[];
}

type EvidenceLevel = "confirmed" | "review" | "info";

type FriendlyEvidenceCopy = {
  title: string;
  summary: string;
  note?: string;
};

const FRIENDLY_EVIDENCE_COPY: Record<string, FriendlyEvidenceCopy> = {
  ORACLE11G_TRANSFORMED_COLUMN: {
    title: "直接比對原始欄位",
    summary: "這支 SQL 先對欄位做函數處理；如果能直接比對原始欄位，資料庫通常比較容易找資料。",
    note: "是否真的變快，還是要看 SQL Developer F10 執行計畫。",
  },
  ORACLE11G_PREFIX_LIKE_RANGE_SCAN: {
    title: "從固定文字開頭比對",
    summary: "像 '13%' 這種固定開頭的寫法，有合適索引時，較有機會先縮小搜尋範圍。",
  },
  ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT: {
    title: "前面有萬用字元",
    summary: "如果 LIKE 一開始就是 % 或 _，索引能幫上的忙通常比較有限。",
    note: "這次改寫可以是安全的，但不能因此認定一定會變快。",
  },
  ORACLE11G_SUBQUERY_UNNESTING: {
    title: "避免重複找同一批資料",
    summary: "這支 SQL 重複到同一張表找最新資料，可評估先集中算一次，再和主查詢 JOIN。",
    note: "先確認同一時間有多筆最新資料時，結果應該怎麼保留。",
  },
  ORACLE11G_VISIT_DATA_FEWER_TIMES: {
    title: "減少重複讀取",
    summary: "同一批資料如果被重複讀很多次，可評估集中處理，減少重複工作。",
    note: "合併前要先確認查詢結果不會改變。",
  },
  ORACLE11G_IMPLICIT_CONVERSION: {
    title: "避免多做一次資料轉換",
    summary: "比較兩邊的資料型態不同時，資料庫可能要先做轉換，會多一道處理。",
    note: "這一項需要欄位型態資訊才能確認。",
  },
  ORACLE11G_IN_LIST_LIMIT: {
    title: "同欄位 OR 可整理成 IN",
    summary: "同一欄位的一連串 OR 可以整理成 IN，條件會更集中，也比較容易閱讀。",
    note: "這主要是安全整理寫法，不代表一定會更快。",
  },
};

function friendlyEvidenceCopy(item: PerformanceEvidence): FriendlyEvidenceCopy {
  return (
    FRIENDLY_EVIDENCE_COPY[item.evidence_id] ?? {
      title: "可注意的效能方向",
      summary: "這個寫法有調整空間；是否真的有幫助，建議再搭配 SQL Developer F10 執行計畫確認。",
      note: item.strength === "conditional" ? "調整前先確認查詢結果是否會改變。" : undefined,
    }
  );
}

const EVIDENCE_META: Record<EvidenceLevel, { label: string; tone: string; badge: string; title: string; explanation: string | null }> = {
  confirmed: {
    label: "可使用此改寫",
    tone: "a-confirmed",
    badge: "green",
    title: `${VERIFIED_REWRITE_EXPLANATION}正式使用前仍請測試。`,
    explanation: VERIFIED_REWRITE_EXPLANATION,
  },
  review: {
    label: "需先確認再改",
    tone: "a-review",
    badge: "yellow",
    title: "改善方向具參考價值，但系統無法只靠 SQL 文字確認查詢結果是否一致。",
    explanation: null,
  },
  info: {
    label: "僅供參考",
    tone: "a-info",
    badge: "purple",
    title: "這是撰寫或治理上的提醒，不代表本案已證明存在效能問題。",
    explanation: null,
  },
};

function canShowConcreteExample(item: AdviceItem): boolean {
  return item.verification === "verified" || item.verification === "corrected";
}

export function ConfidenceBadge({ score }: { score: unknown }) {
  const text = confidenceBadgeText(score);
  if (!text) return null;
  return (
    <span className="badge purple confidence-badge" data-testid="confidence-badge">
      {text}
    </span>
  );
}

export function adviceEvidenceLevel(item: AdviceItem): EvidenceLevel {
  if (item.verification === "verified" || item.verification === "corrected") return "confirmed";
  if (item.verification === "unverified") return "review";

  const example = item.example?.trim() ?? "";
  if (item.before?.trim() && example) return "review";
  if (example && looksLikeSqlFragment(example)) return "review";
  return "info";
}

/**
 * 智慧改善建議：不再把 Gemma 的 high/medium/low impact 當成主要視覺訊號。
 * 模型看不到 execution plan / index / statistics，因此畫面改以伺服器可驗證的
 * 「系統可確認／需人工確認／觀念提醒」呈現可信度與採用方式。
 */
export default function ImprovementAdvice({ ai, performanceEvidence = [] }: ImprovementAdviceProps) {
  const assessmentConfidence =
    ai.status === "ok" ? assessmentConfidenceText(ai.assessment_confidence_score) : null;
  const hasConfidence =
    ai.status === "ok" &&
    (assessmentConfidence !== null ||
      ai.advice.some((item) => confidenceBadgeText(item.confidence_score) !== null) ||
      (ai.suggested_sql?.available === true &&
        ai.suggested_sql.outcome === "provided" &&
        confidenceBadgeText(ai.suggested_sql.confidence_score) !== null));

  return (
    <section className="card card-ai">
      <div className="card-head">
        <div>
          <div className="card-title"><span className="ai-spark" aria-hidden="true">✦</span> 智慧改善建議</div>
        </div>
        {(ai.status === "ok" || performanceEvidence.length > 0) && (
          <div className="advice-badges">
            {performanceEvidence.length > 0 && (
              <span className="badge green" data-testid="oracle-evidence-count">
                系統依據 {performanceEvidence.length} 項
              </span>
            )}
            {ai.status === "ok" && <span className="badge purple">AI 建議 {ai.advice.length} 項</span>}
            {assessmentConfidence && (
              <span
                className="badge purple assessment-confidence-badge"
                data-testid="assessment-confidence-badge"
                title="AI 對目前可見 SQL 文字與系統提供證據的自評；不是 SQL 正確率，也不代表可直接執行。"
              >
                {assessmentConfidence}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="card-body">
        {performanceEvidence.length > 0 && (
          <>
            <div className="evidence-source-note" data-testid="oracle-evidence-note">
              <span className="badge green">Oracle 11g 官方依據</span>
              <span>
                以下效能說明參考 Oracle Database 11g 官方文件，已整理成白話；是否真的變快，請再看 SQL Developer F10 執行計畫。
              </span>
            </div>
            <div className="advice-grid system-evidence-grid" data-testid="performance-evidence-list">
              {performanceEvidence.map((item) => {
                const copy = friendlyEvidenceCopy(item);
                return (
                  <div
                    className={`advice-box system-evidence-box ${item.strength === "strong" ? "a-confirmed" : "a-review"}`}
                    key={`${item.pattern_id}-${item.evidence_id}-${item.statement_indexes.join("-")}`}
                    data-testid="performance-evidence"
                  >
                    <div className="advice-title-row">
                      <h4>{copy.title}</h4>
                      <div className="advice-badges">
                        <span className="badge green">系統依據</span>
                        {item.strength === "conditional" && <span className="badge yellow">需確認</span>}
                      </div>
                    </div>
                    <p>{copy.summary}</p>
                    {copy.note && <div className="friendly-evidence-note">{copy.note}</div>}
                  </div>
                );
              })}
            </div>
          </>
        )}

        {ai.status === "pending" && <div className="ai-note">{AI_PENDING_MESSAGE}</div>}

        {ai.status === "unavailable" && (
          <div className="ai-note">{ai.message?.trim() ? ai.message : AI_UNAVAILABLE_MESSAGE}</div>
        )}

        {ai.status === "ok" && (
          <>
            {ai.advice.length === 0 ? (
              <div className="ai-note">{ai.summary?.trim() || "目前沒有額外的改善建議。"}</div>
            ) : (
              <div className="advice-grid">
                {ai.advice.map((item, index) => {
                  const evidence = EVIDENCE_META[adviceEvidenceLevel(item)];
                  return (
                    <div className={`advice-box ${evidence.tone}`} key={`${item.title}-${index}`}>
                      <div className="advice-title-row">
                        <h4>{item.title}</h4>
                        <div className="advice-badges">
                          <span className="badge purple ai-source-badge" data-testid="ai-advice-badge">
                            AI 建議
                          </span>
                          <span className={`badge ${evidence.badge} evidence-badge`} title={evidence.title}>
                            {evidence.label}
                          </span>
                          <ConfidenceBadge score={item.confidence_score} />
                        </div>
                      </div>
                      {evidence.explanation && <div className="evidence-explanation">{evidence.explanation}</div>}
                      <p>{item.explanation}</p>
                      {item.example && canShowConcreteExample(item) && <code>{item.example}</code>}
                    </div>
                  );
                })}
              </div>
            )}
            {(ai.advice.length > 0 || hasConfidence) && (
              <div className="ai-disclaimer">
                <span>AI 建議僅供參考，不代表實際效能提升；採用前請先測試。</span>
                {hasConfidence && (
                  <span className="confidence-disclaimer">
                    AI 信心僅描述模型在目前證據下的自評；不代表實際效能、正確率或系統驗證結果。
                  </span>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
