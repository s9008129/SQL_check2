# SQLCheck 2.0 正式主機部署指南

目前部署流程已拆成兩支腳本，避免日常應用程式更新被 Windows Firewall / Ollama Host
基礎設施設定卡住。

## 1. 日常正式部署：deploy.ps1

`deploy/deploy.ps1` 是現在的預設部署入口。

它只處理 SQLCheck 應用程式：

- 確認 Git branch / working tree
- `git fetch origin --prune`
- `git pull --ff-only origin main`
- 保留既有 `.env`
- 建立 `sqlcheck-app:prev` rollback point
- `docker compose build sqlcheck`
- 只重建 `sqlcheck` service
- 驗證 `/api/health`
- 執行 `smoke-test.ps1`
- 驗證失敗時自動 rollback

### deploy.ps1 刻意不做

它不會：

- 新增、修改或刪除 Windows Firewall rule
- 修改 TCP 11434 規則
- 修改 `OLLAMA_HOST`
- 停止或重新啟動 Ollama
- 修改 Windows 網路設定
- 匯入 Windows Trusted Root

因此，一般程式碼 / Skill / Pattern Catalog / Prompt / Frontend 更新應優先使用這支腳本。

---

## 2. 基礎設施與 Firewall：deploy-infra.ps1

舊版含完整 Windows Firewall / Ollama Host 設定的部署腳本已保留為：

`deploy/deploy-infra.ps1`

它包含：

- `OLLAMA_HOST=0.0.0.0:11434`
- Windows Firewall 11434 audit / validate / create / verify
- HTTPS 443 rule
- 既有 fail-closed / BreakGlassFirewall 流程

這支腳本目前不屬於日常部署流程。

只有在專案最後進行正式主機 security hardening、11434 範圍收斂、Docker Desktop
網路模式驗證時才使用。

不要為了更新 SQLCheck 程式碼而執行 `deploy-infra.ps1`。

---

## 3. 正式主機建議流程

正式主機預設路徑：

`D:\dev\SQL_check2`

第一次使用新版部署流程前：

```powershell
cd D:\dev\SQL_check2

git status --short
git switch main
git pull --ff-only origin main
```

若 `git status --short` 有任何輸出，先不要 reset / stash / pull；先確認本機修改來源。

拉到最新版後，先做唯讀檢查：

```powershell
pwsh -NoProfile -File .\deploy\deploy.ps1 -CheckOnly
```

正式部署：

```powershell
pwsh -NoProfile -File .\deploy\deploy.ps1 -SkipPull -RequireAi
```

因為前一步已手動 `git pull`，使用 `-SkipPull` 可避免重複 fetch / pull。

若希望腳本自己更新 Git，也可以直接：

```powershell
pwsh -NoProfile -File .\deploy\deploy.ps1 -RequireAi
```

腳本只允許 fast-forward pull，不會自動 merge / rebase。

---

## 4. 重要參數

| 參數 | 用途 |
|---|---|
| `-CheckOnly` | 唯讀檢查，不修改 Git / .env / container |
| `-SkipPull` | 不執行 git fetch / pull |
| `-SkipBuild` | 使用現有 `sqlcheck-app:latest` |
| `-Rollback` | 使用 `sqlcheck-app:prev` 回復 |
| `-Down` | `docker compose down` |
| `-ExpectedCommit <SHA>` | 部署前鎖定預期版本 |
| `-KnowledgeContextMode keep` | 不修改 Context env 設定 |
| `-KnowledgeContextMode on` | 設 `SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED=true` |
| `-KnowledgeContextMode off` | 設 `SQLCHECK_KNOWLEDGE_CONTEXT_ENABLED=false` |
| `-MigrateLegacyNumCtx` | 將既有 `OLLAMA_NUM_CTX=8192` 備份後更新成 16384 |
| `-RequireAi` | `ai_available=false` 時視為部署失敗 |
| `-NoAutoRollback` | 失敗後保留新版，不自動回復 |

