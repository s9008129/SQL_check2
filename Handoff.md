# SQLCheck 2.0 交接文件（Handoff）— 2026-09-17

> 給接手 Agent 的指示 prompt（請將下面這段直接貼給新對話的 Agent）：

```
你接手的是 SQLCheck 2.0（臺灣地方稅務機關內部工具，同仁貼上 Oracle SQL 與 COST，系統用
deterministic 規則引擎判定是否符合中心規範，再由本機 Ollama 上的 Gemma4-31B 給白話改善建議
與「建議寫法」）。專案在 D:\dev\SQL_check2，主分支 main 已與 origin 同步，最新 commit 815c056。
請先完整讀完 Handoff.md（本檔）、tasks/lessons.md、tasks/todo.md，再動手。

硬性規則：
1. 回覆與所有 commit 訊息使用台灣繁體中文；commit 訊息必須含「意圖／你做了什麼／下一步建議」
   三段，並由你自己執行 git add、commit、push。
2. 改任何程式前先跑 `cd backend && uv run pytest -q && uv run ruff check .` 與
   `cd frontend && npm test -- --run && npm run build`，改完再跑一次，全綠才可提交。
3. 不可讓 AI 決定「符合／不符合」；規則引擎（rule_engine.py）是唯一裁判。AI 的建議寫法必須
   通過 ai_service._revalidate_suggested_sql 的結構複核；不可為了讓 AI 更常給改寫而放寬
   複核或把「需要業務假設的改寫」放進 sql 欄位。
4. 不可把申請單號、原始 SQL 常數、附件檔名寫進任何永久儲存或 log。
5. 開發機（10.97.15.54）沒有 Docker 也沒有 Ollama。正式主機的 Ollama 11434 依 PRD §46
   與 2026-09-17 的防火牆 fail-closed 政策**刻意不讓區網（含開發機）直連**；要驗證 prompt
   改動請用「本機程式碼＋通道（tunnel／SSH port-forward）指向正式主機 Ollama」的方式
   （見本檔第 6 節），不要只用 fake_ollama，也不要把 11434 開放給區網。
6. 遇到「AI 沒給建議寫法」類的回報，先用 Handoff 第 4 節的判讀順序查 outcome 與 log，
   不要直接改 prompt。
7. 完成一個可驗證的段落就 commit，不要累積大量未提交變更。
```

---

## 1. 系統一句話與硬性邊界

- 使用者貼 SQL＋COST → 後端 `sql_parser`（sqlglot，Oracle 方言）擷取事實 → `rule_engine`
  依 `rules.yaml` 判 8 條規則（R001 COST、R002 WHERE、R003 Parallel Hint 為 BLOCK 類；
  R004 LIKE 前置萬用字元、R005 條件欄位套函數、R006 OR、R007 重要資料表為 NOTICE 類；
  R008 重要資料表禁止操作）→ `improvement_score` 算改善優先指數 → `ai_service` 呼叫 Ollama
  Gemma4 取得白話建議與建議寫法 → 前端 React 呈現，可列印 PDF。
- **AI 不裁判、不看資料庫、不編造 COST／執行計畫**；它只解釋、建議、在允許時給一份等價改寫。
- 單一 Docker 容器（正式主機 10.97.15.58，HTTPS 443 自簽憑證），Ollama 原生跑在 Windows。
- 詳細產品規格：`SQLCheck2_PRD_v6_AI_Estimated_Improvement.md`；與 PRD 不同的決定記錄在本檔第 3 節。

## 2. 目前程式結構（只列會需要動的）

| 路徑 | 職責 |
|---|---|
| `backend/app/services/sql_parser.py` | sqlglot 解析、事實擷取、`complexity_flags`、R002 的 `_restriction_evidence`、`structural_signature`（改寫結構指紋） |
| `backend/app/services/rule_engine.py` | 8 條規則判定；R002 依 `restriction_kind` 與 `rules.yaml` 的 `restriction_verdicts` 決定 PASS／REVIEW／BLOCK |
| `backend/app/services/ai_service.py` | 守門 `_compute_gates`（回 candidate_allowed / estimate_allowed / decline_code）、payload 組裝、Ollama 呼叫（`think:false`）、`_revalidate_suggested_sql` 結構複核、`outcome` 分類、INFO 決策 log |
| `backend/app/services/masking.py` | 送 AI 前遮罩：字串常數只有「≤4 字元且純 ASCII 英數／%／_」保留，其餘與 ≥6 位數字皆遮罩；`literal_hints`；`deidentify_sql`（蒐集檔用，更嚴） |
| `backend/app/services/sql_archive.py` | 去識別化 JSON Lines 蒐集檔，`data/sql_archive/sql_archive-YYYY-MM.jsonl`，只在 include_ai=true 時寫 |
| `backend/app/services/sql_detect.py` | 附件（docx/pdf/txt/csv/md）中辨識 SQL；連續空行不截斷 |
| `backend/app/prompts/sql_review_zh_tw.txt` | System prompt（全部改動歷史見第 3 節） |
| `backend/app/config/app.yaml` | Ollama 參數（`num_predict 3072`、`timeout 180`、`think_default false`）、`ai_gate`、`ai_guard`、`masking`、`archive` |
| `backend/app/config/rules.yaml` | 規則開關、R002 `restriction_verdicts`、改善指數權重 |
| `backend/app/schemas.py` | API 契約：`SuggestedSql.outcome`、`AdviceItem.before` 等 |
| `frontend/src/components/SummaryCards.tsx` | 4 張摘要卡（中心規範／COST／改善指數／智慧改善建議），含白話「指數組成」展開 |
| `frontend/src/components/SqlCompare.tsx` + `SqlDiffView.tsx` + `lib/sqlDiff.ts` | SQL 寫法比較：判定文字 → 完整改寫逐行對照 → 逐段對照（每項建議 before/example 逐字 diff） |
| `frontend/src/components/ImprovementAdvice.tsx` | 建議卡片，底色依 impact（高紅／中黃／低藍） |
| `frontend/src/lib/copy.ts` | 所有固定文案 |
| `frontend/src/styles/app.css` 末段 | 兩組覆寫：「預估／比較區放大 20%」與「whole-page visual pass」字級階層 |
| `deploy/deploy.ps1`、`docker-compose.yml`、`Dockerfile` | 一鍵部署；`./data:/data` 掛載；`PYTHONIOENCODING=utf-8` |
| `scripts/fake_ollama.py` | 開發機假 Ollama（normal／slow／bad-json／truncated／down） |
| `tasks/lessons.md` | 失敗模式與預防規則，**接手前必讀** |

