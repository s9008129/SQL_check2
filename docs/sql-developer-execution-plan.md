# SQL Developer 執行計畫匯入與效能證據

> CURRENT — 2026-09-22

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

目前 deterministic parser（`backend/app/services/execution_plan.py`）支援三種輸入：DBMS_XPLAN／SQL Developer 的 `|…|` 文字表格、SQL Developer grid 複製的 Tab 分隔文字，以及 CSV 匯出。它只讀取文字裡真的出現的欄位：

| Plan 欄位（常見寫法） | SQLCheck 的處理 |
|---|---|
| `Id` | 步驟編號。沒有 Id／Operation 就無法辨識，直接回報「格式待確認」 |
| `Operation` | 存取動作，例如 `TABLE ACCESS`、`INDEX`、`HASH JOIN` |
| `OPTIONS` | 存取方式，例如 `FULL`、`RANGE SCAN` |
| `Name`／`OBJECT_NAME` | 物件名稱 |
| `Rows`／`CARDINALITY`／`E-Rows` | 估計列數 |
| `A-Rows`、`Starts` | 實際列數與執行次數（runtime evidence） |
| `Cost`（含 `Cost (%CPU)`） | 步驟成本；根節點 Cost 會與使用者輸入的 COST 對照 |
| `A-Time`、`Buffers`、`Reads` | 實際執行時間與 I/O |
| `ACCESS_PREDICATES`、`FILTER_PREDICATES` | 該步驟的存取／過濾條件欄位 |
| `Predicate Information (identified by operation id)` | DBMS_XPLAN 文字中的 predicate 區段；與上面的欄位合併後會去除完全重複的條件 |
| `Plan hash value`、`SQL_ID` | 文字輸出中有就顯示原值，沒有就留空，不會推算 |
| Autotrace aggregate statistics | `recursive calls`、`db block gets`、`consistent gets`、`physical reads`、`redo size`、`SQL*Net` 系列、`sorts (memory)`／`sorts (disk)`、`rows processed` |

### OPERATION 與 OPTIONS 會合併理解

SQL Developer 的 PLAN_TABLE 匯出常把同一個存取路徑拆成兩欄：

```text
OPERATION = TABLE ACCESS
OPTIONS   = FULL
```

SQLCheck 會 deterministic 合併成 `TABLE ACCESS FULL` 再判斷與顯示。`OPTIONS` 為空時只顯示 `Operation`，不會產生多餘空白或 `null`；前端步驟明細顯示的就是合併後的字串，與後端判斷共用同一個語意。

### 不認識的格式一律 fail closed

若內容沒有可辨識的 `Id`／`Operation` 欄位，SQLCheck 只回報「格式待確認」，不會猜測 plan 內容，也不會捏造任何欄位；SQL 規則檢核本身不受影響。第一版只支援上述文字／CSV／Tab 格式，**不做 PDF、截圖或 OCR**，也不加入沒有範例佐證的猜測式解析。

## 系統如何使用這些資料

執行計畫是「證據層」，不是新的中心規範。

- 若 COST 欄位與計畫根節點 COST 不一致，系統只提醒確認是否拿錯 SQL／Plan。
- 若看到 TABLE ACCESS FULL，系統只陳述測試計畫事實，不直接判成錯誤，也不自動要求建立 Index。
- 若實際計畫同時有 E-Rows / A-Rows，系統會以「A-Rows ÷ Starts 與 E-Rows 相差 10 倍以上」作為 review 訊號，標示估計落差，作為後續確認 statistics／資料分布的線索；這是待確認線索，不是「統計資訊錯誤」的判定。
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
