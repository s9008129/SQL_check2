# SQLCheck AI — 第三方審查與後續實作建議（2026-09-17）

> 本文件是第三方 Code Review / 產品審查意見，不直接修改正式程式碼。
> 建議由 Claude Code 在此 PR 分支上審查、評估、實作，再由第三方重新 Review。

## 1. 本輪審查目的

本輪針對兩大面向：

1. **前端 Dashboard / 視覺化呈現**：是否符合 Apple 式簡潔、淺色、現代、資訊圖卡導向，讓非技術使用者一眼看懂。
2. **Gemma 4 31B SQL 建議品質**：是否出現過度改善、假改善、太保守、或長 SQL / 24GB VRAM 情境下不穩定的問題。

本 PR **不要求一次把所有建議都實作**。請先 Review 本文件，再由 Implementation Agent 依風險與成本分批修改。

---

## 2. 目前整體判斷

目前架構方向正確，不建議重構：

- 規則引擎負責明確合規判定。
- Gemma 4 31B 負責白話解釋與改善建議。
- Python 後端再次驗證 AI 改寫，不直接信任模型。
- 長 SQL 採逐段改善，而非強迫模型整段重寫。
- `think=false`、單一 Ollama concurrency、動態 `num_ctx` 都應保留。

前端視覺已接近目標，但仍有少數可改善的人因細節。

---

## 3. 建議實作優先序

### P0 — 正式使用前優先確認

#### P0-1 Ollama 11434 不應讓一般區網直接存取

現有 E2E 紀錄指出正式主機的 Ollama `11434` 曾可由其他區網主機直接連線。

這會繞過 SQLCheck 的：

- 規則引擎
- SQL 遮罩
- AI Prompt Policy
- Rewrite Validation
- 稽核 / Archive 流程

**建議：**

- 確認 Windows Firewall / Ollama 綁定狀態。
- 只允許 SQLCheck 所需的本機 / Docker-to-host 存取。
- 不要讓一般 LAN Client 直接呼叫 Ollama API。
- 修改 deploy 流程前，務必設計 rollback。

**驗收：**

- SQLCheck Container 可以正常呼叫 Ollama。
- 同網段另一台電腦不能直接連 `11434`。
- 部署後自動檢查此條件。

---

### P1 — 建議近期改善

#### P1-1 「改善指數」不要再受 AI 主觀 impact 直接加分

目前改善指數包含：

- 規則發現
- SQL 結構
- COST 接近門檻
- AI impact（low / medium / high）

第一性原理問題：Gemma 看不到實際 Oracle 統計資訊、Index、Execution Plan、資料量，因此它可以合理判斷「值得留意」，但無法可靠判斷真正的效能 impact 是 high / medium / low。

**建議方向：**

- 0–100 的「改善指數」改成完全 deterministic。
- AI impact 可以保留在建議卡片做參考，但不要再回灌改善指數。
- 若仍需 AI 訊號，請以「是否有已驗證的可改寫片段」等伺服器可確認事實取代模型主觀分數。

**驗收：**

- 同一 SQL 在相同規則設定下，改善指數不因模型回覆差異而改變。
- AI 不可用時，改善指數與正常情況仍一致。

---

#### P1-2 「改善潛力」不應只因 NOTICE 就自動升到中

目前只要有 NOTICE，可能就得到「改善潛力：中」。

但 NOTICE 有些只是治理提醒，例如：

- 使用重要資料表
- 請確認查詢範圍

這不等於真的存在中等效能改善空間。

**建議方向：**

將兩種概念分開：

- 治理 / 稽核提醒 → 影響「檢視優先度」
- 已確認有實際 SQL 寫法可改善 → 影響「改善潛力」

**改善潛力升級依據建議：**

- 有經 deterministic rewrite rule 驗證成功的片段。
- 有通過整段 rewrite revalidation 的建議。
- 有明確可改善的結構特徵，且不是純治理提醒。

重要資料表 NOTICE 不應單獨把改善潛力升為中。

---

#### P1-3 規則權重仍標示 provisional，建議用真實 SQL 校準

目前 `rules.yaml` 中改善指數權重仍屬 provisional。

**不要用主觀感覺調分。**

建議蒐集至少 30–50 支真實、去識別化 SQL，由人工 DBA / 系統人員標註：

- 目前良好
- 建議改善
- 優先改善

再比較系統分數與人工判斷，校準權重。

**驗收：**

- 建立可重跑的 golden dataset。
- 權重修改前後能產生對照報告。
- 不因單一特殊 SQL 過度調整整體模型。

---

### P2 — UI / UX 微調

#### P2-1 中尺寸畫面四張摘要卡建議改成 2×2，不要 3+1

目前 Desktop 4 欄是好的；中尺寸 breakpoint 若變成 3 欄，四張卡會形成 3+1，視覺失衡。

**建議：**

- Desktop：4 欄
- 中尺寸：2×2
- Mobile：1 欄或 2×2 再降 1 欄

不要為了這項需求改變整體 Dashboard 結構。

---

#### P2-2 大面積紅色應保留給「明確不符合」

目前 AI advice 的 high impact 會使用紅色系背景。

對非技術使用者而言，紅色大面積容易被理解為「SQL 寫錯 / 違規」，但 AI high impact 只代表模型認為值得優先看，不等於違反中心規範。

**建議視覺語意：**

- 明確符合：綠
- 一般資訊 / COST：藍
- 提醒：黃 / 琥珀
- 明確不符合：紅
- AI 建議：紫或中性色
- AI impact：用小 badge、左側細色條或 icon 表達，不用整張紅底

---

#### P2-3 評估「改善指數」與「改善潛力」是否容易混淆

一般使用者可能不容易理解：

- 改善指數 68 / 100
- 改善潛力：中