## 3. 已定案的設計決定與理由（按時間）

### 2026-09-15（部署）
- HTTPS 443 自簽（ECDSA P-384）；改善優先指數＝規則分＋結構分＋COST 比例分＋AI 影響分（上限 10），BLOCK 下限 80。
- 正式主機模型標籤是 `gemma4:31b`（不是 -it-qat）。

### 2026-09-16 上午：「AI 一律不給建議寫法」根因
- **不是模型保守**：`app.yaml` 的 `candidate_forbidden_complexity_flags` 原本禁止 outer_join／group_by_aggregate／distinct，涵蓋幾乎所有真實查詢。已移除這三項，改由 `structural_signature`（JOIN 種類與順序、GROUP BY、DISTINCT、彙總函數、ORDER BY、欄位數）在改寫送回前比對。仍禁止：window_function、connect_by、set_operation、rownum、correlated_subquery。
- 附件擷取 bug：`sql_detect._trim_trailing_prose` 遇連續空行把 WHERE 整段切掉 → 造成假 BLOCK。已修。
- R002 改「限制條件證據」：沒寫 WHERE 但有 JOIN ON 常數／JOIN 鍵值／子查詢或 WITH 內有 WHERE，依 `rules.yaml` 的 `restriction_verdicts` 判定（使用者決定：預設全部 PASS，但 OUTER JOIN 常數的說明必須講明「只限縮副表、不縮主表」）。
- `estimate_requires_candidate: false`：有任何 finding 就可給預估幅度。
- 遮罩放行 ≤4 字元 ASCII 短代碼（'114%'、'55'、'H'），否則 AI 看不到值無法改寫。
- ai_service 決策 log 由 debug 提升到 INFO（不含 SQL 內容）。
- 新增去識別化蒐集檔（PRD §6.3 的明確例外，使用者決定）：不存申請單號、原始常數、附件名。

### 2026-09-16 晚：建議寫法三態
- 模型必填 `rewrite_outcome ∈ {provided, not_needed, advice_only}`；伺服器再加 `gated`（守門擋）、`rejected`（複核擋）。前端三種文案：「無需改寫」（綠）、「僅提供方向」（黃，附原因）、「本次不提供」（PRD 固定句，只用於 gated／rejected）。
- 使用者決定：**需要業務假設才能等價的改寫（欄位串接切分、日期格式不明）只給片段範例＋說明假設，不產生完整改寫**。
- 後置萬用字元 `LIKE '114%'` 不再當改善項目（Oracle 本就範圍掃描）。

### 2026-09-17 上午：對照組驗證「AI 都說寫法良好」
- 用 10 個藏缺陷的 SQL 驗證：模型有辨別力（7 案正確改寫），使用者的 6 份真實 SQL 確實寫得好。
- **真正根因**：Gemma4 預設「思考模式」把 3072 個 num_predict 全部花在內部推理，content 空白、done_reason=length → 降級「暫時無法使用」。已在請求加 `think:false`（`app.yaml ollama.think_default`、環境變數 `OLLAMA_THINK`），回應時間 40–90 秒 → 6–20 秒。
- payload 新增 `structure_flags`（not_in_subquery、distinct、cartesian_join、select_star…）讓模型不用猜。
- prompt：選 not_needed 前要逐項檢查五類細微寫法，reason 必須列出實際檢查過的項目、只列從 SQL 文字看得出來的事（不可宣稱「無隱含型別轉換」）；NOT IN→NOT EXISTS、OR→UNION ALL、GROUP BY 拆分、移除 DISTINCT 等結構變更一律 advice_only；SUBSTR 前綴改寫用 `>= '114' AND < '115'`，不得補成日期格式。
- `_revalidate_suggested_sql` 新增結構旗標相等比對作為最後防線。

