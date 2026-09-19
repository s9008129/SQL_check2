# SQLCheck PR #17 雲端模型獨立審查 Prompt

你是 SQLCheck 專案的獨立 Senior Code Reviewer。請對以下 Pull Request 做
**read-only、evidence-based、要求導向**的審查。請直接檢查 repository 與
PR diff，不要只接受 commit message 或本 prompt 的結論。不要修改檔案、
不要 merge、不要 deploy。

## PR 基準資料

- Repository: `s9008129/SQL_check2`
- PR: `#17`
- PR URL: https://github.com/s9008129/SQL_check2/pull/17
- Base: `main`
- Baseline `origin/main`: `11e6f1cb5ae93fdb8827c3aea6fe109b87512fe1`
- Deterministic rewrite prerequisite:
  `bce4f6104eaba78790cffbc925c520f15a4ceb37`
- 該 prerequisite 不在 main，已經 cherry-pick。
- Cherry-pick 後起始 SHA:
  `23a2af748887750102b7db748620e3dba211ebb1`
- 實作 commit:
  `91bba6ff16a48e99d7beb86cf1c339d3c69cc024`
- 後續 legacy advice terminology cleanup commit:
  `007f0c27705837555b5049ebe10aebf991fcde00`
- 請先確認 PR 現在的 head SHA、OPEN 狀態與 GitHub CI，再開始結論。

## 審查目標

判斷 PR 是否完整且安全地完成：

1. 修正 deterministic rewrite 與 AI fragment 的重複顯示。
2. 將 rewrite/advice 狀態改成清楚且在畫面與列印/PDF 中可見的文案。
3. 將中心規範檢核簡化為三個使用者可見結果：`符合`、`建議`、`不符合`。
4. 提供足夠 regression coverage，且 PR CI 綠燈。

## 不可違反的語意邊界

若 PR 破壞以下任一 invariant，至少列為 P0/P1 finding：

- formal authority 順序仍為 `rule_engine.py` > `rewrite_rules.py` >
  knowledge catalog > AI。
- 不得改變 compliance calculation 或 improvement score calculation。
- 不得改變 `rules.yaml` semantics、Ollama/Ollama Cloud、archive format、
  `important_tables` business config、deployment scripts 或 R008 matrix。
- deterministic verified rewrite whitelist 只能包含：
  - same-column equality OR -> IN
  - SUBSTR equality -> canonical LIKE
- TRUNC、NVL、TO_CHAR、leading wildcard、cross-column OR、DISTINCT/JOIN
  structural changes 必須維持 advice-only。
- 不得把 unsafe/rejected concrete SQL 重新暴露給使用者。
- 不得把 backend `RuleStatus` 的 REVIEW 改成 NOTICE，也不得改變 backend
  compliance status 或其計算。

## 必查一：verified_rewrites authority 與 duplicate regression

檢查 `frontend/src/App.tsx` 與
`frontend/src/components/SqlCompare.tsx`：

- App 是否原值傳遞 `result.verified_rewrites`，沒有用 `?? []` 把
  `undefined` 壓成空陣列。
- `verified_rewrites !== undefined` 時，是否只渲染 deterministic verified
  fragments，包括明確的 `[]`。
- 必須明確區分 `undefined` 與 `[]`：前者代表舊 backend contract、可使用 legacy AI fallback；後者代表新 backend 已完成檢查且沒有 deterministic rewrite，不得用 `?? []` 混淆兩者。
- `verified_rewrites === undefined` 時，是否只允許 legacy backend payload
  使用 AI verified/corrected fragment fallback。
- 是否移除以 raw before/after 字串作為主要架構的 `mergeSegments()` dedupe。
- 是否仍保留必要的 legacy defensive filtering，且不會讓 unverified
  concrete SQL 進入 diff。
- 測試是否證明：
  - deterministic 與換行不同的 AI verified item 只有一個 FragmentDiff；
  - comma whitespace 不同也只有一個 FragmentDiff；
  - undefined 仍使用 legacy fallback；
  - [] 不會由 AI fragment 偽造 deterministic diff。

## 必查二：rewrite/advice copy 與安全狀態

確認 active UI 與 tests 使用下列 exact copy：

- verified/corrected badge：`可使用此改寫`
- verified visible explanation：`系統已確認：這個改法不會改變查詢結果。`
- unverified/advice-only badge：`需先確認再改`
- informational badge：`僅供參考`
- diff badge：`查詢結果不變`
- compare explanation：`系統已確認這個改法不會改變查詢結果。`
- right diff label：`改後寫法`
- original label：`原寫法`
- hero：`先看中心規範結果，再看改善建議與改寫對照。`

確認 active rendered path 不會顯示：

- `可採用`
- `結果相同`
- `改後寫法（結果相同）`
- `已提供結果相同的改寫，可參考上方「改寫對照」。`

確認 verified explanation 不是 tooltip-only，且 print CSS 不會把它隱藏。

檢查 `backend/app/prompts/sql_review_zh_tw.txt` 對 verified deterministic
advice 是否只要求解釋「改了什麼」與「為什麼較容易閱讀」，並禁止重複：

