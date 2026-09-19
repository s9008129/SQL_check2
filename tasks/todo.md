# 2026-09-15 SQLCheck 2.0 建置

## 目標 / 驗收
- 依 PRD v6 + Prototype v4 建立單一容器的 SQLCheck 2.0（FastAPI + React + 規則引擎 + Ollama/Gemma 4）。
- 開發機完成所有可完成的測試；正式主機一鍵部署 `deploy/deploy.ps1`（HTTPS 443、自簽憑證）。
- 詳細計畫：C:\Users\ca0283\.claude\plans\must-use-rpd-best-use-lively-cupcake.md

## Checklist
- [x] Phase 0 骨架（backend uv 專案、frontend Vite 骨架、Dockerfile/compose/.env.example/.dockerignore/.gitignore/README）
- [x] Phase 1 Parser + 規則引擎 + 改善優先指數 + 單元測試（73 項測試通過）
- [x] Phase 2 附件擷取 + SQL 辨識 + fixtures（32 項測試通過，另修正 5 個邊界案例，見 lessons.md）
- [x] Phase 3 AI service（masking、schema、守門、降級）+ fake_ollama（32 項測試通過；另補上核准計畫中「建議寫法需重新驗證」這項守門，子代理任務說明漏寫，已自行補上並測試）
- [x] Phase 4 API + run.py + certgen（含自動化安全掃描抓到並修復的路徑穿越漏洞，6 項回歸測試）
- [x] Phase 5 前端元件、樣式、列印、響應 + vitest（52 項測試通過，tsc/build 皆過）
- [x] Phase 6 本機整合 E2E（Playwright，1366×768／1920×1080／480 窄螢幕）：後端服務真實前端 build + fake_ollama，實際跑過「貼上 SQL 檢核」「上傳 .sql 附件辨識」兩條路徑，過程中發現並修正一個真實 UI 重複文字 bug（見 lessons.md）
- [x] Phase 7 deploy.ps1 / smoke-test.ps1 / README-deploy.md — 完成，PowerShell 語法驗證通過（0 errors x3），內容經覆核；端對端執行仍待正式主機驗證
- [x] Phase 8 硬化：log 稽核（子代理專案審查，結論 CLEAN，並補強一個潛在缺口）、
      prompt injection 防護（system prompt 明文禁止把 SQL 內容當指令 + 2 項測試）、
      XSS 檢查（前端全文 grep 確認無 `dangerouslySetInnerHTML`／`innerHTML`）、
      危險函式檢查（後端全文 grep 確認無 `eval`／`exec`／`subprocess`／`pickle` 等）
- [x] Verify：`uv run pytest`（191 通過）、`uv run ruff check`（無錯誤）、`tsc --noEmit`（無錯誤）、`npm run test`（52 通過）、`npm run build`（成功）、Playwright E2E（三種解析度手動驅動通過）；PS 語法檢查（3 個腳本皆 0 錯誤）

## Results（完成摘要）

**已完成**：PRD 全部 8 個開發階段（Phase 0-8）。單一 Docker Container 架構、
無資料庫、無 Oracle 連線；決定性規則引擎（R001-R008）+ 改善優先指數模型
（F+S+C+A，含 BLOCK 下限）+ 附件擷取（TXT/SQL/MD/CSV/DOCX/PDF）+ SQL 辨識 +
AI 服務（遮罩、structured output、多層安全守門、prompt injection 防護）+
React Dashboard（忠實還原網頁雛形，含所有 PRD 規定文案與狀態）+ HTTPS 自簽
憑證 + 正式主機一鍵部署腳本，全部完成並在開發機驗證通過。

**測試總數**：後端 191 項（`uv run pytest`）、前端 52 項（`npm run test`），
外加 Playwright 手動驅動的端對端驗證（1366×768／1920×1080／480px，含檢核與
附件上傳兩條主要流程），以及正式主機專用的 golden dataset 腳本
（`backend/tests/golden/run_golden.py`；目前可在 Mac 以 Gemini API 執行，也可在正式機以 Ollama/Gemma 執行）。

