import ExecutionPlanInput from "./ExecutionPlanInput";
import FileUpload from "./FileUpload";
import SqlEditor from "./SqlEditor";

export interface InputPanelProps {
  applicationNo: string;
  onApplicationNoChange: (value: string) => void;
  costText: string;
  onCostTextChange: (value: string) => void;
  onCostBlur: () => void;
  sql: string;
  onSqlChange: (value: string) => void;
  executionPlan: string;
  onExecutionPlanChange: (value: string) => void;
  onFileExtracted: (sql: string, message: string) => void;
  onSubmit: () => void;
  onClear: () => void;
  submitting: boolean;
  validationError: string | null;
}

/** 左側／頂部輸入工作區 (PRD §34): 申請單號、COST、SQL Editor、附件上傳、開始檢核、清除。 */
export default function InputPanel({
  applicationNo,
  onApplicationNoChange,
  costText,
  onCostTextChange,
  onCostBlur,
  sql,
  onSqlChange,
  executionPlan,
  onExecutionPlanChange,
  onFileExtracted,
  onSubmit,
  onClear,
  submitting,
  validationError,
}: InputPanelProps) {
  return (
    <section className="panel input-card">
      <div className="eyebrow">SQL 檢核</div>
      <h2>輸入檢核資料</h2>
      <p className="lead">輸入申請單號、SQL 與 COST，即可開始檢核。</p>

      <div className="field">
        <label className="label" htmlFor="appNo">
          <span>
            申請單號 <span className="required">*</span>
          </span>
        </label>
        <input
          className="input"
          id="appNo"
          value={applicationNo}
          disabled={submitting}
          onChange={(event) => onApplicationNoChange(event.target.value)}
          placeholder="例如：115000218"
        />
      </div>

      <div className="field">
        <label className="label" htmlFor="costInput">
          <span>
            COST 值 <span className="required">*</span>
          </span>
        </label>
        <input
          className="input"
          id="costInput"
          inputMode="numeric"
          value={costText}
          disabled={submitting}
          onChange={(event) => onCostTextChange(event.target.value)}
          onBlur={onCostBlur}
          placeholder="例如：68,420"
        />
      </div>

      <div className="field">
        <label className="label" htmlFor="sqlInput">
          <span>
            SQL <span className="required">*</span>
          </span>
          <span style={{ fontWeight: 500, color: "#8a94a6" }}>可直接貼上</span>
        </label>
        <SqlEditor
          value={sql}
          onChange={onSqlChange}
          readOnly={submitting}
          variant="light"
          minHeightPx={250}
          ariaLabel="SQL 輸入"
        />
      </div>

      <FileUpload onExtracted={onFileExtracted} disabled={submitting} />

      <div className="plan-divider" aria-hidden="true" />
      <ExecutionPlanInput
        value={executionPlan}
        onChange={onExecutionPlanChange}
        disabled={submitting}
      />

      {validationError && <div className="validation-error">{validationError}</div>}

      <button className="primary" type="button" onClick={onSubmit} disabled={submitting}>
        {submitting ? "檢核中…" : "開始檢核"}
      </button>
      <button className="clear" type="button" onClick={onClear} disabled={submitting}>
        清除內容
      </button>
    </section>
  );
}
