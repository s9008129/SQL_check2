# SQLCheck AI 文件狀態總覽

> 更新日期：2026-09-22  
> 目的：避免舊 PRD、舊 E2E 報告或交接文件被誤當成目前系統規格。

## 判讀原則

文件分成三類：

- **CURRENT**：目前仍應維護，可用來理解現行系統。
- **REFERENCE**：仍有參考價值，但不是產品現況的唯一依據。
- **HISTORICAL**：保留作為當時的設計、測試或決策紀錄；內容可能已被後續版本取代。

若文件彼此衝突，優先順序為：

```text
現行程式碼 / config
    >
AGENTS.md 與 skills/sqlcheck-oracle-review/
    >
現行 README / 系統簡易說明 / deploy 文件
    >
REFERENCE 文件
    >
HISTORICAL 文件
```

## CURRENT — 現行文件

| 文件 | 狀態 | 用途 |
|---|---|---|
| `docs/document-status.md` | CURRENT | 全專案文件新舊狀態與判讀入口。 |
| `README.md` | CURRENT | 專案首頁；只保留意圖、目標、簡易安裝與簡易架構。 |
| `SQLCheck2_系統架構與設計簡易說明.md` | CURRENT | 非技術人員的現行系統說明與已結案決策。 |
| `AGENTS.md` | CURRENT | Coding Agent / 開發者工作規範。 |
| `deploy/README-deploy.md` | CURRENT | 正式主機部署操作；Firewall 11434 已改為 owner 人工維運，不列專案待辦。 |
| `tasks/todo.md` | CURRENT | 只記錄目前狀態、已結案決策與真正仍有效的工作。 |
| `data/README.md` | CURRENT | E2E artifact 與 runtime data 目錄規範。 |
| `backend/tests/golden/README.md` | CURRENT | Golden runner 與 Live provider 驗證方式。 |
| `docs/golden-benchmark-strategy.md` | CURRENT | Golden Benchmark 治理策略。 |
| `skills/sqlcheck-oracle-review/SKILL.md` | CURRENT | SQL 改寫 / optimization knowledge 的治理入口。 |
| `skills/sqlcheck-oracle-review/references/project-boundaries.md` | CURRENT | Authority、Oracle/DBA 與 runtime 邊界。 |
| `skills/sqlcheck-oracle-review/references/safe-rewrites.md` | CURRENT | 可驗證改寫治理。 |
| `skills/sqlcheck-oracle-review/references/advice-only-patterns.md` | CURRENT | 只能提供方向的 pattern。 |
| `skills/sqlcheck-oracle-review/references/forbidden-claims.md` | CURRENT | AI / agent 禁止宣稱的內容。 |
| `skills/sqlcheck-oracle-review/references/methodology.md` | CURRENT | Detect → Classify → Verify → Explain 方法。 |
| `docs/sql-developer-execution-plan.md` | CURRENT | SQL Developer 執行計畫證據使用說明（測試機證據層）。 |
| `docs/frontend-visual-storytelling-v2.md` | CURRENT | SQLCheck 前端資訊層級、視覺語言與 responsive / accessibility 實作規格。 |

## REFERENCE — 仍可參考，但不是現況唯一依據

| 文件 | 狀態 | 說明 |
|---|---|---|
| `docs/sql-optimization-skill-applicability.md` | REFERENCE | 外部 sql-optimization skill 與本專案的適用性研究；治理結論仍以 Pattern Catalog / Skill 為準。 |
| `docs/mac-gemma4-validation-cases.md` | REFERENCE | 5 個人工 synthetic 驗證案例；目前已有永久 Manual Live Cloud E2E，可優先用 GitHub Actions。 |
| `tasks/lessons.md` | REFERENCE | 累積式工程 lessons / 決策歷程；不應把早期「待辦」文字當成目前 backlog。 |

## HISTORICAL — 歷史快照，不再代表目前規格

以下文件保留是為了追溯「當時為什麼這樣做」，不應用來覆蓋現行程式或 CURRENT 文件。

