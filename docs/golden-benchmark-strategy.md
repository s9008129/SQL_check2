> **文件狀態：CURRENT**  
> 本策略仍是 Golden Benchmark 的現行治理原則。改善指數的既有權重與分級已於 2026-09-20 定案；真實模型驗證可使用 GitHub Actions 的 `Manual Live Cloud E2E`。

# SQLCheck Golden Benchmark Strategy — 無資深 DBA 情境

> 目的：建立可重跑、可解釋、可逐步擴充的 SQLCheck 評估基準，不要求先蒐集 30～50 支
> 「由資深 DBA 判定好壞」的真實 SQL，也不把 LLM 自己產生的主觀效能判斷冒充 Ground Truth。

## 1. 名稱與邊界

本專案使用 **Golden Benchmark Set / Golden Test Set**，不是建立一個新的業務資料庫。

SQLCheck 不連 Oracle，不看實際 Execution Plan、Index Metadata、Statistics、Cardinality 或 Runtime。
因此 Golden 標籤只涵蓋系統真正能驗證的項目：

- 中心規範的 deterministic 結果（PASS / REVIEW / BLOCK / NOTICE）。
- Parser 可觀察的 SQL 結構事實。
- Rewrite rule 能否證明「查詢結果不變」。
- AI 是否遵守輸出邊界（不捏造執行計畫、索引、改善後 COST 等）。
- UI / outcome 是否把 not_needed、advice_only、gated、rejected、provided 正確分開。

下列項目 **不能只靠 SQL 文字或另一個 AI 標成 Golden Truth**：

- 「這支 SQL 實際會快幾 %」。
- 「一定走索引 / 一定 Full Table Scan」。
- 「這個寫法在正式資料量下一定比另一個快」。
- 改寫後實際 COST。

若未來有測試資料庫與 Execution Plan / Runtime evidence，再另外建立 runtime benchmark，不與本套混用。

## 2. 不需要 30～50 支真實 SQL 才能開始

建議以「覆蓋能力」而不是「真實 SQL 數量」為目標。第一版可由四層案例組成。

### A. 規範錨點（Normative Anchors）

來源：正式中心規範 + `rules.yaml`。

例如：

- COST 99,999 / 100,000 邊界。
- 有 WHERE / 無 WHERE。
- JOIN-only restriction → REVIEW。
- Parallel Hint → BLOCK。
- NOTICE 不得翻成 BLOCK。

這一層的 expected result 由 deterministic 規則決定，不需要 DBA。

### B. 改寫正確性錨點（Rewrite-Proof Anchors）

來源：`rewrite_rules.py` + `pattern_catalog.yaml`。

至少包含：

- 已證明 safe rewrite 的正例。
- 只差一個前提就不安全的反例。
- NULL、OUTER JOIN、DISTINCT、datatype、collation 等語意陷阱。
- Oracle 邊界（例如 OR→IN 的 1000 expressions 上限）。

這一層的 Golden Truth 是「系統能否證明查詢結果不變」，不是「一定比較快」。

### C. 真實代表案例（Representative Real Cases）

使用者日後只需逐步提供少量已去識別化 SQL，不要求 DBA 先評分。

加入流程：

1. 去識別化。
2. Parser / Rule Engine 先產生客觀結構標籤。
3. 依 Pattern Catalog 自動分類 pattern coverage。
4. AI（Gemma 或高階模型）只能提出「候選說明 / 候選改善方向」。
5. Golden expectation 只收錄可由規則、AST 或 rewrite proof 確認的部分。
6. 無法確認的改法標成 `advice_only / review`，而不是硬給對錯。

如此即使沒有資深 DBA，真實 SQL 仍可用來增加「語法多樣性」與「實務代表性」。

### D. 合成壓力案例（Synthetic / Adversarial Cases）

可由高階模型依 Pattern Catalog 與既有真實 SQL 的**結構特徵**生成：

- 同一缺陷的不同寫法。
- 大小寫、換行、巢狀 CTE、JOIN 順序等變形。
- 近似但語意不同的陷阱案例。
- 長 SQL / 多段 SQL / masking / parser 邊界。

