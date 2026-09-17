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
5. 開發機（10.97.15.54）沒有 Docker 也沒有 Ollama；但正式主機的 Ollama
   http://10.97.15.58:11434 可直接連線，驗證 prompt 改動請用「本機程式碼直連正式主機
   Ollama」的方式（見本檔第 6 節），不要只用 fake_ollama。
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
| `frontend/src/components/SummaryCards.tsx` | 4 張摘要卡（中心規範／COST／改善優先指數／改善建議） |
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

## 4. 「AI 沒給建議寫法」的判讀順序（接手後最常被問）

1. 看 API 回應或畫面的 outcome：
   - `not_needed`：模型判定寫法已好，reason 應列出檢查項目。若 SQL 明顯有缺陷卻 not_needed → prompt 檢查清單問題。
   - `advice_only`：有方向但需業務假設 → 看「逐段對照」是否有 before/example。這是設計行為，不是 bug。
   - `gated`：守門擋（多段、非 SELECT、解析失敗、禁止旗標）→ reason 會寫具體原因。
   - `rejected`：模型給了改寫但結構複核擋下 → reason 有具體項目（例如「GROUP BY 與原始不同」）。若複核過嚴可討論放寬，但要先確認語意真的等價。
   - AI 狀態 `unavailable`：正式主機 `docker compose logs sqlcheck | Select-String ai_service` 看 `done_reason`、`thinking_chars`、`eval_count`；若 thinking_chars>0 表示思考模式又被打開。
2. 重現方式：用第 6 節的直連腳本，不需要重新部署。
3. 已知模型品質限制（不是程式 bug）：偶爾漏提引號一致性（`coll_yr = 107`）；TO_CHAR 範例可能假設 'YYYYMMDD' 而非民國日期；before 偶爾跳行複製導致與原文不完全逐字相同（前端仍能 diff）。

## 5. 目前狀態與驗證數據

- 最新 commit `815c056`（main，已推送）。後端 286 項測試、前端 66 項測試、ruff、build 全過。
- 正式主機最後一次由使用者部署的版本在 `6a7294c` 之前；**`80f78e8`（放大字級）與 `815c056`（全頁視覺）尚未部署**，需 `git pull` + `deploy\deploy.ps1`。
- 使用者人工驗證（test_01～03.pdf）：多重缺陷 SQL、笛卡兒積 SQL、乾淨 SQL 三案皆符合預期。
- 報告：`E2E_TEST_report_20260917.md`、`E2E_TEST_report_20260917_round2.md`、`SQLCheck2_E2E_test_report_20260916.md`。

## 6. 開發機驗證方法（不需部署）

```powershell
# 單元測試
cd D:\dev\SQL_check2\backend; uv run pytest -q; uv run ruff check .
cd D:\dev\SQL_check2\frontend; npm test -- --run; npm run build

# 用本機程式碼直連正式主機真實 Gemma4（驗 prompt／守門改動最可靠的方法）
# 寫一支 python：dataclasses.replace(get_settings(), ollama=replace(..., base_url="http://10.97.15.58:11434"))
# 再呼叫 ai_service.get_ai_result(...)，範例見 tasks/lessons.md 2026-09-17 段落與 scratchpad 的 validate_new.py 作法

# 本機看畫面：先 npm run build，把 frontend/dist/* 複製到 backend/static/，
# 設 OLLAMA_BASE_URL=http://10.97.15.58:11434 SQLCHECK_ARCHIVE_ENABLED=false 啟動
# uv run uvicorn app.main:app --port 28000，瀏覽 http://127.0.0.1:28000。用完把 backend/static 清回只剩 .gitkeep。

# 對正式主機 E2E
curl -sk https://10.97.15.58/api/health
# POST /api/extract-sql（multipart file）與 /api/analyze {application_no,cost,sql,include_ai:true}
```

注意：Git Bash 工具在含中文的 heredoc 偶爾會 crash（`add_item failed`），寫檔用 Write 工具、執行用 PowerShell 較穩。

## 7. 尚未完成／建議的下一步方向（依優先序）

1. **安全缺口（高）**：正式主機 Ollama 11434 可從區網直接連線，違反 PRD §46。`deploy.ps1` 的規則只放行 WSL 介面，表示另有放行規則（疑 Ollama 安裝程式自建）。在正式主機執行
   `Get-NetFirewallRule | ? {$_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound'} | Get-NetFirewallPortFilter | ? LocalPort -eq 11434`
   找出來源，加 Block 規則限制 LocalSubnet 來源，並在 deploy.ps1 加自動驗證（容器內能連 host.docker.internal:11434 才保留）與回滾。開發機無法測試防火牆，需在正式主機小心操作。
2. **部署最新兩個 commit 並讓同仁實測**：重點看逐段對照的黃底標示、1366×768 筆電可讀性、列印 PDF。
3. **before 片段校正**：模型偶爾跳行複製 before；可在後端用與前端 `locateOriginalFragment` 相同的 token 重疊邏輯校正到原始行。
4. **蒐集檔分析**：`data/sql_archive/*.jsonl` 累積後統計 `rewrite_outcome` 分布；若 `rejected` 比例高，檢視複核是否過嚴（例如 GROUP BY 拆分在定寬欄位其實等價）。
5. **prompt 微調候選**（要先用第 6 節直連驗證再改）：民國日期格式提示（7 碼 'YYYMMDD'）；引號一致性檢查更明確；不要把「確認查詢範圍」湊成建議。
6. **R002 `restriction_verdicts`**：目前全 PASS 是業務決定；若中心日後要求較嚴，改 `rules.yaml` 即可，程式與測試已涵蓋 pass／review／block。
7. **效能**：prompt 約 4,000 tokens，每次 prompt eval 佔多數時間；若要再快，可精簡 system prompt 或確認 Ollama prefix cache 有生效（keep_alive 30m）。
8. 開發機 `_find_static_dir` 會優先選有 `.gitkeep` 的 `backend/static`（非空）而非 `frontend/dist`，本機看畫面要手動複製 dist；可考慮忽略只含 .gitkeep 的目錄。

## 8. 絕對不要做的事（來自 lessons.md 的血淚）

- 不要用「再問模型一次」來判斷 AI 是否可信；用已知答案的對照組。
- 不要用 debug 等級記錄決策 log。
- 不要在遮罩上一刀切（全部遮會讓 AI 無法做值相依改寫；短 ASCII 代碼要放行）。
- 不要讓模型宣稱它無法驗證的事（欄位型別、索引、執行計畫）。
- 不要以為本機沒走到的分支（Docker 專用路徑）已被測過；為每個候選路徑寫獨立測試。
- 不要因為「規則引擎判 BLOCK」就相信輸入沒被上游截斷（先對照擷取結果與原檔）。