### 2026-09-17 下午～晚：畫面
- advice 新增 `before`（原寫法片段，模型逐字複製）；`example` 設為必填（否則模型只回 before）；example／before 送回前還原遮罩。
- SQL 寫法比較區：移除雙欄原始 SQL 面板與複製按鈕；結構為「判定文字 → 完整改寫逐行逐字對照（黃底＝建議修改處）→ 逐段對照」；example 內「若…：」假設前綴自動抽成「前提」註解；副標紅色警語「AI 建議寫法僅供參考，採用前務必先於測試機驗證」。
- 摘要列改 4 張卡（移除建議寫法卡）；COST 卡依 R001 顯示 ✓ 綠或 ✕ 紅（無「C」）；所有不符合語意紅色（補上原本缺漏的 `.tone-red .m-icon`）。
- 字級：預估／比較區放大約 20%、徽章 13px；全頁字級階層 13/14/15/19–20/28/32，次要文字統一 #5b6577，最重字重 800；建議卡片底色依 impact。

### 2026-09-17 晚：依列印報告回饋的畫面調整（使用者逐點指定）
- 摘要卡：所有「符合」卡片整張淺綠底（`.metric.tone-green`）；COST 低於門檻時不再顯示數字，
  直接顯示「符合中心規範」（超標仍顯示紅色數字）；「改善優先指數」改名「改善指數」，右上角
  圖示改為等級文字（目前良好／建議改善／優先改善）而非重複數字；第 4 張卡改名「智慧改善建議」、
  圖示固定「AI」；右上角圖示放大 20%（34→41px）。
- 指數組成改白話：後端 `ImprovementBreakdownItem` 新增選填 `detail`，每一分項說明「量什麼、
  本案數值、最多幾分」（上限值從 `rules.yaml` 讀，不寫死），例如「目前 COST 68,888 約為規範
  門檻 100,000 的 69%，越接近或超過門檻加分越多，最多 15 分」；前端展開時另有一句總說明。
- 預估改善效果：整區改單一淺綠色系（移除 gray/blue/green 分帶），「預估有改善空間」晶片
  仍只在 ≥20% 時顯示。
- 「SQL 寫法比較」改名「優化前後比較」；逐行對照標題不再重複 COST；右欄與片段標籤改
  「AI 建議寫法」；警語在網頁上也是紅色（根因：`.card-desc` 在全頁視覺段落後宣告、特異性
  相同蓋掉 `.card-warning`，print.css 用 `!important` 才會在 PDF 變紅；已改用
  `.card-desc.card-warning` 提高特異性）。
- advice_only 的說明改白話：前端標題句改為「改善方向請見上方「智慧改善建議」與下方逐段
  對照，採用前請先確認：」；prompt 新增「advice_only 的 reason 寫法」（1～2 句、直指需業務
  確認的事與後果、不可加「故不自動產生建議寫法」結語）；`ai_service._tidy_advice_only_reason`
  以正則剝除句尾「故／因此／本次 不自動產生建議寫法」類結語作為確定性防線。已用本機程式碼
  直連正式主機 Gemma4 驗證（DISTINCT＋JOIN 案例回「移除 DISTINCT 前，請先確認 JOIN 後的
  資料是否已經唯一；若不是，拿掉 DISTINCT 會改變查詢結果…」）。

### 2026-09-17 深夜：5 案盲點測試、docx 巢狀 SQL、Ollama 截斷防線、改名 SQLCheck AI
- 系統標題改為「SQLCheck AI｜SQL 效能優化助手」（index.html、App.tsx 品牌區、app.yaml `app.name/title`、FastAPI title）。README／deploy 腳本仍用專案代號 SQLCheck 2.0，未改。
- **Ollama 靜默截斷 prompt（最重要）**：長 SQL 讓 prompt 超過 `num_ctx` 時 Ollama 不報錯，模型失去系統指令後回英文、捏造資料表。現在 `ai_service._num_ctx_for` 依 prompt 長度在 `num_ctx_default`（8192）～`num_ctx_max`（32768，`OLLAMA_NUM_CTX_MAX`）間自動放大（1024 倍數；小查詢也會因保留完整 num_predict 而升到 10240）；回應 `prompt_eval_count >= num_ctx` 一律降級不重試；summary ≥20 字無中文視為無效（重試一次後降級）。
- **sql_detect 括號深度感知**：`FROM (` 後空行再 `SELECT` 的巢狀查詢不再被切成多段、不再在括號內塞 `;`；括號未閉合時也不做尾隨散文截斷。
- 其他盲點：R001 等於門檻時說明改「達到或超過規範門檻」；模型自創的 `:STR_NNN` 綁定改顯示 `:VALUE`（`masking.scrub_invented_placeholders`，只動原始 SQL 沒有的名稱）；前端 `looksLikeSqlFragment` 讓中文散文型 example 不進逐段對照。
- 已確認為設計而非 bug：R008 在 `forbidden_operations` 空清單時對 UPDATE 重要資料表只給 R007 提醒；改善指數可在「符合中心規範」下仍達 80+（優先改善），因 NOTICE 權重加總所致。

