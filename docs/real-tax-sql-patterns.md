# 地方稅實務 SQL Pattern — SQLCheck v1

> **文件狀態：CURRENT**
>
> 本文件記錄 SQLCheck 從專案 owner 提供的地價稅／使用牌照稅 SQL 收集包中整理出的
> **去識別化結構模式**。原始 SQL、檔名內容、實際人員／案件資料與畫面不進 Git；
> repository 只保留 synthetic / de-identified regression cases。

## 目的

這一版不是讓 AI「更敢猜」，而是增加 SQLCheck 可以先用 AST 確認的結構事實。
Pattern detector 只回答「SQL 裡確實存在什麼形狀」，不回答「一定比較慢」；
真正可以標成「可使用此改寫」的內容，仍只有 rewrite_rules.py 能證明結果不變的規則。

### 權限順序

正式中心規範 → Rule Engine → rewrite_rules.py → Pattern Catalog → Gemma。

本文件新增的 pattern 全部屬 SQL 效能改善知識，不是中心規範，不得升級成 BLOCK。

## 已確認的高頻結構

### latest-row-correlated-max

代表形狀：

```sql
SELECT A.ID
FROM TAX_CASE A
JOIN TAX_HISTORY B ON B.ID = A.ID
WHERE B.UPDATE_DATE = (
  SELECT MAX(H.UPDATE_DATE)
  FROM TAX_HISTORY H
  WHERE H.ID = A.ID
)
AND B.UPDATE_TIME = (
  SELECT MAX(H2.UPDATE_TIME)
  FROM TAX_HISTORY H2
  WHERE H2.ID = A.ID
);
```

這種寫法在使用牌照稅跨年度查詢中反覆出現。系統可以確定「同一來源重複出現相關
MAX scalar subquery」，因此可精準提醒評估先集中取得最新紀錄。

**不能直接改成 ROW_NUMBER()=1**：若同一 ID 在相同日期與時間存在多筆，原 SQL
可能回傳多筆；ROW_NUMBER()=1 只保留一筆，結果會改變。

### repeated-scalar-aggregate

代表形狀：

```sql
SELECT A.ID,
       (SELECT COUNT(*) FROM TAX_DETAIL D WHERE D.ID = A.ID AND D.KIND='A') AS CNT_A,
       (SELECT COUNT(*) FROM TAX_DETAIL D WHERE D.ID = A.ID AND D.KIND='B') AS CNT_B
FROM TAX_CASE A
WHERE A.STATUS='1';
```

系統可確認同一來源被多次 scalar aggregate 查詢，可提醒評估先彙總一次再重用。
但不同 filter、NULL、group semantics 與 correlation 都可能使直接合併不等價，因此先維持
ADVICE_ONLY。

### composite-key-expression-join

代表形狀：

```sql
SELECT A.ID
FROM TAX_A A
JOIN TAX_B B
  ON SUBSTR(A.MANAGE_KEY, 1, 2) = B.DISTRICT_CD
 AND SUBSTR(A.MANAGE_KEY, 3, 4) = B.SECTION_CD
WHERE A.STATUS='1';
```

或：

```sql
ON A.MANAGE_KEY = B.DISTRICT_CD || B.SECTION_CD || B.SERIAL_NO
```

這類複合代碼／欄位加工勾稽在地價稅 SQL 很常見。SQLCheck 可以確定至少一側先做
函數、串接或運算再與另一資料表欄位比較，因此能指出改善位置。

但沒有欄位 metadata 時，系統不知道固定寬度、CHAR/VARCHAR2 補空白、NULL 行為或真正
business key，不能自己拆欄或重組 JOIN。

### repeated-source-union-branch

代表形狀：

```sql
SELECT AREA_CD, COUNT(*) FROM TAX_CASE
WHERE TAX_CD='A' AND AMOUNT <= 100
GROUP BY AREA_CD
UNION ALL
SELECT AREA_CD, COUNT(*) FROM TAX_CASE
WHERE TAX_CD='A' AND AMOUNT > 100
GROUP BY AREA_CD;
```

系統可以確認多個 set-operation branch 使用相同來源資料表組合，因此可提醒評估 CASE /
條件彙總等單次來源查詢。

**不能訂成「UNION ALL 都不好」**。UNION ALL 本身可能正是正確的業務集合語意；只有
來源重複這個結構事實被確認。

### cross-column-or

代表形狀：

```sql
WHERE A.STATUS='1' OR A.CLOSE_DATE >= :D
```

R006 只能知道有 OR。新 detector 會進一步確認同一 OR chain 是否真的涉及不同欄位。
跨欄位 OR 拆成 UNION / UNION ALL 可能改變重複列與去重語意，因此仍是 ADVICE_ONLY。

### string-concat-predicate

代表形狀：

```sql
WHERE A.TAX_CD || A.SUBTAX_CD = :CODE
```

系統可以確認條件式有欄位串接，但不知道 :CODE 應該如何切割，也不知道欄位長度與
NULL／補空白規則，所以只能指出位置與缺少的證據。

## 仍可直接提供 Diff 的既有 VERIFIED_REWRITE

這次實務資料也再次確認現有兩種 deterministic rewrite 很有價值：

1. SUBSTR equality → canonical LIKE。
2. 同欄位 equality OR chain → IN（最多 1000 expressions）。

這兩種 Diff 由 rewrite_rules.py 產生，不需要等待 AI；Gemma 只負責白話說明。
即使語意已由程式確認，實際效能差異仍應在測試機以使用者提供的 SQL Developer plan
或 runtime evidence 驗證。

## Golden regression 原則

原始稅務 SQL 不進 repository。測試只使用：

- synthetic table / column names；
- 改寫後不含真實案件或納稅義務人資料；
- positive / negative / boundary / semantic-trap cases；
- 只測「是否命中 pattern」與「是否被錯誤升級成 VERIFIED_REWRITE」。

下一階段若要讓 NVL、複合代碼拆分等 pattern 升級成條件式 Diff，必須另建由 owner
確認的 column/domain metadata；不得從這批 SQL 的使用慣例反推欄位型態或 NULL 規則。
