# SQLCheck 2.0

地方稅自撰 SQL 的「規範檢核 + 改善優先指數 + 智慧改善建議 + 建議寫法對照」工具。

- 產品需求：[`SQLCheck2_PRD_v6_AI_Estimated_Improvement.md`](./SQLCheck2_PRD_v6_AI_Estimated_Improvement.md)
- 視覺雛形：[`SQLCheck2_dashboard_prototype_v4.html`](./SQLCheck2_dashboard_prototype_v4.html)
- 非技術人員簡易說明：[`SQLCheck2_系統架構與設計簡易說明.md`](./SQLCheck2_系統架構與設計簡易說明.md)
- 實作計畫：`tasks/todo.md`（含目前進度）、`tasks/lessons.md`（開發過程中的重要發現）

## 架構總覽

正式環境只有**一個** Docker Container（`sqlcheck-app`），內含 FastAPI + 規則引擎 +
已建置的 React 靜態檔；正式機仍使用 Windows Host 上的 Ollama／Gemma 4，容器透過
`host.docker.internal:11434` 呼叫。AI 連線已抽成 provider adapter：Mac 開發環境可透過 Gemini API 代管
**Gemma 4 31B IT**，與正式機的 Ollama `gemma4:31b` 對齊模型家族與推理設定；
規則引擎、遮罩、改寫複核與前端不需要跟著改。系統**不**連任何資料庫（含 Oracle）。

```
瀏覽器 --HTTPS(443)--> [sqlcheck-app 唯一容器]
                          FastAPI + React 靜態檔 + 規則引擎 + 改善優先指數
                          |
                          v (host.docker.internal:11434)
                       Windows 原生 Ollama --> Gemma 4 31B
```

## 開發機環境（不需要 Docker）

需求：Node.js 22+、Python 3.12、[`uv`](https://docs.astral.sh/uv/)。

### Mac + Gemini API（推薦的遠端開發方式）

Mac 不需要安裝 Ollama 或任何地端模型。LLM 供應商由
`backend/app/config/llm.yaml` 選擇，API Key 只放在本機 `.env`：

```bash
git pull
cp .env.mac.example .env
# 編輯 .env，填入 GEMINI_API_KEY

bash scripts/dev-mac.sh
```

啟動後：

- 網頁：`http://127.0.0.1:5173`
- API Health：`http://127.0.0.1:8000/api/health`
- Vite 會把 `/api` proxy 到 FastAPI，不需要 CORS 設定。
- **Gemini API 只是雲端傳輸／代管服務，實際模型不是 Gemini 3.x，而是
  `gemma-4-31b-it`**，用來對照正式機 `gemma4:31b`。
- Parity profile 同步對齊：temperature=0.2、max output=3072、context tier=16384/32768、
  地端 `think=false` 對應 API `GEMINI_THINKING_LEVEL=minimal`，以及相同的短 ASCII masking 規則。
- 因 parity 模式會保留與地端相同的短代碼／LIKE 樣式，Mac 雲端驗證**只能使用 synthetic 或
  已去識別化 SQL**；不要把正式機 production archive 或原始案件 SQL 直接送到雲端。

### 單獨跑測試

```bash
cd backend
uv sync --group dev
uv run pytest -q
uv run ruff check app tests

cd ../frontend
npm ci
npm run test -- --run
npm run build
```

若要在 Mac 直接跑 live golden cases：

```bash
cd backend
SQLCHECK_LLM_PROVIDER=gemini \
GEMINI_API_KEY="..." \
uv run python tests/golden/run_golden.py -v
```

Windows 開發機仍可使用 `scripts/dev.ps1` 與 `scripts/fake_ollama.py`。

## LLM Provider 設定

LLM 連線集中在 `backend/app/config/llm.yaml`，目前內建：

| Provider | 用途 | 憑證 |
|---|---|---|
| `ollama` | 正式機／地端 Gemma 4 | 不需要 API Key |
| `gemini` | Mac 開發；Gemini API 代管 `gemma-4-31b-it` | `GEMINI_API_KEY` 環境變數 |

切換只需 `SQLCHECK_LLM_PROVIDER=ollama|gemini`。供應商 HTTP 格式都封裝在
`backend/app/services/llm_provider.py`；未來新增其他模型服務時，不應改動規則引擎。

**API Key 不得寫入 `llm.yaml`、程式碼、測試案例或 Git。**

## 正式主機部署（Windows 11 + RTX 4090 + Docker Desktop + Ollama）

**一鍵部署**（PowerShell，以系統管理員身分執行）：

```powershell
cd deploy
./deploy.ps1
```

日常 `deploy.ps1` 只處理應用程式：Git fast-forward 更新、保留 `.env`、建立 rollback image、
build／recreate SQLCheck container、TLS、health 與 smoke test。它**不會**修改 Windows Firewall、
`OLLAMA_HOST` 或 Ollama process；11434／Firewall 最後另用 `deploy/deploy-infra.ps1` 驗收。
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
| 真實模型輸出品質 | 🟡 已設定 Gemini API / `gemma-4-31b-it` parity，待本機 API Key live 跑 | 🟡 最新版待正式機 `gemma4:31b` + `run_golden.py` 驗收 |
| 一鍵部署腳本完整流程 | 只能 `-CheckOnly` | ✅ |

### SQL 蒐集檔在哪裡

使用者按下 AI 檢核（`include_ai=true`）後，系統會把**去識別化後**的 SQL 與檢核結果寫入
`data/sql_archive/*.jsonl`。這個目錄刻意被 `.gitignore` 排除，所以蒐集資料**不會自動出現在
GitHub Repo**；正式機與 Mac 各自保留自己的 runtime archive。若未來要集中分析，應以安全的
去識別化匯出流程彙整，不要直接把 production archive commit 到 Git。

## 重要設計原則（不得在後續修改中破壞）

1. 正式環境維持單一 Docker Container；Ollama 不進容器。開發環境可不用 Docker，LLM provider 可抽換。
2. 不建立任何應用資料庫，不保存任何「可識別」的案件資料：申請單號、原始 SQL、附件檔名
   一律不落地。**例外（2026-09-16，使用者明確決定）**：`backend/app/services/
   sql_archive.py` 會把去識別化後的 SQL、規則結果、AI 建議寫入 `data/sql_archive/*.jsonl`
   （申請單號／原始常數值一律不寫入），供後續離線分析用途。蒐集檔位置與 Git 邊界見上方
   「SQL 蒐集檔在哪裡」；可用 `SQLCHECK_ARCHIVE_ENABLED=false` 完全停用。
3. 不連財政資訊中心 Oracle，不取得 Execution Plan／Index／實際資料。
4. 規則引擎（`backend/app/services/rule_engine.py`）是唯一決定「符合／不符合中心規範」的地方；
   AI provider 只負責白話解釋與建議，不能決定合規、改善優先指數或宣稱實測效能。
5. AI 不得聲稱資料庫實際行為（索引、全表掃描、Execution Plan），也不得捏造改善後 Oracle COST。

詳細規則與理由見 PRD 文件開頭「§0 Coding Agent 必須先理解的產品決策」。
