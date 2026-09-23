import type { AdviceItem, AiResult, PerformanceEvidence } from "../types/api";
import { AI_PENDING_MESSAGE, AI_UNAVAILABLE_MESSAGE, VERIFIED_REWRITE_EXPLANATION } from "../lib/copy";
import { assessmentConfidenceText, confidenceBadgeText, confidenceLevel } from "../lib/confidence";
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
    summary: "欄位先做函數處理，資料庫會多一道工作；能直接比對原始欄位時，通常比較省事。",
    note: "這代表有改善空間，但不代表每一支 SQL 都一定會變快。",
  },
  ORACLE11G_PREFIX_LIKE_RANGE_SCAN: {
    title: "從固定文字開頭比對",
    summary: "像 '13%' 這種從固定文字開頭比對的寫法，比較容易先縮小要找的資料範圍。",
  },
  ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT: {
    title: "前面有萬用字元",
    summary: "如果 LIKE 一開始就是 % 或 _，資料庫比較難從開頭快速縮小搜尋範圍。",
    note: "這次改寫可以是安全的，但不能因此認定一定會變快。",
  },
  ORACLE11G_SUBQUERY_UNNESTING: {
    title: "避免重複找同一批資料",
    summary: "同一張表反覆查找最新資料，可能做了重複工作；可評估先整理一次再使用。",
    note: "先確認同一時間有多筆最新資料時，結果應該怎麼保留。",
  },
  ORACLE11G_VISIT_DATA_FEWER_TIMES: {
    title: "減少重複讀取",
    summary: "同一批資料如果重複讀很多次，就可能做了重複工作；可評估集中處理。",
    note: "合併前要先確認查詢結果不會改變。",
  },
  ORACLE11G_IMPLICIT_CONVERSION: {
    title: "避免多做一次資料轉換",
    summary: "兩邊資料格式不同時，資料庫可能要先轉換一次；格式一致時通常比較省事。",
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
      summary: "這個寫法有調整空間，可以先從簡化條件或減少重複工作開始檢查。",
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
  const level = confidenceLevel(score);
  if (!text || !level) return null;
  return (
    <span
      className={`badge confidence-badge confidence-${level}`}
      data-testid="confidence-badge"
      title="AI 對這項建議的把握程度；高可優先參考，中、低建議先確認再使用。"
    >
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
  const assessmentLevel =
    ai.status === "ok" ? confidenceLevel(ai.assessment_confidence_score) : null;
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
              <span className="badge yellow" data-testid="oracle-evidence-count">
                改善重點 {performanceEvidence.length} 項
              </span>
            )}
            {ai.status === "ok" && <span className="badge purple">AI 建議 {ai.advice.length} 項</span>}
            {assessmentConfidence && (
              <span
                className={`badge assessment-confidence-badge confidence-${assessmentLevel ?? "medium"}`}
                data-testid="assessment-confidence-badge"
                title="AI 對這次整體判讀的把握程度；高可優先參考，中、低建議先確認再使用。"
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
            <div className="evidence-source-note oracle-source-note" data-testid="oracle-evidence-note">
              <span className="badge yellow">Oracle 11g 官方依據</span>
              <span>
                效能改善說明依據 Oracle Database 11g 官方效能調校文件，並結合 SQLCheck 檢核結果整理。
              </span>
            </div>
            <div className="evidence-learning-heading">為什麼這樣可能比較快</div>
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
                      {item.strength === "conditional" && (
                        <span className="badge yellow">需先確認</span>
                      )}
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
            {hasConfidence && (
              <div className="confidence-guide" data-testid="confidence-guide">
                <strong>AI 信心怎麼看？</strong>
                <span>高：可優先參考；中、低：代表仍有不確定資訊，建議先確認再使用。</span>
              </div>
            )}
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
                <span>AI 建議是改善參考；真正可安全改寫的內容，仍以「系統已驗證」標示為準。</span>
                {hasConfidence && (
                  <span className="confidence-disclaimer">
                    AI 信心是採用時的參考，不是保證；中、低信心的建議請更保守確認。
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
