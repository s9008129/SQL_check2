# SQLCheck 效能改善建議助手 DBA 稽核報告：MAC-G4-01 ~ 05

> 角色：Oracle DBA + `sqlcheck-oracle-review` 治理稽核
> 範圍：`/Users/hsiaojohnny/Downloads/MAC-G4-01.pdf` ~ `MAC-G4-05.pdf` 共 5 份實測 PDF
> 基準：`skills/sqlcheck-oracle-review/SKILL.md` 及其 `references/` 全套，`backend/app/knowledge/pattern_catalog.yaml`，`backend/app/prompts/sql_review_zh_tw.txt`，`backend/app/config/app.yaml`，`backend/app/config/rules.yaml`
> 方法：PDF 全文萃取後逐字比對禁語、分類、改寫呈現、計數一致性；不臆測原 SQL，只審查報告上寫出來的字

## 總結論

- 未發現 Class D 違規：5 份都沒有宣稱索引有無、全表掃描、執行計畫、改善後 COST、已測試實測快幾%。禁語掃描 5 份全過。
- 未發現把 ADVICE_ONLY 假裝成已驗證：TRUNC、NVL、TO_CHAR、DISTINCT、JOIN 位置全部標成有改善方向但請先確認再調整，並附請勿直接套用，符合 2026-09-18 Runtime Correctness 方向。
- 合規與優化分家有守住：R004 LIKE、R005 函數、R006 OR、R007 重要資料表都是 notice，不影響總判定。G4-03 有 LIKE+OR 提醒但總判定仍是符合，G4-04 只有 COST 超標才判不符合，這點是對的。
- 真正的問題是 2 個高風險呈現加 3 處計數文案自相矛盾，細節如下。

## 逐案檢核

### G4-01：符合，WIIT001，25 分

- 事實：智慧建議只有 1 項重要資料表範圍確認，Page2 寫目前未發現需要調整的寫法。
- 問題 M1：頭尾矛盾。Page1 先看結論寫另有 1 項寫法可再檢視，但 Page2 又說未發現需要調整的寫法，建議採用狀態卻又寫有改善方向但請先確認。同一份報告三種說法。
- 問題 M2：把 INFORMATIONAL 當寫法項。`IMPORTANT_TABLE_USAGE` 在 catalog 明寫只是治理提醒，不是效能缺陷證據，刻意與 R004 R005 R006 寫法類分開統計。把它計入寫法可再檢視會誤導。
- 證據：G4-01 Page1 先看結論，Page2 對照查看，`pattern_catalog.yaml` 的 `IMPORTANT_TABLE_USAGE` rationale，`methodology.md` Present 步驟。

### G4-02：符合，HOUT120 TRUNC，55 分

- 事實：建議把 `TRUNC(A.TXN_DATE)` 改日期範圍，並寫需確認 TXN_DATE 資料型態與文字值格式，測試環境驗證。Page2 明寫若不確認直接改寫可能改變結果，故僅提供方向。
- 判定：合規。這正是 `TRUNC_EQ_TO_RANGE` ADVICE_ONLY 的標準處理，runtime 在 2026-09-18 已停止自動推導，PDF 沒有給可貼上的具體 SQL，只有抽象方向，加上有免責聲明，是 5 份裡寫得最好的。
- 證據：G4-02 Page1 觀念提醒，Page2 規則檢核，`advice-only-patterns.md` 的 `TRUNC_EQ_TO_RANGE` 語意陷阱，有時間成分的綁定值會從匹配 0 筆變成 24 小時。

### G4-03：符合，LIKE 前置萬用字元加 OR，50 分

- 事實：原寫法 `A.OWNER_NAME LIKE '%明'`，示意方向給 `A.OWNER_NAME LIKE '明%'`，並附系統無法確認會保留相同結果，請勿直接套用。
- 問題 H1 高風險：`%明` 是以明結尾，`明%` 是以明開頭，是兩個不相交的結果集，根本不是等價改寫。catalog `LEADING_WILDCARD_LIKE` 明寫沒有可保證等價的自動改寫，改成 `xxx%` 是改變查詢條件。就算有警告，concrete 可複製貼上的 SQL 放在逐段對照裡，使用者略過警告直接貼就會出錯。
- 問題 M3：計數對不上。Page1 說另有 1 項寫法，中心規範寫 2 項提醒，Page3 確實列出 LIKE 1 處加 OR 1 處，但 AI 只給 1 項 LIKE，OR 被吞掉。是少報還是頭錯，無法從 PDF 自證。
- 證據：G4-03 Page1 評估 LIKE 比對方式，Page2 逐段對照，`pattern_catalog.yaml` 的 `LEADING_WILDCARD_LIKE`，`advice-only-patterns.md` 同項。

### G4-04：不符合，COST 125000，85 分，TO_CHAR 加 NVL