- `結果相同`
- `查詢結果相同`
- `已確認`
- `可採用`
- `可使用此改寫`

同時確認 prompt 修改沒有放寬任何 AI safety rule。

## 必查三：三態 ComplianceTable presentation

確認 presentation-only mapping：

- PASS -> `符合`（綠色）
- NOTICE -> `建議`（黃色）
- REVIEW -> `建議`（黃色）
- BLOCK -> `不符合`（紅色）
- NA -> 不 render row

確認：

- ComplianceTable 只呈現「檢核項目」與「結果」兩欄。
- 不 render `未發現`、`已設定`、`目前無需調整`。
- 不 render舊的 resolved annotation。
- evidence/note 仍保留在 API/data contract。
- NOTICE 與 REVIEW 在 backend 仍 distinct。
- 沒有引入第四種使用者可見狀態。

## 必查四：header count 與 SummaryCards

確認 dashboard header 與 top summary card 使用：

- all pass -> `全部符合`
- NOTICE + REVIEW > 0 -> `N 項建議`
- BLOCK + suggestions -> `N 項不符合 · M 項建議`
- BLOCK only -> `N 項不符合`

確認 summary card 不顯示 `提醒`、`需確認`，也沒有改變 backend
compliance status 或 calculation。

## 必查五：Print/PDF contract

檢查 `frontend/src/styles/print.css` 與 print tests：

- `系統已確認：這個改法不會改變查詢結果。` 在 print/PDF media 中可見。
- `查詢結果不變` 在 print/PDF media 中可見。
- simplified ComplianceTable 的 item/status 仍可見。
- full SQL details 與 copy button 仍 hidden in print。
- 關鍵 verification meaning 不依賴 HTML title/tooltip。

若沒有真正 saved PDF evidence，請列為 residual risk；不要把它誤判成
code defect，也不要把未執行的檢查寫成 PASS。

## 必查六：Backend regression 與 scope

確認 PR 沒有改 deterministic behavior，且重跑/保留：

- OR same-column -> IN
- SUBSTR -> canonical LIKE
- cross-column OR -> no verified rewrite
- TRUNC -> no verified rewrite
- NVL -> no verified rewrite
- TO_CHAR -> no verified rewrite
- leading wildcard -> no verified rewrite
- AI unavailable 保留 `verified_rewrites`
- `include_ai=false` 保留 `verified_rewrites`
- prompt non-duplication wording test

確認不能出現 `不可採用` 這種未授權 concrete SQL state。

## 必查七：Tests / CI / delivery

檢查實際 CI，而非只相信 summary：

- Backend CI
- Frontend CI
- PR 是否仍 OPEN、沒有 merge
- PR head 是否是實際審查的 commit

若可在 checkout 工作樹執行：

```bash
TMPDIR=/private/tmp uv run pytest -q
uv run ruff check app tests
cd frontend && npm test -- --run
cd frontend && npm run build
```

若 macOS default temp path 重現 `/var` 與 `/private/var` 差異，請先判斷
是否為環境既有問題；不要弱化安全測試或修改無關 static-path tests。

## Finding 規則

只報告可由 code、test、CI 或可重現 evidence 支持的問題，不要報告純風格
偏好，也不要因實作方式和 prompt 不同就直接判定錯誤。

- P0：安全、資料正確性、authority 被破壞，或核心結果失真。
- P1：明確違反 acceptance 或核心 regression。
- P2：非核心但值得本 PR 修正的 correctness/maintainability 問題。
- P3：低風險改善；沒有實質風險時不要列。

每個 finding 必須包含：

1. severity（P0/P1/P2/P3）
2. exact file and line（以 PR head 為準）
3. 問題描述
4. 違反哪一條 acceptance/invariant
5. 具體修正方向
6. 證明問題的 evidence

## 固定輸出格式

請使用以下格式：

```markdown
# PR Review Result

Verdict: APPROVE | REQUEST_CHANGES | COMMENT
Reviewed PR: #17
Reviewed head: <full SHA>
CI status: <backend/frontend status>

## Findings

| Severity | Location | Finding | Acceptance / invariant | Suggested fix |
|---|---|---|---|---|
| P1 | path:line | ... | ... | ... |

若沒有 finding，明確寫：`No blocking findings.`，不要為了填表製造問題。

## Acceptance Matrix

| Area | PASS / FAIL / BLOCKED | Evidence |
|---|---|---|
| verified_rewrites authority | | |
| duplicate prevention | | |
| rewrite/advice copy | | |
| three-state ComplianceTable | | |
| count/summary vocabulary | | |
| print/PDF contract | | |
| backend safety/whitelist | | |
| regression tests | | |
| GitHub CI | | |

## Residual Risks / Follow-ups

- 只列出非 blocking、確實存在且有 evidence 的風險。
- 不要把沒有執行的檢查寫成 PASS。
```

這是 review-only 任務：不要修改工作樹、不要建立第二個 PR、不要 merge、
不要 deploy。
