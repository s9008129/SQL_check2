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
- [ ] Phase 8 硬化、lint、todo Results、lessons
- [x] Verify：`uv run pytest`（186 通過）、`uv run ruff check`（無錯誤）、`tsc --noEmit`（無錯誤）、`npm run test`（52 通過）、`npm run build`（成功）、Playwright E2E（三種解析度手動驅動通過）；PS 語法檢查（3 個腳本皆 0 錯誤）

## Risk & Rollback
- 風險：中（新系統、部署腳本改動正式主機 Ollama 綁定與防火牆）。
- 回滾：`deploy.ps1 -Rollback`（回前版映像）、`-Down`；Ollama 環境變數可手動移除。

## Dependencies & Environment
- Python 3.12 / uv、Node 22；Docker 僅正式主機；OLLAMA_MODEL=gemma4:31b-it-qat。

## Working Notes
- 開發機無 Docker/Ollama：AI 測試用 respx + scripts/fake_ollama.py。
- sqlglot hint 只在 SELECT 後成為 exp.Hint → R003 用 token 層判定。
- 建議寫法回傳前還原遮罩。

## Working Notes（持續更新）
- certgen.py 的 SAN 清單務必包含 127.0.0.1（loopback IP），Dockerfile HEALTHCHECK 以憑證釘選（cafile=/certs/sqlcheck.crt）方式驗證，不停用 TLS 驗證。
- deploy.ps1 的 `Set-OllamaHostBinding` 用 `Get-Process -Name 'ollama*','ollama app'` 嘗試停止 Windows Ollama 行程；正式主機上 Ollama 系統匣程式的實際 process name 未經現場確認，若停止失敗腳本只會靜默略過（不阻斷部署），正式部署時請留意 Step 2 的輸出，必要時手動結束該行程。
