import type { AiResult, ComplianceResult } from "../types/api";
import {
  AI_PENDING_MESSAGE,
  AI_UNAVAILABLE_MESSAGE,
  ESTIMATE_NOT_NEEDED_MESSAGE,
  ESTIMATE_NOTICE_ONLY_MESSAGE,
  POTENTIAL_CAVEAT,
} from "../lib/copy";

export interface EstimateCardProps {
  ai: AiResult;
  compliance: ComplianceResult;
}

/**
 * 建議採用狀態。
 *
 * 這一區回答的是「上面的建議目前可以怎麼用」，不是預測 Oracle 會快多少。
 * 效能提升幅度需要真實執行計畫、統計資訊與測試，SQLCheck 目前不宣稱擁有這些資料。
 */
export default function EstimateCard({ ai, compliance }: EstimateCardProps) {
  const basis = ai.improvement_potential_basis ?? [];
  const confirmedFragments = ai.advice.filter(
    (item) => item.verification === "verified" || item.verification === "corrected",
  ).length;
  const fullRewriteConfirmed = ai.suggested_sql?.outcome === "provided";
  const hasConfirmed = fullRewriteConfirmed || confirmedFragments > 0;

  const basisList =
    basis.length > 0 ? (
      <ul className="potential-basis" aria-label="系統判斷依據">
        {basis.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    ) : null;

  let body: React.ReactNode;
  if (ai.status === "pending") {
    body = <div className="ai-note">{AI_PENDING_MESSAGE}</div>;
  } else if (ai.status === "unavailable") {
    body = <div className="ai-note">{ai.message?.trim() ? ai.message : AI_UNAVAILABLE_MESSAGE}</div>;
  } else if (hasConfirmed) {
    body = (
      <div className="ai-note ai-note-good" data-testid="adoption-confirmed">
        <strong>已有建議寫法由系統確認</strong>
        <p>系統已確認相關改寫不會改變查詢結果；實際執行效率仍請於測試環境確認。</p>
        {basisList}
      </div>
    );
  } else if (compliance.status === "BLOCK") {
    body = (
      <div className="ai-note ai-note-notice" data-testid="adoption-blocked">
        <strong>需要優先處理，但正確改法仍需確認</strong>
        <p>系統已確認有不符合中心規範的項目；若缺少實際查詢目的或業務條件，系統不會自行猜測 WHERE、JOIN 或欄位。</p>
        {basisList}
      </div>
    );
  } else if (ai.improvement_potential == null) {
    body = (
      <div className="ai-note ai-note-good" data-testid="adoption-none">
        {ESTIMATE_NOT_NEEDED_MESSAGE}
      </div>
    );
  } else if (ai.improvement_potential === "notice_only") {
    body = (
      <div className="ai-note ai-note-notice" data-testid="adoption-notice-only">
        {ESTIMATE_NOTICE_ONLY_MESSAGE}
        {basisList}
      </div>
    );
  } else {
    body = (
      <div className="ai-note ai-note-notice" data-testid="adoption-confirm-first">
        <strong>有改善方向，但請先確認再調整</strong>
        <p>目前沒有足夠資訊讓系統確認一段可直接套用的改寫；請依上方建議先確認業務條件。</p>
        {basisList}
      </div>
    );
  }

  return (
    <section className="card card-estimate">
      <div className="card-head">
        <div>
          <div className="card-title">建議採用狀態</div>
          <div className="card-desc">告訴你哪些建議可直接參考，哪些需要先確認業務條件</div>
        </div>
      </div>
      <div className="card-body">
        {body}
        {ai.status === "ok" && <div className="estimate-note potential-caveat">⚠ {POTENTIAL_CAVEAT}</div>}
      </div>
    </section>
  );
}
