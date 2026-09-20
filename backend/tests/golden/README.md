# Golden / E2E evidence runner

> Golden corpus governance：見 `docs/golden-benchmark-strategy.md`。本專案不要求先取得
> 30～50 支由資深 DBA 評分的真實 SQL；可由規範錨點、rewrite correctness anchors、
> 少量去識別化真實案例與可驗證的合成邊界案例共同建立基準。AI 可協助設計案例，
> 但不可把自身對 runtime / index / Execution Plan 的猜測當 Ground Truth。

`run_golden.py` checks the live SQLCheck stack (this codebase's own
`sql_parser` / `rule_engine` / `ai_service`, not a re-implementation) against
a REAL live LLM provider instance. It can run against either the formal-host
Ollama/Gemma provider or the project’s Ollama Cloud profile used for development validation.

## Run

```bash
cd backend
uv run python tests/golden/run_golden.py --base-url http://localhost:11434 -v
```

- `--base-url` overrides the **active provider** base URL for this one run. When using
  formal-host Ollama, do not expose TCP 11434 to LAN clients just to run this.
- `-v` prints a one-line per-case summary (rewrite outcome, advice count,
  improvement potential, wall-clock latency, prompt/eval token counts).
- `--out <path>` additionally writes the de-identified evidence JSON. Without
  the flag only the summary is printed. Exit code is `0` only when every
  case passes (0 is not proof of model quality — read the per-case lines).

## Evidence / de-identification policy

Golden cases must stay synthetic or de-identified, and the evidence writer is
deliberately incapable of emitting anything else: it copies only whitelisted
fields — case name, compliance, rule ids/statuses, advice count, per-advice
`verification`, rewrite `outcome`, `improvement_potential`, token counts,
latency and pass/fail. No SQL text, no model output, no API response and no
application number can be written. Never post-process the record into a less
safe shape, and do not commit output produced from real production cases — a
`.gitignore`d directory is not a licence to store un-deidentified data.

## What is asserted

- deterministic, strict: compliance verdict, fired rule ids, parser
  structural-complexity flags;
- AI, few and explicit: no forbidden claims/vocabulary,
  `estimated_improvement_pct` sanity, plus each case's `expect_no_advice` /
  `expect_outcome_in` / `expect_candidate_allowed` declarations.
  `expect_no_advice` is strict: a clean-SQL case passes only when
  `advice == []` **and** `suggested_sql.outcome == "not_needed"`; a
  "not_needed" answer that still carries advice is recorded as
  `quiet_kind=not_needed_with_advice` and FAILS the case.

Adding a case: extend `CASES` in `run_golden.py` with synthetic SQL, state the
deterministic expectations (`expect_compliance`, `expect_finding_rule_ids`,
`expect_complexity_flags`) and — only where the PRD requires a specific model
behaviour — one explicit AI expectation. Keep per-advice `impact` a
*recorded* observation, not an assertion: it is reference material only and
never feeds the deterministic improvement score or potential level.

## Mac / Ollama Cloud

Mac 不需要安裝地端模型。先在 Repo 根目錄：

```bash
cp .env.mac.example .env
# 填入 OLLAMA_API_KEY
set -a; source .env; set +a
cd backend
SQLCHECK_LLM_PROVIDER=ollama_cloud uv run python tests/golden/run_golden.py -v
```

也可以不在本機執行，直接到 GitHub Actions 手動啟動 **Manual Live Cloud E2E**：

- `smoke`：執行 live golden cases。
- `full`：執行較完整的 model/API E2E。

雲端測試只使用 synthetic 或已去識別化 SQL；不要把 production archive 或原始案件 SQL 送到雲端。