### 2026-09-17 深夜（二）：長 SQL 輸出截斷 → 三區全降級的根因修復
- 正式主機 log：`model output truncated (done_reason=length, eval_count=3072)`。**輸出**撞上 num_predict（不是輸入被截斷）：守門沒看長度，模型嘗試把 6,000 字 SQL 完整改寫進 JSON，半途被切、整份作廢。
- 守門新增長度維度：`_compute_gates(..., sql_tokens, num_predict)`，`sql_tokens × ai_gate.rewrite_token_ratio(1.2) + ai_gate.rewrite_reply_overhead_tokens(900) > num_predict` → `decline_code=too_long_for_rewrite`，只給方向與片段。gate log 多了 `sql_tokens=`。
- 輸出截斷的有界補救：原本允許改寫且剩餘時間 ≥ 60 秒時，用 `candidate_allowed=false` 的 payload 重試一次（`decline_code=rewrite_truncated`）；`get_ai_result` 以單一 `deadline`（timeout_seconds=180）涵蓋所有嘗試。
- 降級分類：`AiResult.degrade_code` ∈ output_truncated／prompt_truncated／timeout／connection／http／invalid_response，`message` 對應專屬中文句（`DEGRADE_MESSAGES`）；前端三張卡直接顯示 `ai.message`，不需改版面。
- 長度守門或 rewrite_truncated 時，伺服器的原因一律覆蓋模型自己的 reason（模型常照抄通用句）。
- `num_ctx_default` 8192→16384；`_num_ctx_for` 只在倍數分級間切換（避免 Ollama 反覆重載模型）。
- 驗證：docx 直連正式主機三次 19–25 秒穩定 gated＋三條含 before/example 的建議；小查詢仍 provided；fake_ollama truncated 模式前端顯示專屬訊息。

### 2026-09-17 深夜（三）：條件改寫的等價性由系統驗證（`services/rewrite_rules.py`）
- 起因：模型把 `SUBSTR(MANAGE_CD,6,3)='551'` 改成 `LIKE '__%551%'`（結果不同）並以「AI 建議寫法」示人；片段建議原本零驗證，整段改寫的結構複核也看不到條件語意。
- 規則白名單（每條附等價論證）：`SUBSTR(col,p,n)='v'`→`col LIKE '<p-1 個 _>v%'`（p=1 也接受上下界寫法）；`TRUNC(col)=X`→`col>=X AND col<X+1`（附「X 不含時分秒」前提）；`NVL(col,'a')='b'`→`(col='b' OR col IS NULL)`／`col='b'`；同欄位 `OR` 串→`IN`。
- 片段：`AdviceItem.verification` ∈ verified／corrected（example 已被系統換成推導結果）／unverified（前端標「AI 示意寫法」、不用黃底）；`assumption` 顯示為「前提：…」。
- 整段改寫：`_revalidate_suggested_sql` 最後一步 `verify_predicate_changes`，任何條件變動都必須是規則可推導的，否則退回（原因句講「查詢結果可能改變」，不用「等價」字眼）。
- 加新規則的方法：在 `rewrite_rules._RULES` 加一個函式，回傳 `Rewrite(rule, canonical, accepted, assumption)`，並在 `tests/test_rewrite_rules.py` 寫正反例。

### 2026-09-17 深夜（四）：預估改善效果改為「改善潛力」等級
- 使用者決定：百分比從未經量測（AI 不看執行計畫／統計／改後 COST），改為伺服器依事實推算的高／中／低（`ai_service.improvement_potential`）。
  **2026-09-17 PR #1 更新後的推算表（AI impact 不再參與；2026-09-17 第三方 Review 後再收緊）**：≥2 項 server 已驗證改善證據 → 高；恰 1 項已驗證證據 → 中；BLOCK 單獨存在（確定性不符合，但沒有已驗證改善證據）、只有 R004／R005／R006 寫法類提醒或未通過驗證的建議 → 低；只有治理型提醒（R007 重要資料表等）→ `notice_only`（畫面「有提醒，但未確認具體改善點」，**不得**顯示「目前寫法良好」）；完全無發現 → None（畫面「目前寫法良好」）。「已驗證證據」= `verification` 為 verified／corrected 的片段，或通過 `_revalidate_suggested_sql` 的整段改寫。
- `estimated_improvement_pct` 仍在 API 與蒐集檔（分析用），畫面不顯示；`estimate_reason` 已移除。

### 2026-09-17（PR #1 Batch 1）：Ollama 11434 防火牆 fail-closed 與部署硬化
- 政策：**只有 SQLCheck 容器可以連到主機 Ollama 11434**，一般區網電腦必須連不上；正常流量
  只有 `Browser → SQLCheck (443) → 容器 → 主機 Ollama`。不建立固定開發機 IP 例外，也不加
  「無條件 LocalSubnet Block」——那會連 Docker Desktop（WSL）→ 主機的流量一起擋掉。
- `deploy.ps1` Step 3 改為 audit → validate → create → verify：列舉**所有**會開啟 TCP 11434
  的 Inbound 規則；同名規則逐項驗證 Enabled／Direction／Action／LocalPort／InterfaceAlias／
  RemoteAddress／Profile（不再只因名稱存在就略過）；建立後重新讀回驗證。
