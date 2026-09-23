# SQL Developer 執行計畫匯入與效能證據

> CURRENT — 2026-09-23

SQLCheck 不會主動連線 Oracle，而是解析使用者從 SQL Developer 貼上／匯出的 Plan。專案 owner 已確認日常作業是在**正式 Oracle 資料庫**執行 **F10 Explain Plan**，因此 F10 證據應視為「正式資料庫環境下的 Optimizer 估算」，而不是測試機資料。F10 仍未實際執行 SQL，所以不能把預估 COST／Rows 當成真實耗時、I/O 或實際列數。

## 建議取得方式

本專案的正式作業流程以 Oracle SQL Developer 為主，且 owner 已確認 **F10 Explain Plan 是在正式資料庫連線上執行**。

### 1. 標準流程：正式資料庫 Explain Plan（F10）

在 SQL Developer 對正式資料庫連線，使用 **F10 Explain Plan** 取得 Optimizer 的預估執行計畫，再將 Plan 文字／CSV 貼入 SQLCheck。

Oracle 11g 官方說明，`EXPLAIN PLAN` 會讓 Optimizer 為指定 SQL 決定一份執行計畫，並將各步驟寫入 PLAN_TABLE；它也會估算 COST。這讓 F10 比「只看 SQL 文字」多了一層與正式資料庫環境相關的證據，例如當下 Optimizer 看見的物件、統計資訊與可選 access path 所形成的估算結果。

但必須維持一條清楚邊界：**F10 是 estimated plan，不是 actual runtime plan。**它不能證明 SQL 已實際執行，也不能直接代表真實執行時間、Buffers、Reads、A-Rows 或最終 cursor plan。

SQLCheck 因此會標示：

> 正式資料庫 F10 Explain Plan（估算）

並允許用它確認「正式庫 Optimizer 當下預估會走哪種 Operation／Options」；若要宣稱「實際變快」，仍需要另有經核准的 runtime evidence。

### 2. Autotrace（F6）／實際執行證據：不是 SQLCheck 的預設要求

SQL Developer **F6 Autotrace** 會涉及實際執行與 runtime statistics。因本專案標準流程已確認是在正式資料庫做 F10，SQLCheck **不會要求同仁為了取得建議而在正式庫額外執行 F6**。

若既有作業規範另有授權，而且使用者本來就有合法取得的 actual plan／runtime statistics，SQLCheck 仍能解析 A-Rows、Starts、Buffers、Reads、A-Time 等欄位；但系統不會僅憑文字自行猜測該 runtime evidence 是從正式庫或測試庫取得，來源應以作業紀錄為準。

### 3. 進階：DBMS_XPLAN.DISPLAY_CURSOR

若既有 DBA／作業流程已合法取得 cursor plan statistics，可使用 DBMS_XPLAN 顯示 cursor 計畫，例如：

```sql
SELECT *
FROM TABLE(
  DBMS_XPLAN.DISPLAY_CURSOR(NULL, NULL, 'ALLSTATS LAST +PREDICATE +COST')
);
```

`ALLSTATS LAST` 需要有對應 plan statistics；`DISPLAY_CURSOR` 也需要查詢相關 `V$SQL*` fixed views 的權限。因此 SQLCheck 不要求使用者自行增加權限、修改 SQL 加 hint 或在正式庫額外執行查詢。

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
- 若 F10 Plan 顯示 TABLE ACCESS FULL，系統可以陳述「正式庫 Optimizer 的估算 Plan 含此 access path」，但不直接判成錯誤，也不自動要求建立 Index。
- 標準 F10 只有 estimated rows，不會因此產生「估計列數 vs 實際列數」判斷。只有使用者另行提供含 E-Rows / A-Rows / Starts 的合法 runtime evidence 時，系統才會計算落差作為後續確認線索；這仍不是「統計資訊錯誤」的判定。
- 若 SQL 已符合 deterministic VERIFIED_REWRITE，且 Plan Predicate 也看到對應條件，系統會把它列為優先在正式資料庫依既有流程做 Before／After F10 Explain Plan 比較的候選。
- 執行計畫目前**不改變中心規範判定與「改善指數」**。

## 資料安全

- 執行計畫原文不寫入 `data/sql_archive/`。
- 執行計畫原文不送往 Ollama Cloud / Gemma。
- SQLCheck 只在目前這次 API request 中解析，前端取得的是結構化結果。
- 使用者仍應遵守既有測試資料與敏感資訊管理規範。

## Oracle 官方依據

- Oracle SQL Developer：F10 顯示 Explain Plan；F6 顯示 Autotrace。
- Oracle Database 11g SQL Language Reference：EXPLAIN PLAN 讓 Optimizer 決定指定 SQL 的執行計畫並寫入 PLAN_TABLE，也會估算 COST。
- Oracle SQL Tuning Guide：EXPLAIN PLAN 顯示的是 explain 當下的估算；實際執行環境不同時，actual plan 可能不同。
- DBMS_XPLAN：`DISPLAY_CURSOR` 可顯示 cursor 計畫；`ALLSTATS LAST` 在有收集 plan statistics 時可顯示最後一次執行統計。
