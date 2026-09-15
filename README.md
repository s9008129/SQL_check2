# SQLCheck 2.0

地方稅自撰 SQL 的「規範檢核 + 改善優先指數 + 智慧改善建議 + 建議寫法對照」工具。

- 產品需求：[`SQLCheck2_PRD_v6_AI_Estimated_Improvement.md`](./SQLCheck2_PRD_v6_AI_Estimated_Improvement.md)
- 視覺雛形：[`SQLCheck2_dashboard_prototype_v4.html`](./SQLCheck2_dashboard_prototype_v4.html)
- 非技術人員簡易說明：[`SQLCheck2_系統架構與設計簡易說明.md`](./SQLCheck2_系統架構與設計簡易說明.md)
- 實作計畫：`tasks/todo.md`（含目前進度）、`tasks/lessons.md`（開發過程中的重要發現）

## 架構總覽

正式環境只有**一個** Docker Container（`sqlcheck-app`），內含 FastAPI + 規則引擎 +
已建置的 React 靜態檔；Ollama／Gemma 4 執行於 Windows Host，容器透過
`host.docker.internal:11434` 呼叫。系統**不**連任何資料庫（含 Oracle），**不**保存任何案件資料。

```
瀏覽器 --HTTPS(443)--> [sqlcheck-app 唯一容器]
                          FastAPI + React 靜態檔 + 規則引擎 + 改善優先指數
                          |
                          v (host.docker.internal:11434)
                       Windows 原生 Ollama --> Gemma 4 31B
```

## 開發機環境（本機開發與測試 — 不需要 Docker／Ollama）

需求：Node.js 22+、Python 3.12、[`uv`](https://docs.astral.sh/uv/)。

```bash
# 後端
cd backend
uv sync --group dev
uv run pytest -q          # 單元測試
uv run ruff check app tests

# 前端
cd ../frontend
npm install
npm run build              # 產生 dist/，供整合測試 / Docker build 使用
npm run test                # vitest
```

本機整合測試（後端服務前端 build 結果 + 假 Ollama，無需 Docker／真實 Ollama）：
見 `scripts/dev.ps1` 與 `scripts/fake_ollama.py`。

## 正式主機部署（Windows 11 + RTX 4090 + Docker Desktop + Ollama）

**一鍵部署**（PowerShell，以系統管理員身分執行）：

```powershell
cd deploy
./deploy.ps1
```

腳本會自動：檢查 Docker Desktop／Ollama、設定 `OLLAMA_HOST` 並重啟 Ollama、
設定僅限容器來源的防火牆規則、產生自簽 HTTPS 憑證、建置並啟動容器、執行健康檢查。
詳見 [`deploy/README-deploy.md`](./deploy/README-deploy.md)。

`docker compose build` 只能在正式主機（可連網際網路）執行——開發機沒有 Docker，
Dockerfile／docker-compose.yml 在開發機只能做語法層級的靜態檢查。

## 已驗證 / 待正式主機驗證

| 項目 | 開發機 | 正式主機 |
|---|---|---|
| 後端單元測試、ruff | ✅ `uv run pytest`、`uv run ruff check` | — |
| 前端型別檢查、單元測試、build | ✅ `tsc --noEmit`、`npm run test`、`npm run build` | — |
| 本機整合（假 Ollama）+ E2E | ✅ | — |
| Docker 映像建置與啟動 | ❌ 開發機無 Docker | ✅ |
| 真實 Gemma 4 輸出品質 | ❌ | ✅ `backend/tests/golden/run_golden.py` |
| 一鍵部署腳本完整流程 | 只能 `-CheckOnly` | ✅ |

## 重要設計原則（不得在後續修改中破壞）

1. 單一 Docker Container；Ollama 不進容器。
2. 不建立任何應用資料庫，不保存任何案件資料（申請單號／SQL／COST／AI 建議一律不落地）。
3. 不連財政資訊中心 Oracle，不取得 Execution Plan／Index／實際資料。
4. 規則引擎（`backend/app/services/rule_engine.py`）是唯一決定「符合／不符合中心規範」的地方；
   AI 只負責白話解釋、建議、建議寫法、預估效能改善幅度。
5. AI 不得聲稱資料庫實際行為（索引、全表掃描、Execution Plan），也不得捏造改善後 Oracle COST。

詳細規則與理由見 PRD 文件開頭「§0 Coding Agent 必須先理解的產品決策」。
