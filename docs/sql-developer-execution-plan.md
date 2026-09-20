# SQL Developer 執行計畫匯入與效能證據

> CURRENT — 2026-09-20

SQLCheck 的執行計畫功能是為了讀取**測試機**證據，不會連線 Oracle，也不會把測試機結果說成正式機一定相同。

## 建議取得方式

本專案的日常工具是 Oracle SQL Developer，因此輸入流程以 SQL Developer 為主。

### 1. 首選：Autotrace（F6）

在測試機可以實際執行 SQL 時，優先使用 SQL Developer 的 **Autotrace（F6）**。Oracle 官方說明中，Autotrace 會執行 SQL，並收集 runtime statistics 與 actual execution plan。

將 Autotrace 的文字內容複製到 SQLCheck 的「SQL Developer 執行計畫」欄位；若工作環境可匯出文字，也可存成 TXT／CSV 後上傳。

### 2. 備用：Explain Plan（F10）

若不適合實際執行，可使用 **Explain Plan（F10）**。這是 Optimizer 的預估計畫，不等於 SQL 真正執行時一定採用相同計畫。SQLCheck 會明確標示為「測試機預估執行計畫」。

### 3. 進階：DBMS_XPLAN.DISPLAY_CURSOR

若測試帳號具備必要權限，而且已依環境規範收集 plan statistics，可在實際執行後使用 DBMS_XPLAN 顯示 cursor 計畫，例如：

```sql
SELECT *
FROM TABLE(
  DBMS_XPLAN.DISPLAY_CURSOR(NULL, NULL, 'ALLSTATS LAST +PREDICATE +COST')
);
```

Oracle 文件說明，`ALLSTATS LAST` 能顯示最後一次執行的 I/O／memory statistics，但需要有對應的 plan statistics；`DISPLAY_CURSOR` 也需要查詢相關 `V$SQL*` fixed views 的權限。因此 SQLCheck 不會要求使用者一定採用此方式，也不會自動修改 SQL 加 hint。

## SQLCheck 目前會讀什麼

目前 deterministic parser 會讀取常見 DBMS_XPLAN／SQL Developer 文字表格與 CSV／Tab 匯出，包括：

- Id、Operation、Name
- Rows／E-Rows、A-Rows、Starts
- Cost
- A-Time、Buffers、Reads
- Access Predicate、Filter Predicate
- Plan hash value、SQL_ID（若輸出中有）
- 常見 Autotrace aggregate statistics（例如 consistent gets、physical reads、rows processed）

## 系統如何使用這些資料

執行計畫是「證據層」，不是新的中心規範。

- 若 COST 欄位與計畫根節點 COST 不一致，系統只提醒確認是否拿錯 SQL／Plan。
- 若看到 TABLE ACCESS FULL，系統只陳述測試計畫事實，不直接判成錯誤，也不自動要求建立 Index。
- 若實際計畫同時有 E-Rows / A-Rows，系統可標示明顯的估計落差，作為後續確認 statistics／資料分布的線索。
- 若 SQL 已符合 deterministic VERIFIED_REWRITE，且 Plan Predicate 也看到對應條件，系統會把它列為優先在測試機做 Before／After 驗證的候選。
- 執行計畫目前**不改變中心規範判定與「改善指數」**。

## 資料安全

- 執行計畫原文不寫入 `data/sql_archive/`。
- 執行計畫原文不送往 Ollama Cloud / Gemma。
- SQLCheck 只在目前這次 API request 中解析，前端取得的是結構化結果。
- 使用者仍應遵守既有測試資料與敏感資訊管理規範。

## Oracle 官方依據

- SQL Developer / Worksheet：Explain Plan 產生預估計畫；Autotrace 執行 SQL 並收集 runtime statistics 與 actual plan。
- Oracle Database SQL Tuning Guide：EXPLAIN PLAN 可能與實際執行計畫不同。
- DBMS_XPLAN：`DISPLAY_CURSOR` 可顯示 cursor 計畫；`ALLSTATS LAST` 在有收集 plan statistics 時可顯示最後一次執行統計。
