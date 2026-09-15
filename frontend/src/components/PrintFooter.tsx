export interface PrintFooterProps {
  applicationNo: string;
  onScrollToInput: () => void;
}

/** 列印 / 存成 PDF 按鈕 + 建議以申請單號命名檔案的提示 (PRD §37)。 */
export default function PrintFooter({ applicationNo, onScrollToInput }: PrintFooterProps) {
  const trimmed = applicationNo.trim();
  return (
    <div className="footer-actions no-print">
      <div className="print-hint">
        列印或存成 PDF 時，建議以申請單號{trimmed ? `「${trimmed}」` : ""}命名檔案，方便日後查找。
      </div>
      <div className="footer-actions-buttons">
        <button type="button" onClick={onScrollToInput}>
          回到輸入區
        </button>
        <button type="button" className="dark" onClick={() => window.print()}>
          列印 / 存成 PDF
        </button>
      </div>
    </div>
  );
}