合成案例適合做 robustness test，但不可把「模型自己生成 + 模型自己判斷」當成效能真值。
每一支合成 SQL 必須有 deterministic expected facts，才能進 Golden Set。

## 3. 沒有 DBA 時，改善指數怎麼校準

不要把「改善指數」校準成真正的 Oracle 效能分數。它的產品定義維持：

> 值得優先檢視的程度。

因此校準目標改成 **contract calibration**，確認以下單調性與業務語意：

- 明確 BLOCK 的案件不得落在「目前良好」。
- 純治理型 NOTICE 不應單獨推高「改善潛力」。
- 新增一個更嚴重 deterministic finding，不應讓指數反而下降。
- Clean SQL 不應為了湊分數被推到「優先改善」。
- 同一 SQL + COST + rules config，不受 Gemma 回覆差異影響。
- score band 的文案與使用者實際處理順序一致。

這種校準不需要資深 DBA；它驗證的是 SQLCheck 自己宣稱的「檢視優先度」是否一致、可解釋。

若未來有 DBA 或測試資料庫，再新增第二層 validation：
「檢視優先度是否與真實效能改善價值相關」，不可回頭把目前指數說成已經具備這種證據。

## 4. AI 可以扮演什麼角色

高階模型可以協助：

- 從使用者提供的 SQL 中挑出「能增加 coverage」的代表案例。
- 找出重複案例並建議只保留其中一支。
- 依已知 pattern 生成正例、反例、邊界例。
- 撰寫每個 case 的 rationale。
- 檢查測試資料是否不小心把錯誤契約寫成正確答案。
- 對 Gemma Context ON/OFF 做盲測比較。

高階模型不應單獨決定：

- 真實 Oracle runtime 高低。
- 索引是否使用。
- Full Table Scan 是否發生。
- 改善後 COST / 百分比。
- 需要未知 datatype / business semantics 才能成立的等價性。

## 5. 建議的第一版規模

不追求「30～50 支真實 SQL」。第一版建議：

- 10～15 個規範 / parser deterministic anchors。
- 10～15 個 rewrite semantic anchors（正例 + 反例 + 邊界）。
- 5～10 個去識別化真實代表案例（有多少先用多少）。
- 必要時由模型生成變體補 coverage。

總量約 25～40 cases 即可，但其中真正的 production SQL 可以只有 5～10 支。

重點是每一類系統能力都有可重跑證據，而不是把數量本身當 KPI。

## 6. 使用者後續提供 SQL 時的標準流程

每批 SQL 交給本專案後：

1. 先去識別化與 structural fingerprint。
2. 與既有 Golden Set 去重。
3. 判定補到了哪一個規則 / pattern / parser / gate coverage。
4. 只挑有新增 coverage 的案例入選。
5. 必要時由高階模型生成 1～3 個反例或邊界變體。
6. deterministic expectations 進 unit/golden tests。
7. AI expectations 僅保留少量產品契約（例如 clean SQL 可 `not_needed`、不得 forbidden claim）。
8. 正式 Gemma 用 `run_golden.py` 做 Context ON/OFF A/B。

這樣 Golden Set 會隨實務使用自然成長，而不是在專案初期硬湊 50 支 SQL。


## 7. 現行 Live Cloud 驗證入口

永久 workflow：`.github/workflows/live-cloud-e2e.yml`。

- `smoke`：跑 live golden cases，適合 prompt / model-path 一般調整。
- `full`：跑較完整的 model/API suite，適合 masking、AI guard、rewrite governance、confidence 或 provider 行為重大變更後封板。
- workflow 只接受 synthetic / 去識別化 SQL，不應放 production 原始 SQL。
- Browser DOM / Native Print Preview 不屬於這個 Cloud model/API workflow 的證據範圍。

改善指數的目的仍是「值得優先檢視的程度」；2026-09-20 owner 已確認沿用現有權重、分級與演算法，不再列為 provisional calibration 待辦。
