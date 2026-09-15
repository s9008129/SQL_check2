# 2026-09-15 SQLCheck 2.0 建置

## 目標 / 驗收
- 依 PRD v6 + Prototype v4 建立單一容器的 SQLCheck 2.0（FastAPI + React + 規則引擎 + Ollama/Gemma 4）。
- 開發機完成所有可完成的測試；正式主機一鍵部署 `deploy/deploy.ps1`（HTTPS 443、自簽憑證）。
- 詳細計畫：C:\Users\ca0283\.claude\plans\must-use-rpd-best-use-lively-cupcake.md

## Checklist
- [ ] Phase 0 骨架（backend uv 專案、frontend Vite、Dockerfile/compose/.env.example/.gitignore/README）
- [ ] Phase 1 Parser + 規則引擎 + 改善優先指數 + 單元測試
- [ ] Phase 2 附件擷取 + SQL 辨識 + fixtures
- [ ] Phase 3 AI service（masking、schema、守門、降級）+ fake_ollama
- [ ] Phase 4 API + run.py + certgen + API 測試
- [ ] Phase 5 前端元件、樣式、列印、響應 + vitest
- [ ] Phase 6 本機整合 E2E（Playwright 1366/1920）
- [ ] Phase 7 deploy.ps1 / smoke-test.ps1 / README-deploy.md
- [ ] Phase 8 硬化、lint、todo Results、lessons
- [ ] Verify：uv run pytest、ruff、tsc、vitest、npm run build、E2E、PS 語法檢查

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