- fail-closed：稽核／建立／驗證失敗或偵測到 Enabled＋Allow＋未限縮來源的 11434 規則時，
  列印問題規則與修正指令並**中止部署**；緊急時可用新的 `-BreakGlassFirewall` 略過（會印出
  明顯警告，屬例外而非正常流程）。
- 新增 `deploy/tests/firewall-helpers.Tests.ps1`（96 項判斷邏輯測試，任何 OS 的 PowerShell 7
  可跑，不碰防火牆；`deploy.ps1` 本體不會被執行）。
- 復原：`Remove-NetFirewallRule -DisplayName 'SQLCheck - Ollama API (container only)'`。
- **未在主機驗證（必須在正式主機驗收）**：`Get-NetFirewallRule`／`New-NetFirewallRule` 的實際
  行為、`vEthernet (WSL*)` 介面是否存在、容器能否連到 `host.docker.internal:11434`、
  `/api/health` 的 `ai_available`、以及「第二台區網電腦連 11434 失敗」這三項主機端驗證，
  都只能在 Windows 11 + Docker Desktop + RTX 4090 正式主機上執行；macOS 開發機無法驗證。

### 2026-09-18 Knowledge v1 correction（PR #2）
- `backend/app/knowledge/pattern_catalog.yaml` 是 SQL optimization knowledge 的機器可讀
  source of truth；`skills/sqlcheck-oracle-review/` 說明怎麼使用。Runtime 目前不讀取它。
- **本節更正上方「2026-09-17 深夜（三）」把四條規則都寫成等價白名單的說法。**
  `rewrite_rules.py` 的行為沒有改變，但治理上的認定如下（「runtime_gap」＝ runtime 仍會把
  片段標成 verified／corrected，但治理不認可）：
  - `SUBSTR(col,p,n)='v'` → `col LIKE '<p-1 個 _>v%'`：VERIFIED_REWRITE。p=1 時 runtime
    另外接受的上下界寫法依賴 collation，列為 runtime_gap。
  - `TRUNC(col)=X` → 範圍：ADVICE_ONLY＋runtime_gap。「X 不含時分秒」只寫成 assumption，
    沒有檢查；X 帶時間時兩種寫法回傳的資料不同。
  - `NVL(col,'a')='b'` → 條件式：ADVICE_ONLY＋runtime_gap。NVL 對文字資料回傳 VARCHAR2
    （nonpadded 比較），CHAR 欄位與文字常數則是 blank-padded 比較；SQLCheck 看不到欄位型別。
  - 同欄位 OR → IN：VERIFIED_REWRITE，但只授權 1～1000 個值（Oracle 19c 單一 IN 清單上限）。
    超過 1000 個值列為 runtime_gap：規則沒有檢查數量，目前是因為約 997 個值以上會在規則內
    觸發 RecursionError 而剛好被擋下，這是副作用，不是邊界。
- 以上 runtime_gap 必須在 Phase 2（Pattern Selector）之前，以獨立的 correctness PR 修正
  `rewrite_rules.py`；在那之前，不可把 runtime 對這些寫法的 verified／corrected 標示當成
  治理已證明。
- 之後新增 rewrite rule 時，除了 `rewrite_rules.py` 與 `tests/test_rewrite_rules.py`，也要在
  `pattern_catalog.yaml` 加恰好一個條目（`tests/test_pattern_catalog.py` 會檢查）。

### 2026-09-18 Runtime Correctness v1（branch `feature/sqlcheck-runtime-correctness-v1`）
- 上一段列出的四個 runtime_gap 已在 `rewrite_rules.py` 修正，catalog 目前沒有任何 runtime_gap：
  - TRUNC → 範圍、NVL → 條件式：移除推導規則。這類片段一律 unverified（畫面顯示「AI 示意
    寫法」），整段改寫若改動這些條件會被退回（rejected），也不再計入改善潛力的已驗證證據。
    TRUNC 沒有只靠 SQL 文字就能證明的子集：欄位是 NUMBER 時 TRUNC 是去掉小數，
    `TRUNC(n)=0` 對應 -1<n<1。
  - SUBSTR：只接受 canonical LIKE；p=1 的上下界寫法會被改成 LIKE（corrected），整段改寫
    則退回。另修正 v 含單引號時 canonical 產生不合法 SQL 的既有 bug。
  - 同欄位 OR → IN：以 `ORACLE_IN_LIST_MAX_EXPRESSIONS = 1000` 明確限制 2～1000 個值；OR 串
    改用非遞迴展開，不再依賴 Python recursion limit。
- 系統提示同步：6-2 只列 SUBSTR→LIKE 與同欄位 OR→IN 為系統可推導；TRUNC／NVL／TO_CHAR
  改寫改為需要前提的 advice_only；後置萬用字元改為「不屬於 R004 的命中範圍」，並移除建立
  文字索引的建議。**尚未用正式主機 Gemma 驗證**，請依第 6 節用通道直連後跑 golden 與
  TRUNC／NVL／SUBSTR 範例。
- `tests/test_pattern_catalog.py` 以合成探測直接呼叫 runtime：runtime 若再認證 catalog 不認可的
  寫法，而 catalog 沒有對應的 runtime_gap，測試會失敗。