**過程中發現並修正的真實問題**（詳見 lessons.md）：
1. sqlglot `error_level=RAISE` 對壞掉的 SQL 不可靠，需另外檢查頂層節點型別。
2. `exp.And`／`exp.Or` 本身是 `exp.Func` 子類別，函數偵測需改用 `exp.Predicate`。
3. sqlglot `find_all(exp.Literal)` 不依原始文字順序回傳，遮罩改用 token 位置。
4. Big5 解碼被 charset-normalizer 誤判成韓文；PDF 掃描偵測門檻誤傷短 SQL。
5. 多段 SQL 候選用空行接起來會被誤判成 1 段解析失敗。
6. `main.py` SPA fallback 路由存在路徑穿越漏洞（自動化安全掃描發現）。
7. AI 安全守門原本漏了「建議寫法需重新解析＋比對表集合＋重跑規則引擎」這一層
   （核准計畫有寫，交辦子代理時漏寫，覆核時自行補上）。
8. 前端在「伺服器端拒絕建議寫法」時會把固定文案顯示兩次（唯有實際跑通前後端
   整合才會現形，前端單元測試的假資料用了不同字句所以沒測出來）。

**尚未／無法在開發機驗證的部分**：
- Docker 映像實際建置與啟動（開發機無 Docker）。
- `deploy.ps1` 完整流程與正式主機 Ollama 綁定／防火牆設定（需 Windows 系統管理員
  權限與真實 Docker Desktop／Ollama，僅能在正式主機驗證；`-CheckOnly` 模式的邏輯
  已在開發機驗證）。
- 真實 Gemma 4 的輸出品質與繁體中文用詞（`run_golden.py` 已備妥，需正式主機執行）。
- 改善優先指數的正式權重（`rules.yaml` 標示 `provisional: true`，待業務端確認）。

## Risk & Rollback
- 風險：中（新系統、部署腳本改動正式主機 Ollama 綁定與防火牆）。
- 回滾：`deploy.ps1 -Rollback`（回前版映像）、`-Down`；Ollama 環境變數可手動移除。

## Dependencies & Environment
- Python 3.12 / uv、Node 22；Docker 僅正式主機；OLLAMA_MODEL=gemma4:31b（正式主機 `ollama list` 實際顯示的標籤；先前計畫誤記為 gemma4:31b-it-qat，2026-09-15 首次部署 Preflight 發現後修正）。

## Working Notes
- Windows 開發機無 Docker/Ollama 時仍可用 respx + scripts/fake_ollama.py；Mac 可直接用 Gemini API，不需安裝地端模型。
- sqlglot hint 只在 SELECT 後成為 exp.Hint → R003 用 token 層判定。
- 建議寫法回傳前還原遮罩。

## Working Notes（持續更新）
- certgen.py 的 SAN 清單務必包含 127.0.0.1（loopback IP），Dockerfile HEALTHCHECK 以憑證釘選（cafile=/certs/sqlcheck.crt）方式驗證，不停用 TLS 驗證。
- deploy.ps1 的 `Set-OllamaHostBinding` 用 `Get-Process -Name 'ollama*','ollama app'` 嘗試停止 Windows Ollama 行程；正式主機上 Ollama 系統匣程式的實際 process name 未經現場確認，若停止失敗腳本只會靜默略過（不阻斷部署），正式部署時請留意 Step 2 的輸出，必要時手動結束該行程。

## 2026-09-16：修正「一律不給建議寫法」與「WHERE 死判」根因，新增 SQL 蒐集檔

### 已完成
- 修正 `sql_detect._trim_trailing_prose` 連續空行截斷附件 SQL 的 bug（真實案例：
  LND_台糖馬稠後產業園區土地課稅情形.docx 被誤判 R002 BLOCK）。
- R002「WHERE 查詢條件」改為看限制條件證據（`sql_parser._restriction_evidence`）：
  JOIN ON 含常數、僅 JOIN 鍵值連接、子查詢／WITH 內有 WHERE，依 `rules.yaml`
  `R002.restriction_verdicts` 判定，預設皆 PASS 並給白話說明。
- `app.yaml` 的 `candidate_forbidden_complexity_flags` 移除 outer_join／
  group_by_aggregate／distinct（原因：這三者涵蓋了幾乎所有真實業務查詢，導致
  candidate_allowed 對使用者 6 份測試 SQL 全部為 false）；改由
  `sql_parser.structural_signature` + `ai_service._revalidate_suggested_sql` 的
  結構複核（JOIN 種類順序、GROUP BY、DISTINCT、彙總函數、ORDER BY、欄位數）把關。