- 事實：COST 超過 100000 門檻判不符合，正確。另 2 項建議是日期比對改範圍例如大於等於 2026-01-01 且小於 2027-01-01，NVL 改 `A.CANCEL_FLAG = 'N' OR A.CANCEL_FLAG IS NULL`，兩處都有附需確認資料型態，CHAR NCHAR 會不一致。
- 問題 H2 高風險：prompt 明定 TRUNC NVL 這類只能在 explanation 白話說明方向，example 留空，不要產生可直接貼上的日期範圍或 NVL 展開式。PDF 卻在觀念提醒內文直接寫出具體年份區間和具體 OR 展開式，等於繞過 example 留空的守門。NVL 的 CHAR 空白補齊陷阱雖然有警告，但具體 SQL 已經給出去，CHAR 欄位貼上就錯。
- 問題 M4：日期年份疑似自創。prompt 規定沿用佔位符，不要自編新字串數字。原 SQL 經遮罩，模型看不到真值，2026-01-01 極可能是示意捏造，應留空抽象描述就好。
- 判定其餘合規：有警告 CHAR NCHAR，有寫缺乏業務資訊直接改寫會改變結果，有不代表效能提升，方向正確。
- 證據：G4-04 Page1 兩則觀念提醒，Page2 規則檢核，`advice-only-patterns.md` 的 `NVL_EQ_TO_OR_IS_NULL` CHAR 說明，`sql_review_zh_tw.txt` 改寫範例 b，`rewrite_rules.py` 註解 TRUNC NVL 已移除。

### G4-05：請人工確認，LEFT JOIN ON 加 DISTINCT，40 分

- 事實：LEFT JOIN 的 `B.OWNER_TYPE = '1'` 寫在 ON，主查詢無 WHERE，提醒主表 LND_CASE 全列都會列出。DISTINCT 提醒需確認 JOIN 後是否已唯一。這兩段 DBA 觀念本身是對的，符合 `DISTINCT_REMOVAL` 需唯一性證明和 JOIN 條件位置的語意風險。
- 問題 M5：同一份自打臉。Page1 中心規範寫目前無提醒事項，Page3 中心規則比對卻寫 7 符合 1 提醒，WHERE 列為問號。先看結論說有 1 項需人工確認，AI 卻給 2 項。使用者無法判斷到底有無提醒。
- 判定其餘合規：沒有叫你把 LEFT 改 INNER，沒有自動補 WHERE，沒有叫你直接拿掉 DISTINCT，全部維持 advice_only，是對的。若直接改 JOIN 種類會丟主表列，正是 `LEFT_JOIN_TO_INNER_JOIN` 禁止自動改的原因。
- 證據：G4-05 Page1 兩則觀念提醒，Page2 建議採用狀態，Page3 WHERE 問號，`rules.yaml` R002 `accept_join_on: false` 與 `join_on_outer_constant: review`，`advice-only-patterns.md` 的 `LEFT_JOIN_TO_INNER_JOIN` 與 `DISTINCT_REMOVAL`。

## 共通檢查

- 禁語掃描：Full Table Scan、全表掃描、索引失效、已使用索引、未使用索引、改善後 COST、執行計畫顯示、已驗證、已測試、實測、高風險、嚴重問題、錯誤寫法、無法利用索引 5 份全無命中。保守句通常能讓資料庫有更多機會採用較有效率的查詢方式是 prompt 允許的教育性說法，且每份都有不代表實際效能提升，測試機確認兜底，合規。
- 改善優先指數：G4-04 BLOCK 給 85 優先改善符合 `rules.yaml` block_floor 80，其餘 25 55 50 40 皆為目前良好，與 COST 接近門檻分一致。無證據 AI impact 回灌分數，但 PDF 指數組成收合看不到 F S C 明細，無法重現驗證。
- 呈現區分：5 份都有未經系統確認的示意方向請勿直接套用，符合 Present 步驟。但 G4-01 G4-05 的採用狀態文案與對照內容打架，需修文案邏輯。

## 未來改善方向

- Prompt 補洞：把 example 留空擴大到 explanation 內文。LIKE 前置、NVL 展開、日期範圍一律只准抽象描述加需確認清單，不准在內文寫 concrete 可貼 SQL。G4-03 G4-04 就是從內文漏出去的。
- UI 計數修齊：INFORMATIONAL 不計入寫法項，AI 項數等於規則提醒項數，REVIEW 無提醒事項文案統一。先修 G4-01 G4-03 G4-05 的三處矛盾。
- 測試加碼：加 LIKE `%x` 轉 `x%` 必須 advice_only 且無 concrete SQL 的測資，加 NVL 內文 concrete 檢測，加 PDF 計數一致性 e2e 測試。參照 `tests/test_pattern_catalog.py` 與 `semantic_traps.yaml` 模式。
- 稽核可追溯：PDF 附原 SQL 去識別化雜湊與代表語句類型，否則下次仍無法驗證等價性，Learn 迴圈接不上 Golden Dataset。
