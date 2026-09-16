# SQLCheck 2.0 正式主機部署指南

本文件說明 `deploy.ps1` 一鍵部署腳本的行為、參數、憑證信任設定，以及常見問題排除。
適用對象：在正式主機（Windows 11 + Docker Desktop + Windows 原生 Ollama）上執行部署的操作人員，
不需要具備開發背景即可依本文件操作。

架構背景（詳見專案根目錄 `README.md`）：正式環境**只有一個** Docker Container
（`sqlcheck-app`），內含 FastAPI + 規則引擎 + 已建置的 React 靜態檔；Ollama／Gemma 4
執行於 Windows Host（不進容器），容器透過 `host.docker.internal:11434` 呼叫。對外只開放
HTTPS 443（自簽憑證），不使用 Nginx 或任何反向代理，不建立資料庫。

---

## 目錄

1. [執行前準備](#執行前準備)
2. [如何執行](#如何執行)
3. [參數與開關](#參數與開關)
4. [deploy.ps1 執行步驟說明](#deployps1-執行步驟說明)
5. [讓同仁的瀏覽器信任自簽憑證](#讓同仁的瀏覽器信任自簽憑證)
6. [常見問題與排除](#常見問題與排除)
7. [回復（Rollback）與關閉（Down）](#回復rollback與關閉down)
8. [單獨執行 smoke-test.ps1](#單獨執行-smoke-testps1)
9. [記錄檔](#記錄檔)
10. [去識別化 SQL 蒐集檔](#去識別化-sql-蒐集檔)

---

## 執行前準備

- Windows 11，且已安裝：
  - **Docker Desktop**（`docker` CLI 可用）
  - **Ollama for Windows**（`ollama` CLI 可用），且已執行過 `ollama pull gemma4:31b`
    （或您實際要用的模型標籤）下載好模型
  - **PowerShell 7 以上**（`pwsh`）
- 以**系統管理員身分**執行 PowerShell（設定防火牆規則、使用者層級環境變數需要提權）。
- 本機防火牆已開通、可連上區網（供同仁瀏覽器存取 443）。

---

## 如何執行

```powershell
cd deploy
.\deploy.ps1
```

請確認是在「以系統管理員身分執行」的 PowerShell 7 (pwsh) 視窗中執行。若您的執行原則
(Execution Policy) 擋下腳本，可改用：

```powershell
pwsh -ExecutionPolicy Bypass -File .\deploy.ps1
```

首次部署會需要下載/建置映像檔、產生憑證，可能耗時數分鐘，請耐心等候，腳本會持續印出進度。

---

## 參數與開關

| 參數 | 型別 | 預設值 | 說明 |
|---|---|---|---|
| `-CheckOnly` | switch | (關閉) | 只執行 Preflight 檢查並印出通過/失敗摘要，**不做任何變更**（不啟動 Docker Desktop、不動防火牆、不動 `.env`/憑證、不建置或啟動容器）。開發機沒有 Docker，只能用這個模式確認腳本邏輯本身正常。 |
| `-SkipBuild` | switch | (關閉) | Step 6 略過重新建置，直接用現有映像檔執行 `docker compose up -d`。適合「只是重啟容器、程式碼沒有變更」的情境。（例外：若映像檔完全不存在且憑證尚未產生，Step 5 仍會先建置一次，否則無法產生憑證。） |
| `-Rollback` | switch | (關閉) | 停止目前容器，回復到上一次部署時標記的 `sqlcheck-app:prev` 映像檔並重新啟動。 |
| `-Down` | switch | (關閉) | 執行 `docker compose down` 後結束，不做其他任何事。 |
| `-ProductionIp` | string | `10.97.15.58` | 正式主機的區網 IP。會寫入憑證的 SAN（讓瀏覽器用這個 IP 連線時憑證有效），部署完成後也會用這個位址自動開啟瀏覽器。 |
| `-OllamaModel` | string | `gemma4:31b` | 正式主機上應已安裝的 Ollama 模型標籤。會寫入 `.env` 的 `OLLAMA_MODEL`，也是 Preflight 檢查 `ollama list` 時要找的模型名稱。 |
| `-DockerRemoteAddress` | string | `172.16.0.0/12` | 找不到 `vEthernet (WSL*)` 介面時，Ollama（11434）防火牆規則改用的來源位址範圍 (CIDR)。實際範圍依 Docker Desktop 的網路模式而異，如有需要請調整此參數後重新執行。 |

`-CheckOnly`、`-Rollback`、`-Down` 三者是互斥的操作模式：同時給多個時，`-Down` 優先於
`-Rollback`，`-Rollback` 優先於一般部署流程；一般不需要同時使用。

---

## deploy.ps1 執行步驟說明

一般部署（未加 `-Rollback` / `-Down`）依序執行以下 6 個步驟：

### Step 1/6：Preflight 檢查
- 確認以系統管理員身分執行。
- 確認 `docker` CLI 存在，且 `docker info` 有回應；若引擎未回應，會嘗試啟動 Docker Desktop
  並每 5 秒輪詢一次，最多等待約 3 分鐘。
- 確認 `ollama` CLI 存在，且 `ollama list` 的輸出包含 `-OllamaModel` 指定的模型；若找不到，
  會印出目前已安裝的模型清單，並提示執行 `ollama pull <模型名稱>`，接著**中止部署**
  （不會自動幫您下載一個可能高達 20GB 的模型）。
- 加上 `-CheckOnly` 時，做完以上檢查就印出摘要結束，不會往下執行。
- 一般部署（未加 `-CheckOnly`）若有任何一項未通過，同樣會在此中止，不會產生任何副作用。

### Step 2/6：設定 Ollama 對外監聽（`OLLAMA_HOST`）
- Ollama 預設只聽 `127.0.0.1:11434`，但 Docker 容器要透過 `host.docker.internal` 呼叫，
  必須改成監聽 `0.0.0.0:11434`。
- 腳本會檢查使用者層級環境變數 `OLLAMA_HOST` 是否已經等於 `0.0.0.0:11434`；**已經是的話就
  完全不動**，不會覆蓋您原本的自訂設定，也不會重啟 Ollama。
- 需要變更時，腳本會設定該環境變數，然後停止現有的 Ollama process（`ollama` /
  `ollama app`），接著**請您自行**從「開始」功能表或系統匣重新啟動 Ollama（一般使用者身分）
  ——腳本刻意不從提權的視窗直接啟動 Ollama，避免用錯誤的使用者身分產生重複/衝突的 Ollama
  執行個體。
- 腳本會每 3 秒輪詢一次 `http://127.0.0.1:11434/api/tags`，最多等待 60 秒讓 Ollama 重新上線，
  上線後再次確認模型仍然存在。逾時或模型消失都會中止部署並印出明確訊息。

### Step 3/6：設定 Windows 防火牆規則
建立兩條防火牆規則（皆為冪等：已存在同名規則就略過，可重複執行）：

- **`SQLCheck - Ollama API (container only)`**（TCP 11434，Inbound）：
  依 PRD §46「Windows Firewall 應限制 11434 不對一般區網任意開放」，**刻意縮小開放範圍**，
  只讓 Docker 容器能連上 Ollama。優先綁定 Docker Desktop 的 `vEthernet (WSL*)` 介面；找不到
  該介面時（例如 Docker Desktop 改用 Hyper-V 網路模式）改用 `-DockerRemoteAddress` 限制來源
  位址範圍。**這條規則不應該、也不會對一般區網開放。**
- **`SQLCheck - HTTPS (LAN)`**（TCP 443，Inbound，Profile: Domain, Private）：
  這條才是要給同仁瀏覽器連線用的，刻意排除 Public 設定檔。如需進一步限縮來源網段，可自行
  執行 `Set-NetFirewallRule -DisplayName 'SQLCheck - HTTPS (LAN)' -RemoteAddress <您的CIDR>`。

若建立防火牆規則失敗（例如公司原則限制），腳本只會印出警告並繼續，不會中止整個部署——
但請務必依警告訊息手動確認防火牆設定，否則同仁可能連不上服務。

### Step 4/6：準備 `.env`
若 `.env` 不存在，複製 `.env.example` 為 `.env`，並把其中的 `OLLAMA_MODEL=...` 換成
`-OllamaModel` 參數的值（其餘內容原封不動）。**若 `.env` 已存在則完全不覆寫**——後續重新
部署不會動到您手動調整過的設定（例如 `OLLAMA_TIMEOUT_SECONDS`、`OLLAMA_NUM_CTX`）。

### Step 5/6：TLS 憑證
若 `.\certs\sqlcheck.crt` 已存在則略過（憑證有效期約 825 天，不需要每次部署都重簽）。
不存在時：

1. 若映像檔 `sqlcheck-app:latest` 尚未存在，先執行 `docker compose build`（首次需下載
   base image 與套件，可能需要數分鐘；此步驟不受 `-SkipBuild` 影響，因為沒有映像檔就無法
   產生憑證）。
2. 以一次性的 `docker run --rm -v <專案>\certs:/certs sqlcheck-app:latest python -m
   app.certgen --out-dir /certs --host <ProductionIp> --host <本機電腦名稱>` 產生憑證
   （`127.0.0.1` / `localhost` 一律會自動加入，不需另外指定）。刻意不用 `docker compose run`：
   `docker-compose.yml` 對執行中的服務是以**唯讀**方式掛載 `./certs`（執行期安全設定），
   一次性的產生步驟必須用可寫入的掛載才寫得出檔案。輸出的 `sqlcheck.crt` / `sqlcheck.key` /
   `sqlcheck.cer` 會落在正式主機的 `.\certs\` 目錄。
3. 用 `certutil -addstore Root .\certs\sqlcheck.cer` 把憑證匯入**正式主機本機**的信任清單，
   讓主機自己（以及在主機上開瀏覽器測試）不會看到憑證警告。這一步失敗只會印出警告，不會
   中止部署——但代表您需要手動處理，見下一節。

### Step 6/6：建置映像檔並啟動容器
- 未加 `-SkipBuild` 時：先把目前的 `sqlcheck-app:latest`（如果有）標記為 `sqlcheck-app:prev`
  作為復原點，再執行 `docker compose up -d --build`。
- 加了 `-SkipBuild` 時：直接執行 `docker compose up -d`，不重新建置、不建立新的復原點。
- 每 3 秒輪詢 `https://localhost/api/health`（略過憑證檢查），最多等待 90 秒，直到收到
  HTTP 200。
  - 回應中 `ai_available: true` 代表容器可正常連線 Ollama。
  - `ai_available: false` 只會印出**警告**，不會判定部署失敗——依 PRD 設計，決定性規則檢查
    本來就應該在 AI／Ollama 無法連線時仍正常運作。請參考下方〈`ai_available:false`〉排除。
- 執行 `.\smoke-test.ps1` 並印出結果。
- 全部通過時自動開啟瀏覽器連到 `https://<ProductionIp>/`；smoke test 未通過時則不自動開啟，
  但仍會印出網址供您手動檢查。

---

## 讓同仁的瀏覽器信任自簽憑證

`deploy.ps1` 只會把憑證匯入**正式主機本機**的信任清單（`certutil -addstore Root`）。
其他同仁在自己電腦的瀏覽器連到 `https://10.97.15.58/` 時，**仍然會看到「不安全」／
憑證不受信任的警告**，除非他們各自的電腦也信任這張憑證。有兩種方式：

### 方式一：同仁自行手動匯入（適合少數人）
1. 向操作人員索取 `certs\sqlcheck.cer` 檔案（可透過內部檔案分享，這不是機密檔案）。
2. 雙擊該檔案 → 「安裝憑證」→ 選擇「本機電腦」（需要系統管理員權限）→
   「將所有憑證放入以下的存放區」→ 瀏覽選擇「受信任的根憑證授權單位」→ 完成。
3. 或用管理員 PowerShell/命令提示字元執行：`certutil -addstore Root <路徑>\sqlcheck.cer`
4. 重新啟動瀏覽器後再次連線即可。

### 方式二：由 IT 單位透過群組原則 (GPO) 統一推送（適合較多使用者）
1. 將 `sqlcheck.cer` 放到網域控制站可存取的共用位置。
2. 於「群組原則管理主控台」建立/編輯 GPO：
   `電腦設定 → 原則 → Windows 設定 → 安全性設定 → 公開金鑰原則 → 受信任的根憑證授權單位`，
   匯入 `sqlcheck.cer`。
3. 將該 GPO 連結到涵蓋同仁電腦的 OU，待原則更新（或 `gpupdate /force`）後即可自動信任。

憑證有效期約 825 天（依 `certgen.py` 預設），到期前需重新產生並重新分發／推送給同仁。

---

## 常見問題與排除

### Ollama 模型未安裝（Preflight 或 Step 2 失敗，提示找不到模型）
- 確認實際已安裝的模型名稱：`ollama list`。
- 若模型標籤與 `-OllamaModel`／`.env` 的 `OLLAMA_MODEL` 不一致（例如標籤打錯字），請以
  `.\deploy.ps1 -OllamaModel <正確標籤>` 重新執行，或直接下載對應模型：
  `ollama pull gemma4:31b`（模型可能高達數十 GB，請確認網路與磁碟空間足夠）。

### 部署成功但 `ai_available: false`（健康檢查顯示 AI 不可用）
決定性規則檢查仍可正常使用，但 AI 輔助複核／改善建議會停用。依序檢查：
1. **`OLLAMA_HOST` 是否真的是 `0.0.0.0:11434`**：`[System.Environment]::GetEnvironmentVariable('OLLAMA_HOST','User')`。
   若不是，重新執行 `deploy.ps1`（Step 2 會自動修正並引導您重啟 Ollama）。
2. **Ollama 是否真的在跑、且模型存在**：在主機瀏覽器開
   `http://localhost:11434/api/tags` 應該要能看到 JSON 內含您的模型。
3. **防火牆規則是否誤擋**：確認 `SQLCheck - Ollama API (container only)` 規則存在
   （`Get-NetFirewallRule -DisplayName 'SQLCheck - Ollama API (container only)'`），且其
   `-InterfaceAlias`／`-RemoteAddress` 範圍與您實際的 Docker Desktop 網路模式相符——網路模式
   變更（例如 WSL2 ↔ Hyper-V 切換）可能導致原本設定的介面/網段失效，此時需要手動調整或刪除
   該規則後以 `-DockerRemoteAddress` 重新指定範圍讓 `deploy.ps1` 重建。
4. **`.env` 的 `OLLAMA_BASE_URL`**：應為 `http://host.docker.internal:11434`，且不應指向
   公用／區網位址（PRD 要求瀏覽器不得直接呼叫 Ollama，只能透過 SQLCheck 容器轉呼叫）。
5. 檢查容器記錄：`docker compose logs sqlcheck`（在專案根目錄執行，或見下方）。

### 443 埠已被占用（`docker compose up` 失敗、或健康檢查一直連不上）
1. 確認是哪個程式佔用：`Get-NetTCPConnection -LocalPort 443 -State Listen` 或
   `netstat -ano | findstr :443`，再用 `Get-Process -Id <PID>` 對應出程式名稱。
2. 常見衝突來源：IIS 預設網站、其他已在跑的 Web 服務、其他 Docker 容器。
3. 停用/移除衝突的服務或容器後，重新執行 `docker compose up -d`（或整個
   `.\deploy.ps1 -SkipBuild`）。

### Docker Desktop 未啟動／未回應
- `deploy.ps1` 會自動嘗試啟動並輪詢最多 3 分鐘；若仍失敗，請手動開啟 Docker Desktop，
  確認左下角引擎狀態為「Running」（非 "Starting..."）後再重新執行腳本。
- 若持續失敗，檢查 Docker Desktop 本身的診斷紀錄（工作列圖示 → Troubleshoot）。

### 容器啟動但健康檢查一直過不了
- `docker compose logs sqlcheck`（於專案根目錄，即 `deploy` 的上一層執行）查看實際錯誤。
- 確認 `.\certs\sqlcheck.crt`／`sqlcheck.key` 兩個檔案都存在且非空（若憑證產生中途失敗，
  可能只留下部分檔案）；必要時刪除 `.\certs\` 目錄下的檔案後重新執行 `deploy.ps1` 讓它
  重新產生。

---

## 回復（Rollback）與關閉（Down）

### 回復到上一版
```powershell
.\deploy.ps1 -Rollback
```
會停止目前容器，並把上一次部署時標記的 `sqlcheck-app:prev` 映像檔重新標記為 `:latest`
後啟動。**只有先前成功執行過一次「未加 `-SkipBuild`」的部署，`sqlcheck-app:prev` 才會存在**；
若沒有可回復的映像檔，腳本會清楚印出訊息並以非 0 結束碼結束，不會有任何動作。

若需要連同 `OLLAMA_HOST` 環境變數一併還原，需自行手動處理，例如：
```powershell
[System.Environment]::SetEnvironmentVariable('OLLAMA_HOST', $null, 'User')
```
（移除後 Ollama 會回復預設只監聽 `127.0.0.1`，需自行重啟 Ollama 生效。）

### 直接關閉服務
```powershell
.\deploy.ps1 -Down
```
等同於在專案根目錄執行 `docker compose down`，停止並移除容器，不做其他任何事
（不動防火牆規則、不動 `.env`、不動憑證、不動 `OLLAMA_HOST`）。

---

## 單獨執行 smoke-test.ps1

`smoke-test.ps1` 會在 `deploy.ps1` 的 Step 6 自動執行，也可以隨時單獨執行，用來快速確認
服務目前是否正常（不需要系統管理員權限）：

```powershell
cd deploy
.\smoke-test.ps1
# 或指定其他位址：
.\smoke-test.ps1 -BaseUrl https://10.97.15.58
```

會依序檢查：
1. `GET /api/health` 回應 200 且 `status` 為 `"ok"`。
2. `POST /api/analyze`（帶 `include_ai:false` 的已知正常範例 SQL）回應 200 且
   `compliance.status` 為 `"PASS"`——這一項刻意不依賴 AI／Ollama，用來確認規則引擎本身
   （不受 Ollama 狀態影響）運作正常。

全部通過印出 `Smoke test: 全數通過 (ALL PASSED)` 並以結束碼 0 結束；任一項失敗則印出
`[FAIL]` 明細並以非 0 結束碼結束，方便寫進排程/監控腳本判斷。

---

## 記錄檔

每次執行 `deploy.ps1`（含 `-CheckOnly`／`-Rollback`／`-Down`）都會透過 `Start-Transcript`
把完整輸出寫到 `deploy\logs\deploy-<時間戳記>.log`（資料夾不存在會自動建立；此目錄已列在
`.gitignore`，不會被提交進版本控制）。回報問題或請他人協助排除時，請一併附上對應的記錄檔。

---

## 去識別化 SQL 蒐集檔

2026-09-16 新增：系統會把每一次「有勾選 AI 建議」（`include_ai=true`）的檢核結果，以
去識別化後的內容寫入 JSON Lines 檔案，存放在主機的 `D:\dev\SQL_check2\data\sql_archive\`
（容器內對應 `/data/sql_archive`，`docker-compose.yml` 已掛載為讀寫 volume），每月一個檔
案，例如 `sql_archive-2026-09.jsonl`。目的是日後可以把大量 SQL 交給 AI 或人工做離線分析、
統計、找出常見的改善模式。

**不會**寫入的內容：申請單號、原始 SQL 常數值（字串、日期、身分證字號等一律先去識別
化）、附件檔名、任何使用者或 IP 資訊——見 `backend/app/services/sql_archive.py` 與
`backend/app/services/masking.py` 的 `deidentify_sql()`。

每一行是一筆獨立的 JSON 物件，主要欄位：`sql_deidentified`（去識別化後的 SQL）、
`sql_fingerprint`（SQL 結構指紋，可用來找出重複送出的相似查詢）、`compliance`／`rules`／
`findings`（規則引擎結果）、`improvement`（改善優先指數）、`ai`（AI 摘要建議標題、
影響程度、是否提供建議寫法、預估改善幅度——同樣去識別化）。

**如何停用**：在 `.env` 設定 `SQLCHECK_ARCHIVE_ENABLED=false` 後重新 `docker compose up -d`
即可完全停止寫入（不需要重新建置映像檔）。

**如何讀取分析**（PowerShell 範例，逐行印出 SQL 指紋與改善指數）：

```powershell
Get-Content .\data\sql_archive\sql_archive-2026-09.jsonl | ForEach-Object {
    $r = $_ | ConvertFrom-Json
    "$($r.sql_fingerprint)  score=$($r.improvement.score)  compliance=$($r.compliance.status)"
}
```

或用 Python／pandas：`pandas.read_json("data/sql_archive/sql_archive-2026-09.jsonl", lines=True)`。

部署腳本 Step 6/6 會先探測 `.\data` 資料夾是否可寫入；若無法寫入只會印出警告，不會中止
部署（蒐集檔功能失效不影響網頁與 SQL 檢核本身）。