- `estimate_requires_candidate` 改為 false；`num_predict` 1024→3072、
  `OLLAMA_TIMEOUT_SECONDS` 120→180；前端 `AI_TIMEOUT_MS` 150s→200s。
- `masking.py` 新增「短 ASCII 常數（<=4 字元）不遮罩」規則，讓 AI 看得到
  `'114%'`／`'55'`／`'H'` 這類代碼；新增 `literal_hints`（結構提示，不含值）；
  新增 `deidentify_sql()`（供蒐集檔用，更嚴格）。
- `ai_service.py` 決策 log 由 debug 提升為 info（gate／model／revalidation／
  forbidden-phrase 皆可在正式主機 log 直接看到，不含 SQL 內容）；新增
  `decline_code` 讓「不提供建議寫法」的原因具體化；新增 `done_reason=length`
  截斷偵測（不重試，直接降級並記 log）。
- 新增 `backend/app/services/sql_archive.py`：去識別化 SQL 蒐集檔（JSON Lines，
  `data/sql_archive/*.jsonl`），只在 `include_ai=true` 時記錄，不存申請單號／
  原始 SQL／附件檔名；`docker-compose.yml`／`Dockerfile`／`deploy.ps1`／
  `.env.example`／`.gitignore` 同步更新，`deploy.ps1` Step 6 前新增寫入探測。
- System prompt（`sql_review_zh_tw.txt`）新增「candidate_allowed 為 true 時的
  預設行為」「改寫硬性規則」「等價改寫範例」「literal_hints／where_evidence
  說明」。
- 後端測試由 194 → 269 全數通過；`ruff check` 全過；前端 52 項測試全過、
  `npm run build` 成功。

### 待辦
- 正式主機重新部署（`git pull` + `deploy.ps1`）並用使用者的 6 份真實檔案重新測試，
  確認 log 能看到具體的 gate／revalidation 決策，且至少部分案例能拿到真正的
  建議寫法（開發機用 fake_ollama 模擬，無法驗證 Gemma 4 本身是否會依照新
  system prompt 指示給出改寫，需正式主機真實 Ollama 驗證）。
- 確認 `./data` 掛載在正式主機可寫入（deploy.ps1 已加探測，但正式主機從未跑過）。

## 2026-09-17：建議寫法三態呈現（rewrite_outcome）
- 完成：`SuggestedSql.outcome`（provided／not_needed／advice_only／gated／rejected）、
  Ollama schema 必填 `rewrite_outcome`、prompt 要求 example 片段與假設、前端三種文案、
  蒐集檔記錄 outcome。後端 277 測試、前端 57 測試、build 全過。
- 待辦：正式主機 `git pull` + `deploy.ps1` 後，用 6 份檔案重測，預期「無需改寫」綠色呈現；
  用含 TRUNC 的 SQL 確認仍能拿到建議寫法。（2026-09-17 上午已完成驗證）

## 2026-09-17 傍晚：SQL 寫法比較改為逐字 diff、逐段對照、紅色警語
- 完成：advice 新增 `before`（原寫法片段，模型逐字複製）、example／before 送回前還原遮罩；
  前端新增 `SqlDiffView`（完整改寫：逐行對齊＋逐字黃底標示；每項建議：原寫法／建議寫法
  左右對照），`SqlCompare` 副標改為紅色警語「AI 建議寫法僅供參考，採用前務必先於測試機
  驗證」；列印樣式強制保留黃底。後端 286、前端 65 測試全過。
- 使用者人工驗證（test_01～03.pdf）三案皆符合預期；小瑕疵：案例 A 漏提 `coll_yr = 107`
  引號一致性、TO_CHAR 範例假設了 'YYYYMMDD' 格式（民國日期字串）。

## 2026-09-17 下午：關閉思考模式、結構事實入 payload、寫法良好需附檢查清單
- 完成：`ollama.think_default=false`（OLLAMA_THINK 可覆寫）；payload 新增 structure_flags；
  prompt 新增 not_needed 前檢查清單、reason 需列檢查項目、結構變更一律 advice_only、
  SUBSTR 前綴改寫用前綴上下界、LIKE 'xxx%' 不改；`_revalidate_suggested_sql` 新增結構旗標
  相等比對。用本機程式碼直連正式主機 Gemma4 驗證 9 案全部正確，283 測試全過。