### 2026-09-18 Pattern Selector v1 — Phase 2 Shadow Mode
- 新增 `backend/app/services/pattern_selector.py`，開始在 Runtime **唯讀**載入
  `pattern_catalog.yaml`，但目前仍不把 catalog 內容送進 Gemma。
- Selector 將結果嚴格分成兩層：
  - `exact`：已有特定 deterministic detector 命中（rule_engine rule id、rewrite_rules rule、
    sql_parser complexity flag、或既有 many_tables threshold）。
  - `family_signal`：只有 R005／R006／outer_join／group_by 等較寬的 family signal 命中；
    **不得**當成特定 pattern 已確認，也不得進入未來 context candidate。
- `context_candidate_ids` 只取 exact，且即使未來 OUT_OF_SCOPE pattern 有 detector，也明確排除，
  避免 INDEX／Execution Plan 等 Class D 知識被送進模型。
- `ai_service.get_ai_result` 目前只在 shadow mode 呼叫 selector，INFO log 僅記錄 pattern id/count；
  不記 SQL、literal、table name、模型文字。selector 若失敗只 warning，既有 AI path 照常執行
  （fail-open diagnostics），不會把整次分析降級。
- 本 Phase **沒有**改 Gemma payload、system prompt、candidate gate、compliance、改善指數、
  改善潛力、rewrite verification、API schema 或前端。下一階段 Compact Context Adapter 才會
  研究如何只注入少量 exact pattern；family_signal 在沒有特定 detector 前一律不可注入。
- 正式主機 10.97.15.58 的 11434 / Windows Firewall 問題依專案 owner 決策暫時與核心開發解耦：
  目前不修改該主機防火牆設定，也不讓 Step 3 驗收阻擋 Knowledge／Selector／Context 核心工作；
  最後再獨立做正式主機 security hardening 與驗收。

### 2026-09-18 Compact Context v1 — Phase 3 correction
- Phase 2 的「只 shadow、不送進 Gemma」是當時的安全過渡狀態；Phase 3 起新增
  `backend/app/services/context_adapter.py`，只把 Pattern Selector 的 **exact** match
  轉成小型 `knowledge_context` 放進 `<SQL_DATA>`。不要再把「catalog 永遠不進模型」當成現況。
- 注入邊界是程式硬限制，不靠模型自律：
  - `family_signal` 永不注入；
  - `OUT_OF_SCOPE` 永不注入；
  - 只保留實際送給 Gemma 的 representative statement 所命中的 pattern；
  - 優先序固定為 VERIFIED_REWRITE → ADVICE_ONLY → INFORMATIONAL；
  - 預設最多 4 項、JSON 字元總量最多 1800；程式另有 hard cap 8 項／6000 字元；
  - 只注入 catalog 內人工審核過的 `model_guidance_zh_tw`，不帶 SQL、literal、table name、
    finding prose、family signal 或模型輸出。
- `SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED=false` 可在正式主機快速關閉 Phase 3 context 做 A/B／回復；
  關閉後仍保留 Pattern Selector 與既有 prompt/runtime，不需要 rollback commit。
- Selector／Context Adapter 都採 fail-open：catalog/context 失敗時只記 exception type，送給 Gemma 的
  knowledge_context 退回空陣列，不影響原有 AI 可用性。
- Phase 3 **不改** compliance、candidate gate、改善優先指數、改善潛力、rewrite proof、
  API response schema、前端、Ollama 參數、deploy 或 firewall。
- Prompt slimming 暫不和本 Phase 混做；先在正式主機用同一版程式做 context on/off golden A/B，
  確認品質再另開 PR，才能知道改善或退步是 context 還是 prompt 改動造成。

### 2026-09-18 App-only Deployment split
- 日常正式部署入口改為 `deploy/deploy.ps1`：只處理 Git ff-only 更新、.env、rollback image、
  build、TLS、單一 sqlcheck service recreate、health 與 smoke test。
- `deploy/deploy.ps1` **不修改** Windows Firewall、TCP 11434、OLLAMA_HOST、Ollama process 或
  Windows Trusted Root。正式主機已知的 11434 hardening 不再卡日常 application deploy。
- 舊的 firewall-aware 部署流程完整保留成 `deploy/deploy-infra.ps1`，只在最後做正式主機
  infrastructure/security hardening 時使用。
- App deploy 失敗時，除了 image rollback，也會回復本次部署前的 .env；rollback point 優先取
  「目前執行中 container 的 image id」，避免 latest tag 在 build 後已指向新版而失去真正上一版。
- 新增 `Deploy Script CI`（Windows runner）：PowerShell parser、App-only policy boundary、
  firewall helper regression 都是 merge gate。
- 正式主機後續標準流程：先 `git pull --ff-only origin main`，再
  `pwsh -NoProfile -File .\deploy\deploy.ps1 -SkipPull -RequireAi`。