| 文件 | 狀態 | 說明 |
|---|---|---|
| `SQLCheck2_PRD_v6_AI_Estimated_Improvement.md` | HISTORICAL | v6 Draft 初始 PRD；仍包含「改善優先指數」、AI 改善百分比、完全 stateless 等已被後續決策取代的內容。 |
| `SQLCheck2_dashboard_prototype_v4.html` | HISTORICAL | 初始畫面 Prototype；現行 React UI 已多次調整。 |
| `SQLCheck2.0_系統設計簡易說明.pdf` | HISTORICAL | 舊版 PDF 快照；以現行 Markdown 簡易說明為準。 |
| `Handoff.md` | HISTORICAL | 舊階段交接快照；不是目前待辦清單。 |
| `20260919_audit_report.md` | HISTORICAL | 2026-09-19 當時稽核報告。 |
| `20260919_audit_report_R2.md` | HISTORICAL | 2026-09-19 第二版稽核報告。 |
| `E2E_test_report.md` | HISTORICAL | 舊 E2E 測試報告。 |
| `E2E_TEST_report_20260917.md` | HISTORICAL | 2026-09-17 E2E 快照。 |
| `E2E_TEST_report_20260917_round2.md` | HISTORICAL | 2026-09-17 E2E 第二輪快照。 |
| `SQLCheck2_E2E_test_report_20260916.md` | HISTORICAL | 2026-09-16 E2E 快照。 |
| `SQLCheck2_E2E_test_report_20260917.md` | HISTORICAL | 2026-09-17 E2E 快照。 |
| `review/2026-09-17_sqlcheck_ai_ui_review_plan.md` | HISTORICAL | 當時 UI review plan；現行 UI 已後續修改。 |
| `.agent/tasks/T20260919-1758-rewrite-ux/plan.md` | HISTORICAL | 單一任務執行計畫。 |
| `.agent/tasks/T20260919-1758-rewrite-ux/execution.md` | HISTORICAL | 單一任務執行紀錄。 |
| `.agent/tasks/T20260919-1758-rewrite-ux/handoff.md` | HISTORICAL | 單一任務交接紀錄。 |
| `.agent/tasks/T20260919-1758-rewrite-ux/cloud-pr-review-prompt.md` | HISTORICAL | 當時 PR review prompt。 |
| `.agent/tasks/T20260919-1758-rewrite-ux/e2e/attempt-01/e2e_report.md` | HISTORICAL | 該任務第一次 E2E 報告。 |
| `.agent/tasks/T20260919-1758-rewrite-ux/review/attempt-01/plan_snapshot.md` | HISTORICAL | 該次 review 的 plan snapshot。 |
| `.agent/tasks/T20260919-1758-rewrite-ux/review/attempt-01/review_report.md` | HISTORICAL | 該次 review report。 |

## 2026-09-20 已結案決策

下列項目不再列為 backlog：

- **Cloud privacy**：維持目前 Balanced policy，不新增 Strict Mode。
- **SQL Archive retention**：維持現況，不新增自動 purge。
- **R008 禁止操作矩陣**：實務沒有禁止操作；保留 R007 重要資料表提醒，R008 正式停用。
- **改善指數**：現行 UI 正式名稱確認為「改善指數」；既有權重、分級與演算法正式定版。
- **Ollama 11434 Firewall hardening**：由專案 owner 人工處理，專案不再追蹤。
- **Execution Plan**：2026-09-20 暫緩；2026-09-22 由 owner 重新開啟，範圍限定為「使用者主動從測試機 Oracle SQL Developer 提供的執行計畫證據」。仍不連 Oracle、不推論正式機行為、不改變 compliance 與「改善指數」。目前實作見 `docs/sql-developer-execution-plan.md`。

## Live Cloud E2E 現行做法

永久 workflow：`.github/workflows/live-cloud-e2e.yml`

它**不會每次 PR 自動執行**。需要時到 GitHub Actions 手動按 Run workflow：

- `smoke`：較快，跑 live golden cases，適合一般 AI/prompt 調整後確認。
- `full`：較完整，約 59 次 live analyze，適合模型、masking、AI guard、rewrite governance 等重大變更後封板。

白話說，就是：

> 平常用便宜、穩定的自動測試；真的改到 AI 核心時，再手動按一次「用真正 Gemma 跑完整體檢」。

這樣能保留真實模型驗證，又不讓每個 README 或 CSS 修改都浪費雲端 API。