兩者的差異。

**建議先做使用者觀察，不必立刻改。**

若同仁確實混淆，可考慮：

- 「改善指數」→「檢視優先度」
- 「改善潛力」維持原名

讓語意變成：

- 現在是否值得優先檢視？
- 採用改善後大概值不值得？

---

## 4. Gemma 4 31B 建議品質 — 必須保留的現有設計

以下設計目前是正確方向，除非有明確新證據，**不要為了增加建議數量而放寬**：

### 4.1 Clean SQL 可以 0 項建議

不要為了讓畫面看起來「AI 有做事」而硬湊通用建議。

### 4.2 `not_needed / advice_only / provided / gated / rejected` 三態以上分類要保留

使用者必須能分辨：

- 沒有必要改
- 有方向但需要業務假設
- 有可參考完整改寫
- 系統因長度 / 結構不允許完整改寫
- AI 改寫未通過安全複核

### 4.3 Python Rewrite Validation 必須保留

AI 不是語意等價判定的最終權威。

模型提出的：

- TRUNC
- SUBSTR
- NVL
- 同欄位 OR → IN

等改寫，應持續由 deterministic rewrite rule 驗證。

無法證明結果不變的改法，只能 advice-only。

### 4.4 不得讓 AI 宣稱觀測不到的 Oracle 事實

持續禁止：

- 已使用 / 未使用索引
- Full Table Scan
- Execution Plan 實際結果
- 實測快多少
- 改善後 COST

除非未來真的接測試資料庫並取得實際資料，否則不得放寬。

---

## 5. RTX 4090 24GB / 長 SQL 最佳實踐

### 5.1 保留 `think=false`

目前實測已證明 Gemma 開啟 thinking 會把大量 output token 花在內部推理，導致正式 JSON 被截斷。

本系統是結構化 Review 任務，且後面已有 deterministic validation，因此維持 `think=false`。

### 5.2 保留單一 Ollama concurrency

24GB VRAM 不建議同時跑多個 31B inference。

目前 `Semaphore(1)` 是合理選擇。

### 5.3 保留動態 Context，而不是固定最大 Context

建議維持：

- default `num_ctx = 16384`
- 必要時升到 `32768`
- 只有長 SQL 才升級

不要所有請求都固定 32K。

### 5.4 長 SQL 不要強迫整段重寫

如果完整 rewrite 預估無法塞入 `num_predict`：

- 保留 summary
- 最多 2–3 個具體片段
- before / after
- 明確指出為何不整段重寫

不要用無限制提高 `num_predict` 來解決。

### 5.5 建議建立正式主機簡易效能基準表

不需要做進產品 UI，只需維運測試：

| SQL 類型 | num_ctx | 回應時間 | VRAM 峰值 | 是否 CPU offload |
|---|---:|---:|---:|---|
| 短 SQL | 16K |  |  |  |
| 中 SQL | 16K |  |  |  |
| 長 SQL | 32K |  |  |  |

若 Context 拉高後速度突然大幅下降，優先確認是否發生 CPU offload，而不是先調 Prompt。

---

## 6. Prompt 後續策略

目前 system prompt 已很長。

後續不要持續無限制加入規則。

原則：

- 能由 Python 確定判斷 → 放 Python
- AI 只處理：白話說明、有限建議、必要假設、結構化輸出

未來若要縮短 Prompt：

1. 先保留現在版本作 baseline。
2. 建立 Golden Dataset。
3. 精簡 Prompt 後 A/B 比較。
4. 品質沒有退化才採用。

不要直接大幅刪除現行 Prompt。

---

## 7. Claude Code Review / Implementation 指示

請 Claude Code **先做 Review，不要直接全部修改**。

建議依下列順序：

1. 檢查本文件每一項是否與目前 main 實作一致。
2. 對每一項標示：
   - Agree
   - Partially Agree
   - Disagree
   - Already Fixed
3. 說明理由與可能副作用。
4. 先提出 Implementation Plan。
5. 使用者確認後才修改。
6. 每個 P1 / P2 項目盡量拆成小 Commit。
7. 每個修改都必須補測試或更新既有測試。
8. 不得降低 AI rewrite 的安全守門。
9. 不得新增 Oracle 連線。
10. 不得新增應用資料庫。

---

## 8. 建議驗證清單

實作後至少重跑：

### Backend

```bash
uv run pytest
uv run ruff check .
```

### Frontend

```bash
npm run test
npm run build
```

### 真實 Gemma E2E

至少包含：

1. 乾淨 SQL → 不應硬湊建議。
2. TRUNC / NVL / SUBSTR 等安全改寫 → 應能提出具體建議。
3. NOT IN / 跨欄位 OR / DISTINCT / GROUP BY 等可能改變語意情境 → 應保守，只給方向。
4. 重要資料表純提醒 → 不應被誤解成一定有中高改善潛力。
5. 長 SQL → 不應因完整 rewrite 導致 JSON output truncation。
6. Ollama 不可用 → 規則結果仍完整可用。

---

## 9. 本 PR 的角色分工

- **ChatGPT**：第三方整合者 / Code Reviewer / 架構與產品品質檢查。
- **Claude Code**：主要 Implementation Agent，負責程式修改、測試與 Commit。
- **使用者**：決定需求、確認業務規則、正式主機部署與實機驗證。

建議工作流：

```text
ChatGPT 提 Review / PR
        ↓
Claude Code Review PR
        ↓
Claude Code 提 Implementation Plan
        ↓
使用者確認
        ↓
Claude Code 在同一 PR branch 實作 + Commit
        ↓
ChatGPT 再 Review Diff
        ↓
使用者正式主機測試
        ↓
確認後 Merge
```

這樣可以避免單一模型同時「提出方案、寫程式、自己驗收自己」。