### 2026-09-18 Business-Readable Advice v1（PR #8）
- 產品定位由「AI 幫你猜更快的 SQL」收斂為「中心規範確定性檢核 + 地端 Gemma 白話輔導 + Python 安全複核」。Gemma 可以積極提出方向，但不得把未知業務條件包裝成可直接套用的 SQL。
- 正式使用者 persona 是「懂業務邏輯、會寫 SQL，但不是 Oracle DBA」。畫面只要求同仁理解：哪裡值得注意、為什麼、怎麼處理、目前能不能直接採用。
- UI 語意：
  - `影響` → `改善機會`（值得檢視程度，不是實際效能提升幅度）。
  - `預估改善效果` → `建議採用狀態`。
  - `優化前後比較` → `原寫法與建議寫法`。
  - `改善指數` → `改善優先指數`，避免被誤認為效能分數。
  - unverified 片段顯示 `示意方向（請勿直接套用）`；verified/corrected 才能稱為系統確認的建議寫法。
- Runtime anti-hallucination：
  - advice example 若引入原 SQL 未出現的欄位／資料表／別名，伺服器隱藏 SQL 片段但保留有用的文字方向；
  - 遺失 DATE/TIMESTAMP typed-literal wrapper 的 example 不顯示成可執行 SQL；
  - `:STR_xxx`／`:NUM_xxx` 不得出現在人類可見 prose；
  - 索引／Execution Plan 等 SQLCheck 無法觀測的資料庫行為宣稱由 prompt + server prose guard 雙層收斂。
- Prompt 的最高原則改成「不知道就不要猜 SQL」；缺 WHERE、未知 JOIN key、未知 datatype 等資訊不足情境改為 prose-first，不為了填 example 而生成欄位或條件。
- 同欄位 OR→IN 的 advice fragment 現在可先移除純語法 wrapper `WHERE`／`ON` 再驗證；不擴大 rewrite authority。
- Cartesian join 沒有被新增為中心規範 BLOCK；但 rules.yaml 新增產品層 `structure.score_floors.cartesian_join=60`，讓缺少資料表關聯條件的 SQL 至少顯示「建議改善」，不再出現 compliance PASS + 改善優先指數「目前良好」的矛盾。
- Gemma response schema 不再要求模型猜 `estimated_improvement_pct`；API 欄位暫留相容，正式模型不再花 token 猜百分比。
- 新增 `docs/115-sqlcheck-innovation-positioning.md`：115 年創新項目的真實可行銷定位、頁面語意與年度 KPI 證據原則。
- 新增 Frontend CI；本輪 merge gate 為 Backend CI（pytest + Ruff）與 Frontend CI（Vitest + build）全綠。
- 正式機 Gemma live 驗證仍須於 merge/deploy 後重跑 Round 1 的 10 cases，至少人工確認 T01/T05/T07/T10。

## 4. 「AI 沒給建議寫法」的判讀順序（接手後最常被問）

1. 看 API 回應或畫面的 outcome：
   - `not_needed`：模型判定寫法已好，reason 應列出檢查項目。若 SQL 明顯有缺陷卻 not_needed → prompt 檢查清單問題。
   - `advice_only`：有方向但需業務假設 → 看「逐段對照」是否有 before/example。這是設計行為，不是 bug。
   - `gated`：守門擋（多段、非 SELECT、解析失敗、禁止旗標、**SQL 過長 too_long_for_rewrite**、**改寫時輸出截斷 rewrite_truncated**）→ reason 會寫具體原因。
   - `rejected`：模型給了改寫但結構複核擋下 → reason 有具體項目（例如「GROUP BY 與原始不同」、「改動了條件，系統無法確認查詢結果是否相同」）。後者代表模型做了 `rewrite_rules` 白名單以外的條件改法；若那種改法確實結果不變且常見，加規則（附等價論證）而不是放寬檢查。
   - AI 狀態 `unavailable`：先看 API 的 `ai.degrade_code`（output_truncated／prompt_truncated／timeout／connection／http／invalid_response），畫面訊息也已對應。再看正式主機 `docker compose logs sqlcheck | Select-String ai_service` 的 `done_reason`、`thinking_chars`、`eval_count`（`eval_count == num_predict` 是輸出截斷；`prompt_eval_count == num_ctx` 是輸入截斷，兩者修法不同）；若 thinking_chars>0 表示思考模式又被打開。若看到 `prompt truncated by ollama`，代表 SQL 長到連 `num_ctx_max` 都不夠，調高 `OLLAMA_NUM_CTX_MAX` 或請同仁拆分 SQL；若看到 `response not in Chinese`，先查同一請求的 `num_ctx raised to` 與 `prompt_eval_count` 是否貼近上限。
2. 重現方式：用第 6 節的直連腳本，不需要重新部署。
3. 已知模型品質限制（不是程式 bug）：偶爾漏提引號一致性（`coll_yr = 107`）；TO_CHAR 範例可能假設 'YYYYMMDD' 而非民國日期；before 偶爾跳行複製導致與原文不完全逐字相同（前端仍能 diff）。

## 5. 目前狀態與驗證數據

- GitHub Actions `Backend CI` 已成為 backend PR/main 的固定 gate。Compact Context v1 最新 CI：
  **499 passed / Ruff All checks passed**（2026-09-18，PR #6）。前一個 Large-AND robustness PR #5
  為 484 passed / Ruff clean；Pattern Selector PR #4 為 481 passed / Ruff clean。
- 前端本輪沒有修改；最近一次既有前端基線為 74 項測試與 build 全過。不要因 backend CI 綠燈
  宣稱重新跑過前端。
