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
（`backend/tests/golden/run_golden.py`，需真實 Ollama，開發機無法執行）。

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
- 開發機無 Docker/Ollama：AI 測試用 respx + scripts/fake_ollama.py。
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
