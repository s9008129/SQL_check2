# SQLCheck AI — Current Project Status

> 更新日期：2026-09-20  
> 本文件只保留「現在」的專案狀態。早期開發過程與歷史決策請看 `tasks/lessons.md` 與歷史報告。

## Current baseline

- Main product：SQLCheck AI
- Frontend：React / TypeScript
- Backend：FastAPI / Python 3.12
- Formal model：Gemma 4 31B via Ollama
- Compliance authority：deterministic rule engine
- AI role：白話說明與建議，不決定 compliance 或 semantic equivalence
- Oracle connection：none
- Execution Plan：not in current scope
- Current score name：**改善指數**

## Closed decisions

- [x] Cloud privacy：維持目前 Balanced policy；不新增 Strict Mode。
- [x] SQL Archive retention：維持現況；不新增自動 purge。
- [x] R008：實務沒有重要資料表禁止操作；保留 R007 reminder，R008 正式停用。
- [x] 改善指數：名稱確認為「改善指數」；既有權重、分級與演算法正式定版。
- [x] Ollama 11434 Firewall hardening：由專案 owner 人工處理，不再列入本專案 backlog。
- [x] Execution Plan：暫緩，現階段不開發。

## Current recurring verification

一般 PR：

- Backend pytest
- Ruff
- Frontend tests / build（有 frontend 變更時）
- Deploy CI（有 deploy 變更時）

AI / Prompt / masking / model / rewrite governance 有重大變更時：

- GitHub Actions → **Manual Live Cloud E2E**
- 先跑 `smoke`
- 封板或高風險變更再跑 `full`

這個 workflow 是手動啟動，不會每個 PR 自動消耗 Ollama Cloud API。

## Documentation maintenance

文件狀態統一看：

- `docs/document-status.md`

CURRENT 文件要保持與 main 一致；HISTORICAL 文件保留當時內容，不再拿來當現行需求。

## Operational items

以下屬部署 / 維運工作，不是未完成產品功能：

- 正式主機需要更新版本時，由維運人員執行 `deploy/deploy.ps1`。
- 正式主機 Firewall / Ollama 11434 由專案 owner 人工維護。
- `data/sql_archive/` 為 runtime archive，不提交 Git。
- 真實 Browser / Native Print evidence 只在 UI / 列印有重大變更時重新驗收。

## Future ideas — not active backlog

下列項目只有在 owner 重新開案後才進入開發：

- Execution Plan / runtime evidence
- Strict privacy mode
- 新的 R008 類禁止規範
- 自動 archive retention / purge
- 新的 verified rewrite pattern

目前沒有需要先行實作的上述項目。