- 正式主機尚未用 Compact Context 版本做 Gemma live A/B。project owner 已要求：先把核心程式與
  Skill 修到 review/CI 完成，再一次通知正式主機 git pull；因此不要提早要求正式機更新。
- 既有人工驗證（test_01～03.pdf）：多重缺陷 SQL、笛卡兒積 SQL、乾淨 SQL 三案皆符合當時版本預期。
- 報告：`E2E_TEST_report_20260917.md`、`E2E_TEST_report_20260917_round2.md`、`SQLCheck2_E2E_test_report_20260916.md`。

## 6. 開發機驗證方法（不需部署）

```powershell
# 單元測試
cd D:\dev\SQL_check2\backend; uv run pytest -q; uv run ruff check .
cd D:\dev\SQL_check2\frontend; npm test -- --run; npm run build

# 用本機程式碼連正式主機真實 Gemma4（驗 prompt／守門改動最可靠的方法）
# 前提：正式主機的 Ollama 11434 不對區網開放（2026-09-17 起的 fail-closed 政策），
# 必須先建立通道，再把 base_url 指向通道的本機埠，例如：
#   ssh -N -L 11434:127.0.0.1:11434 <正式主機帳號>@10.97.15.58
# 然後寫一支 python：dataclasses.replace(get_settings(), ollama=replace(..., base_url="http://127.0.0.1:11434"))
# 再呼叫 ai_service.get_ai_result(...)，範例見 tasks/lessons.md 2026-09-17 段落與 scratchpad 的 validate_new.py 作法
# 不要為了圖方便把 11434 重新開放給區網；也不要建立固定的開發機 IP 例外。

# 本機看畫面：先 npm run build，把 frontend/dist/* 複製到 backend/static/，
# 設 OLLAMA_BASE_URL=http://127.0.0.1:11434（走上面的通道）SQLCHECK_ARCHIVE_ENABLED=false 啟動
# uv run uvicorn app.main:app --port 28000，瀏覽 http://127.0.0.1:28000。用完把 backend/static 清回只剩 .gitkeep。

# 對正式主機 E2E
curl -sk https://10.97.15.58/api/health
# POST /api/extract-sql（multipart file）與 /api/analyze {application_no,cost,sql,include_ai:true}

# 11434 安全驗收（在「第二台」區網電腦上執行，不是在正式主機上）
# Test-NetConnection 10.97.15.58 -Port 11434   -> 必須是 TcpTestSucceeded : False
# 絕不要「從其他電腦連 11434 成功」當成正常流程或驗收通過條件。
```

注意：Git Bash 工具在含中文的 heredoc 偶爾會 crash（`add_item failed`），寫檔用 Write 工具、執行用 PowerShell 較穩。

## 7. 尚未完成／建議的下一步方向（依優先序）

1. **正式主機統一更新 + Gemma A/B 驗證（目前核心）**：PR #6 Compact Context 已 merge；
   App-only deploy split 通過後才通知正式機一次 git pull。用同一組 golden 跑 Context on/off，
   比較 advice/rewrite 品質與 latency。
2. **Prompt slimming / A-B**：只有正式機 context on/off 基線穩定後，才縮短 system prompt 內重複 optimization prose；
   不和 context 接線混在同一變更，避免無法歸因。
3. **Knowledge coverage 精進**：依正式 SQL／去識別化 archive 的實際缺口補「specific detector → catalog guidance」，
   不把 family signal 直接升級成 exact，也不新增無法證明的 rewrite。
4. **Windows Firewall / 11434 hardening（最後獨立處理）**：正式主機 10.97.15.58
   目前 Step 3 會因既有 11434 規則 scope 不符而 fail-closed。這是已知部署／安全議題，不再作為
   Knowledge／Selector／Context 開發 gate；最後再獨立修正式主機規則、deploy diagnostics 與三項 E2E
   （container→Ollama、`/api/health`、第二台 LAN 11434 必須失敗）。
6. **before 片段校正**：模型偶爾跳行複製 before；可在後端用與前端 `locateOriginalFragment` 相同的 token 重疊邏輯校正到原始行。
7. **蒐集檔分析**：`data/sql_archive/*.jsonl` 累積後統計 `rewrite_outcome` 分布；若 `rejected` 比例高，檢視複核是否過嚴。
8. **R002 `restriction_verdicts`**：目前全 PASS 是業務決定；若中心日後要求較嚴，改 `rules.yaml` 即可，程式與測試已涵蓋 pass／review／block。

## 8. 絕對不要做的事（來自 lessons.md 的血淚）

- 不要用「再問模型一次」來判斷 AI 是否可信；用已知答案的對照組。
- 不要用 debug 等級記錄決策 log。
- 不要在遮罩上一刀切（全部遮會讓 AI 無法做值相依改寫；短 ASCII 代碼要放行）。
- 不要讓模型宣稱它無法驗證的事（欄位型別、索引、執行計畫）。
- 不要以為本機沒走到的分支（Docker 專用路徑）已被測過；為每個候選路徑寫獨立測試。
- 不要因為「規則引擎判 BLOCK」就相信輸入沒被上游截斷（先對照擷取結果與原檔）。
