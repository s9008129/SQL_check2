import { useRef, useState } from "react";
import { ApiError, extractPlan } from "../api/client";

export interface ExecutionPlanInputProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

type StatusTone = "success" | "error" | "info";

export default function ExecutionPlanInput({
  value,
  onChange,
  disabled = false,
}: ExecutionPlanInputProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ text: string; tone: StatusTone } | null>(null);

  async function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;

    setBusy(true);
    setStatus(null);
    try {
      const response = await extractPlan(file);
      onChange(response.plan_text);
      setStatus({ text: `✓ ${response.message}`, tone: response.truncated ? "info" : "success" });
    } catch (error) {
      const detail =
        error instanceof ApiError
          ? error.detail
          : "執行計畫附件讀取失敗，請改用 TXT／CSV 或直接貼上文字。";
      setStatus({ text: detail, tone: "error" });
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="plan-input">
      <div className="label plan-input-label">
        <span>SQL Developer 執行計畫（選填）</span>
        <span className="plan-optional">正式資料庫 F10 證據</span>
      </div>

      <div className="plan-guidance">
        <strong>標準流程：正式資料庫 F10 Explain Plan</strong>
        <span>：提供資料庫預估的執行方式，SQLCheck 會把它當作估算證據。</span>
      </div>

      <textarea
        className="plan-textarea"
        aria-label="SQL Developer 執行計畫"
        value={value}
        maxLength={300000}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        placeholder={"可直接貼上 SQL Developer 的 Autotrace／Explain Plan 文字\n例如包含：Id、Operation、Name、E-Rows、A-Rows、Cost、Predicate…"}
      />

      <div className="plan-upload-row">
        <input
          ref={inputRef}
          type="file"
          hidden
          accept=".txt,.csv,text/plain,text/csv"
          onChange={(event) => void handleFiles(event.target.files)}
        />
        <button
          className="upload-btn"
          type="button"
          disabled={disabled || busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "讀取中…" : "↑ 上傳執行計畫 TXT / CSV"}
        </button>
        {value.trim() && (
          <button
            className="plan-clear-btn"
            type="button"
            disabled={disabled}
            onClick={() => {
              onChange("");
              setStatus(null);
            }}
          >
            清除執行計畫
          </button>
        )}
      </div>
      <div className="upload-help">
        SQLCheck 不會連線 Oracle；原始 Plan 不寫入 SQL Archive，也不送往雲端 AI。
      </div>
      {status && <div className={`upload-status upload-status-${status.tone}`}>{status.text}</div>}
    </div>
  );
}
