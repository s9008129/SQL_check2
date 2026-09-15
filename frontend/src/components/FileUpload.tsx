import { useRef, useState } from "react";
import { ApiError, extractSql } from "../api/client";

export interface FileUploadProps {
  /** Fills the SQL editor via the caller's callback — never auto-submits (PRD §35). */
  onExtracted: (sql: string, message: string) => void;
  disabled?: boolean;
}

type StatusTone = "success" | "error" | "info";

export default function FileUpload({ onExtracted, disabled = false }: FileUploadProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [status, setStatus] = useState<{ text: string; tone: StatusTone } | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setBusy(true);
    setStatus(null);
    try {
      const res = await extractSql(file);
      if (res.sql.trim()) {
        onExtracted(res.sql, res.message);
        setStatus({ text: `✓ ${res.message}`, tone: "success" });
      } else {
        setStatus({ text: res.message, tone: "info" });
      }
    } catch (err) {
      const detail =
        err instanceof ApiError ? err.detail : "上傳失敗，請稍後再試一次，或直接貼上 SQL。";
      setStatus({ text: detail, tone: "error" });
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="upload-box">
      <input
        ref={inputRef}
        type="file"
        hidden
        accept=".docx,.pdf,.txt,.csv,.md,.markdown,.sql"
        onChange={(event) => void handleFiles(event.target.files)}
      />
      <button
        type="button"
        className="upload-btn"
        disabled={disabled || busy}
        onClick={() => inputRef.current?.click()}
      >
        {busy ? "辨識中…" : "↑ 上傳附件辨識 SQL"}
      </button>
      <div className="upload-help">支援 DOCX、文字型 PDF、TXT、CSV、Markdown、SQL</div>
      {status && <div className={`upload-status upload-status-${status.tone}`}>{status.text}</div>}
    </div>
  );
}
