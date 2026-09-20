# SQLCheck AI

SQLCheck AI 是地方稅自撰 SQL 的事前檢核與改善輔助工具。

它的目的不是取代 DBA，也不會連線或操作正式 Oracle 資料庫；系統會先依既有規則檢查 SQL，再由 AI 用較容易理解的方式整理改善方向，協助同仁在正式執行前先發現明確的規範問題與值得留意的寫法。

## 專案目標

SQLCheck AI 主要協助同仁：

- 檢查 COST、WHERE、Parallel Hint 等既有規範。
- 找出 LIKE、條件欄位函數、OR、重要資料表等需要留意的寫法。
- 以「改善指數」呈現值得優先檢視的程度。
- 在系統能證明安全時提供改寫對照；無法證明時只提供方向，不猜測業務條件。
- 使用 AI 產生白話說明，但合規判定與可否採用改寫仍由系統規則決定。
- 在送往雲端 AI 前先進行必要的去識別化與資料最小化。

## 簡易安裝與啟動

開發環境需要 Python 3.12、Node.js 22+ 與 `uv`。

Mac 開發可使用 Ollama Cloud：

```bash
git clone <repo-url>
cd SQL_check2
cp .env.mac.example .env
# 在 .env 填入 OLLAMA_API_KEY
bash scripts/dev-mac.sh
```

啟動後可開啟：

- 網頁：`http://127.0.0.1:5173`
- API：`http://127.0.0.1:8000`

正式環境採 Windows 11 + Docker Desktop + Windows 原生 Ollama。部署方式請參考 `deploy/README-deploy.md`。

## 簡易架構

```text
使用者
  ↓
SQLCheck AI 網頁
  ↓
FastAPI 後端
  ├─ SQL / 附件解析
  ├─ 規則引擎
  ├─ 改善指數
  ├─ 確定性改寫驗證
  └─ 去識別化後的 AI 請求
          ↓
      Gemma 4 31B
```

正式環境中，SQLCheck 不連 Oracle、不執行 SQL，也不取得 Execution Plan、Index 或正式資料內容。

## 文件

目前有效文件與歷史文件的狀態，統一整理在：

- `docs/document-status.md`

較完整但仍以非技術方式撰寫的系統說明：

- `SQLCheck2_系統架構與設計簡易說明.md`
