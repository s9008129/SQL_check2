> **文件狀態：REFERENCE / 人工驗證案例集**  
> 這 5 案仍可用來人工觀察 UI 與模型語意，但不再是主要 Live 驗收流程。  
> **目前真實模型驗證優先使用 GitHub Actions 的 `Manual Live Cloud E2E`（smoke / full）；本文件保留作人工補充案例。**

# Mac / Ollama Cloud：Gemma 4 31B 五情境驗證

目的：在沒有正式案件 SQL 的 Mac 上，用 **synthetic SQL** 驗證與正式機相同的 Gemma 4 31B
模型路徑。這五案是依 2026-09-16～17 的 E2E 紀錄抽象化重建，**不是原始案件 SQL 的還原**；
只保留當時真正遇過的結構與風險類型：GROUP BY、LEFT JOIN、DISTINCT、TRUNC、TO_CHAR、NVL、
前置萬用字元、OR、JOIN-only R002 等。

請逐案貼到網頁，申請單號與 COST 也照表輸入。模型輸出不是 deterministic，
所以驗收重點是「安全邊界與方向」，不是要求每個中文字完全一致。

## Case 1 — 乾淨 GROUP BY + 後置 LIKE：不應硬湊改善

- 申請單號：`MAC-G4-01`
- COST：`38000`
- 來源脈絡：歷史「地價稅／房屋稅」GROUP BY 案，以及 `LIKE '114%'` 曾被誤當改善點的紀錄。

```sql
SELECT
    W.TAX_CD,
    W.SUBTAX_CD,
    COUNT(*) AS CNT
FROM WIIT001 W
WHERE W.COLL_YR LIKE '114%'
  AND W.STATUS_CD = '1'
GROUP BY W.TAX_CD, W.SUBTAX_CD;
```

**應觀察：**
- 中心規範不應因 GROUP BY 本身被判 BLOCK。
- `LIKE '114%'` 是後置萬用字元，不應被 R004 當「前置萬用字元」。
- WIIT001 可出現重要資料表提醒，但 AI 不應為了看起來有用而硬改 SQL。
- 合理結果是 `not_needed`，或只有真正有依據的觀念提醒。

## Case 2 — TRUNC 日期條件：型態不能在遮罩後消失

- 申請單號：`MAC-G4-02`
- COST：`48000`
- 來源脈絡：歷史 S1 / 真實模型 TRUNC 測試，以及 PR #10 DATE/TIMESTAMP type-preserving masking。

```sql
SELECT
    A.CASE_NO,
    A.TXN_DATE
FROM HOUT120 A
WHERE TRUNC(A.TXN_DATE) = DATE '2026-09-01';
```

**應觀察：**
- R005 應提醒「條件欄位套用函數」。
- HOUT120 符合目前 HOU* 重要表 pattern，可另有治理提醒。
- 雲端送模前日期實值會遮罩，但 `DATE` 型態提示應保留。
- AI 不得聲稱「已確認使用索引／沒有 Full Table Scan／Execution Plan 會改善」。
- 若提供日期範圍改法，最新版安全策略應清楚標示其可採用程度；不能把未證明的型態／時間語意包裝成已驗證事實。

## Case 3 — 前置萬用字元 + 跨欄 OR：應偏向人工確認

- 申請單號：`MAC-G4-03`
- COST：`62000`
- 來源脈絡：歷史 S2、F4、F6。

```sql
SELECT
    A.CASE_NO,
    A.OWNER_NAME,
    A.DISTRICT_CD
FROM LND_CASE A
WHERE A.OWNER_NAME LIKE '%明'
   OR A.DISTRICT_CD = '07';
```

**應觀察：**
- 應命中 R004（前置萬用字元）與 R006（OR）。
- 因 OR 跨不同欄位，系統不應把它當成可安全證明的 same-column OR → IN。
- AI 可以說明方向，但不應自行把它改成 UNION ALL 並宣稱等價。
- 不得新增原 SQL 沒有的欄位、JOIN key 或業務條件。

## Case 4 — TO_CHAR + NVL + COST 超標：規則與 AI 職責要分開

- 申請單號：`MAC-G4-04`
- COST：`125000`
- 來源脈絡：歷史 S3、F8、F10，加上中心 COST 門檻驗證。

```sql
SELECT
    A.CASE_NO,
    A.APPR_DATE,
    A.CANCEL_FLAG
FROM TAX_CASE A
WHERE TO_CHAR(A.APPR_DATE, 'YYYY') = '2026'
  AND NVL(A.CANCEL_FLAG, 'N') = 'N';
```

**應觀察：**
- COST > 100000 應由 deterministic 規則直接處理，不是讓 AI 決定。
- TO_CHAR / NVL 應產生 R005 類提醒。
- AI 不知道資料欄位真正 datatype、索引、統計量，不得自行宣稱「一定可以用 index」。
- 若正確改寫需要知道日期欄位型態或 NULL 的業務意義，應要求確認，而不是猜一支看似合理的完整 SQL。

## Case 5 — LEFT JOIN + DISTINCT、主查詢沒有 WHERE：R002 應 REVIEW

- 申請單號：`MAC-G4-05`
- COST：`42000`
- 來源脈絡：三份 LND Word 真實案例的 outer join / distinct 結構，以及 2026-09-19 R002 語意校正。

```sql
SELECT DISTINCT
    A.CASE_ID,
    A.LAND_NO,
    B.OWNER_TYPE
FROM LND_CASE A
LEFT JOIN LND_OWNER B
       ON B.CASE_ID = A.CASE_ID
      AND B.OWNER_TYPE = '1';
```

**應觀察：**
- 主查詢沒有 WHERE；只有 LEFT JOIN 的 ON 條件。
- R002 應是 **REVIEW／需人工確認**，不能因為 ON 有常數就直接說「符合中心 WHERE 要求」。
- AI 不得為了補 WHERE 而編造欄位或業務條件。
- DISTINCT / LEFT JOIN 本身不應被一刀切禁止，但完整改寫若改變結構應被 safety gate 擋下或降為人工確認。

## 五案共同驗收底線

1. API / 畫面可正常取得 AI 結果，不因 provider 切換而 500。
2. AI 不決定 compliance，也不改寫 deterministic 規則結果。
3. 不出現模型杜撰的欄位、資料表、JOIN key、業務常數。
4. 不宣稱 SQLCheck 看不到的 Execution Plan、Index 使用情形、Full Table Scan、實際 runtime 或改善後 COST。
5. `data/sql_archive/` 若啟用，應只寫去識別化後的 SQL；本文件五案皆為 synthetic，可安全用於 Mac parity 測試。