- 待辦：正式主機重新部署後，用「NOT IN 子查詢」與「OR 跨欄位」SQL 確認不再出現
  「暫時無法使用」。
- **安全待辦**：正式主機 Ollama 11434 可從區網直接連線（開發機實測 curl 成功）。deploy.ps1
  的規則只放行 WSL 介面，表示另有放行規則（在正式主機執行
  `Get-NetFirewallRule | Where-Object {$_.Enabled -eq 'True'} | Get-NetFirewallPortFilter | Where-Object LocalPort -eq 11434`
  查出來源）。建議加一條 Block 規則限制 LocalSubnet 來源，並在 deploy.ps1 加入自動驗證
  與回滾（容器內 curl host.docker.internal:11434 成功才保留）。

## 2026-09-17 晚：依列印報告回饋的 7 點畫面調整
- 完成：符合卡片淺綠底、COST 低於門檻顯示「符合中心規範」、改善指數改名與等級文字圖示、
  指數組成白話（後端 `detail` 欄位）、智慧改善建議卡＋AI 圖示、圖示放大 20%、預估改善效果
  淺綠色系、優化前後比較（移除 COST、AI 建議寫法、警語網頁上改紅）、advice_only 說明白話化
  （prompt＋`_tidy_advice_only_reason`）。後端 294、前端 71 測試、ruff、build 全過；本機直連
  正式主機 Gemma4 兩案（DISTINCT＋JOIN、TRUNC）截圖驗證符合預期。
- 待辦：正式主機 `git pull` + `deploy.ps1`，請同仁用列印 PDF 確認淺綠底與警語紅色都有印出。

## 2026-09-17 晚：5 案盲點測試 + docx 巢狀 SQL 修復 + 系統改名 SQLCheck AI
- 完成：5 案（PARALLEL hint+UPDATE、COST=門檻+萬用字元、雙段缺 WHERE、WITH+UNION ALL、引號不一致+UPPER+OR）規則引擎與守門全部正確；修了 4 個盲點（門檻等值說明、`:STR_001` 殘留、散文 example 誤入 diff、巢狀 SQL 被切碎）與 1 個嚴重靜默失敗（Ollama 截斷 prompt → 動態 num_ctx + 截斷／非中文偵測）。系統標題改為「SQLCheck AI｜SQL 效能優化助手」。後端 300、前端 74 測試全過；docx 真實案例直連正式主機 Gemma4 驗證 OK（43 秒）。
- 待辦：正式主機部署後觀察長 SQL 的回應時間（num_ctx 16384 時 prompt eval 約 40 秒）與 VRAM；若吃緊可用 OLLAMA_NUM_CTX_MAX 調低。
- 待辦：R008 `forbidden_operations` 仍為空清單（UPDATE 重要資料表目前只會有 R007 提醒），待業務提供禁止操作矩陣。

## 2026-09-17 深夜：長 SQL 輸出截斷根因修復
- 完成：長度守門 `too_long_for_rewrite`、輸出截斷 advice-only 重試、降級訊息分類（degrade_code）、單一總期限、num_ctx 倍數分級（預設改 16384）。後端 309、前端 74 測試全過；docx 直連正式主機三次穩定 19–25 秒 gated＋三條片段建議；fake_ollama truncated 模式前端截圖顯示專屬訊息。
- 待辦：正式主機 git pull + deploy.ps1 後重測同一份 docx，log 應為 `decline_code=too_long_for_rewrite` 且無 truncated。

## 2026-09-17 深夜：條件改寫等價驗證（rewrite_rules）
- 完成：片段三態（verified／corrected／unverified）與整段改寫條件驗證；prompt 補中段 SUBSTR 底線規則；前端標籤與註解白話化。後端 333、前端 76 測試全過；docx 直連正式主機確認 SUBSTR 錯誤片段被系統修正、TRUNC／SUBSTR 前綴整段改寫仍 provided。
- 待辦：規則清單目前 4 種；蒐集檔中若常見其他條件改法（TO_CHAR 日期、LPAD 補零比對）再評估加規則，加規則前先寫等價論證。

