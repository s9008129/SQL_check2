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
        <span>SQL Developer F10 執行計畫（選填）</span>
        <span className="plan-optional">F10 Explain Plan</span>
      </div>

      <div className="plan-guidance">
        在 <strong>SQL Developer</strong> 按 F10 取得執行計畫後，可直接貼上或上傳。
        SQLCheck 會幫你整理 COST 較高的步驟與可注意的地方。
      </div>

      <textarea
        className="plan-textarea"
        aria-label="SQL Developer 執行計畫"
        value={value}
        maxLength={300000}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        placeholder={"可直接貼上 SQL Developer F10 執行計畫文字\n也可以上傳 TXT／CSV 檔案"}
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
        SQLCheck 不會主動連線 Oracle；貼上的執行計畫不會保存，也不會送給雲端 AI。
      </div>
      {status && <div className={`upload-status upload-status-${status.tone}`}>{status.text}</div>}
    </div>
  );
}