---

## 5. Compact Context A/B

正式主機測試 Pattern Catalog Compact Context 時，不需要改程式碼。

Context ON：

```powershell
pwsh -NoProfile -File .\deploy\deploy.ps1 -SkipPull -SkipBuild -KnowledgeContextMode on -RequireAi
```

Context OFF：

```powershell
pwsh -NoProfile -File .\deploy\deploy.ps1 -SkipPull -SkipBuild -KnowledgeContextMode off -RequireAi
```

兩者都會重建 SQLCheck container，讓新的 `.env` 值確實生效。

建議使用同一組 golden SQL 比較：

- SUBSTR canonical LIKE
- same-column OR -> IN <= 1000
- TRUNC advice-only
- NVL advice-only
- NOT IN / NULL semantics
- 乾淨 SQL 不硬湊建議

---

## 6. Rollback

一般部署前，`deploy.ps1` 會優先把「目前正在執行中的 container image」標記成：

`sqlcheck-app:prev`

這比直接標記 `sqlcheck-app:latest` 更可靠，因為 latest tag 可能已被 build 覆蓋。

人工 rollback：

```powershell
pwsh -NoProfile -File .\deploy\deploy.ps1 -Rollback
```

健康檢查或 smoke test 失敗時，預設也會自動 rollback。

---

## 7. Health / Smoke Test

部署完成至少確認：

```powershell
Invoke-RestMethod https://localhost/api/health -SkipCertificateCheck
```

應看到：

- `status = ok`
- 若正式 AI 測試要求完整可用：`ai_available = true`

單獨執行 deterministic smoke test：

```powershell
pwsh -NoProfile -File .\deploy\smoke-test.ps1 -BaseUrl https://localhost
```

Smoke test 刻意使用 `include_ai:false`，用來確認 API 與規則引擎不依賴 Ollama 也能正常工作。

---

## 8. TLS

若 `certs/sqlcheck.crt` 與 `certs/sqlcheck.key` 已存在，日常部署完全保留。

若不存在，`deploy.ps1` 會使用剛 build 的 SQLCheck image 執行 `app.certgen` 產生 cert/key。

App-only deploy 不會自動匯入 Windows Trusted Root。

同仁端憑證信任 / GPO 推送屬基礎設施工作，與日常應用程式部署分開管理。

---

## 9. Windows Firewall / Ollama 11434

目前正式機 10.97.15.58 的 Firewall / 11434 hardening 是已知、延後的獨立工作。

日常 `deploy.ps1` 不會因此失敗，也不會嘗試修正。

核心程式完成後，再使用 `deploy-infra.ps1` 與主機實測完成：

1. container -> `host.docker.internal:11434` 成功
2. `/api/health` -> `ai_available:true`
3. 第二台 LAN 電腦 -> `10.97.15.58:11434` 失敗
4. Windows Firewall 規則來源範圍明確限制

在那之前，不要使用 `-BreakGlassFirewall` 來繞過日常部署問題；日常部署直接使用
App-only `deploy.ps1`。

---

## 10. CI

Deployment scripts 有獨立 GitHub Actions：

`.github/workflows/deploy-ci.yml`

它會：

- 用 Windows PowerShell Parser 檢查 PowerShell 語法
- 驗證 App-only deploy 不含 Firewall / OLLAMA_HOST mutation
- 驗證 rollback / ff-only / smoke / context mode 等必要安全邊界
- 保留原有 firewall helper regression tests

正式 merge 前，Deploy Script CI 必須綠燈。

---

## 11. Logs

每次 App-only deploy 會寫：

`deploy/logs/deploy-app-YYYYMMDD-HHMMSS.log`

此目錄已由 Git 忽略。

問題回報時，請附：

- `git rev-parse HEAD`
- `docker compose ps`
- `/api/health`
- 最新 `deploy-app-*.log`
- 必要時 `docker compose logs --tail=150 sqlcheck`