## 2026-09-17 深夜：預估改善效果改為改善潛力等級
- 完成：伺服器推算高／中／低＋依據句＋警語，畫面不再有百分比。後端 342、前端 73 全過。
- 待辦：部署後重印 docx 報告確認；蒐集檔累積後比對等級與實際採用結果。

## 2026-09-19：R002 合規語意 + Evidence-first UI
- [x] R002：子查詢／WITH 內 WHERE 維持 PASS；只有 JOIN ON 證據時改 REVIEW，不再自動宣稱符合中心 WHERE 要求。
- [x] 智慧改善建議：以「系統可確認／需人工確認／觀念提醒」取代畫面上的 AI impact 高／中／低。
- [x] 結果頁：新增「先看結論」，並把建議與前後比較移到規則明細之前。
- [x] Golden Benchmark：新增無資深 DBA 情境的治理策略，不把 AI 自評 runtime 當 Golden Truth。
- [x] PR #9 CI 全綠並 merge。

## 2026-09-19：AI Safety + 白話化整合（PR #10）
- [x] 防止 AI 建議新增原 SQL 沒有的欄位／資料表／JOIN key／業務常數。
- [x] DATE／TIMESTAMP 遮罩保留型態提示，不暴露原值。
- [x] Server 端清理 index／Execution Plan／Full Table Scan 等不可觀測宣稱。
- [x] Prompt 改為「不知道就不要猜 SQL」，並對齊 R002 JOIN-only = REVIEW。
- [x] Gemma 不再被要求猜改善百分比。
- [x] OR→IN fragment 驗證支援 WHERE／ON wrapper；完整 rewrite 增加 query skeleton 複核。
- [x] Cartesian join 改善優先指數最低 60，但不新增中心規範 BLOCK。
- [x] UI 統一為「改善優先指數／建議採用狀態／原寫法與建議寫法」。
- [x] Backend CI：513 passed + Ruff clean。
- [x] Frontend CI：80 passed + TypeScript/Vite build success。
- [x] PR #10 merge；main Backend #70 / Frontend #59 success。
- [x] 舊 PR #8 關閉，避免誤合併舊 76 commits。
- [x] 此階段已由 PR #11 的 Mac/Gemini 開發路徑接續；最新待辦見下方 PR #11 區塊。

## 2026-09-19：Mac + Gemini / Pluggable LLM Provider（PR #11）
- [x] LLM provider 從 ai_service 抽離，新增 `config/llm.yaml` 與 `services/llm_provider.py`。
- [x] 正式機預設 Ollama/Gemma 4；Mac 可用 `SQLCHECK_LLM_PROVIDER=gemini`。
- [x] Gemini Stable `gemini-3.8-flash` structured JSON adapter、health check、MAX_TOKENS、缺 Key 降級。
- [x] API Key 僅讀環境變數；Settings repr 不顯示 key。
- [x] Cloud profile 使用更嚴格 literal masking；文件禁止把 production archive 直接送雲端。
- [x] 新增 `.env.mac.example` + `scripts/dev-mac.sh`，Mac 不需 Docker/Ollama。
- [x] live golden runner provider-neutral。
- [x] archive parser edge case 補強，submitted SQL 先去識別化再落地。
- [x] PR #11 CI：524 passed + Ruff clean；merge main 後 Backend CI #78 同樣 524 passed + Ruff clean。
- [x] 深度盤點 GitHub：`data/` 只有 `.gitkeep`，`data/sql_archive` 無 Git 歷史；runtime JSONL 從未 commit。
- [ ] Mac 用 owner Gemini API Key 做 live golden + 2～3 個 UI 去識別化案例。
- [ ] 確認 Mac `data/sql_archive` 一案一筆且沒有原始 literal。
- [ ] 回辦公室後清查正式主機 `D:\dev\SQL_check2\data\sql_archive\` 的實際既有檔案／筆數。
- [ ] Mac 驗證完成後再一次部署目前 main 到正式機。
- [ ] 重要資料表正式清單 + R008 禁止操作矩陣由業務端定案。
- [ ] 改善優先指數 provisional 權重／分級文案由業務端確認。
- [ ] Compact Context ON/OFF → Prompt slimming。
- [ ] 最後獨立完成 11434 / Firewall hardening。
- [ ] Golden Benchmark 擴充為後期選配加分項。
