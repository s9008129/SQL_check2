# Repository Guidelines

## Project Structure & Module Organization

- `backend/app/` contains the FastAPI API, schemas, settings, deterministic SQL rules, LLM adapters, prompts, and YAML configuration. Backend tests live in `backend/tests/`; golden-case tooling is under `backend/tests/golden/`.
- `frontend/src/` contains the React/TypeScript UI. Keep reusable UI in `components/`, API access in `api/`, utilities in `lib/`, and colocate tests as `*.test.ts(x)`.
- `scripts/` provides local launch helpers; `deploy/` contains Windows production deployment and Pester tests. Runtime archives belong in ignored `data/sql_archive/`; never commit them.

## Build, Test, and Development Commands

Requirements are Python 3.12, `uv`, and Node.js 22+.

```bash
bash scripts/dev-mac.sh                 # start FastAPI (:8000) and Vite (:5173)
cd backend && uv sync --group dev       # install locked Python dependencies
uv run pytest -q                        # run backend tests
uv run ruff check app tests             # lint and check imports
cd ../frontend && npm ci                # install locked frontend dependencies
npm run test -- --run                   # run Vitest once
npm run build                           # type-check and build production assets
```

Use `scripts/dev.ps1 -WithFakeOllama` on Windows when a simulated LLM endpoint is useful. Docker builds are intended for the production host.

## Coding Style & Naming Conventions

Python uses four spaces, Python 3.12 syntax, `snake_case` functions/modules, and `PascalCase` classes. Ruff enforces selected `E`, `F`, `I`, `UP`, `B`, and `SIM` rules with a 100-column target. TypeScript uses two spaces, semicolons, `camelCase` functions, and `PascalCase` React components. Preserve the rule engine as the authority for compliance; LLM output is advisory only.

## Testing Guidelines

Use Pytest/`pytest-asyncio` for backend tests and Vitest with Testing Library for frontend tests. Name tests `test_*.py` or `*.test.ts(x)`. Add focused regression coverage for changed behavior, then run the complete affected suite and frontend build. Use only synthetic or de-identified SQL in cloud-backed tests.

The user-facing score name is **「改善指數」**. Internal module names such as `improvement_score.py` may remain unchanged, but new UI/documentation must not revive the older 「改善優先指數」 label.

### Manual Live Cloud E2E

`.github/workflows/live-cloud-e2e.yml` is the permanent real-model verification entry point. It is deliberately **manual-only** (`workflow_dispatch`), not a required check on every PR.

- `smoke`: real Ollama Cloud / `gemma4:31b` golden cases; use after ordinary prompt/model-path changes.
- `full`: the broader ~59-call model/API suite; use for release sealing or changes to masking, AI guards, rewrite governance, confidence, or provider behavior.
- Do not claim this cloud workflow proves Browser DOM or Native Print Preview behavior.
- Never paste API keys into prompts, logs, issues, PRs, or evidence; the workflow uses the repository `OLLAMA_API_KEY` secret.

## E2E Artifact & Disk Hygiene

All manual, Live-Gemma, browser, Computer Use, and regression evidence must stay under the repository's ignored `data/` tree. **Do not write test artifacts to `/tmp`, `/var/tmp`, the repository root, or arbitrary desktop/download folders.**

For every independent test run, create one clearly named run directory, for example:

```text
data/e2e_post_pr20_YYYYMMDD_HHMMSS/
```

Put every run-specific artifact there, including temporary test harness scripts created only for that run, raw model captures, final API JSON, CSV matrices, logs, screenshots, print evidence, environment/git-state evidence, and the Markdown report. Product source code changes still belong in the normal source tree; this rule applies to generated test/run artifacts.

Evidence validity is stricter than file existence:

- `ui_pass` must come from actual browser DOM assertions captured from the rendered SQLCheck page. A screenshot merely existing, or a static expected-value table in a harness, is not proof.
- Every UI screenshot used as PASS evidence must visibly contain SQLCheck content for the named case; a desktop/wallpaper/terminal screenshot is invalid evidence and must fail that case.
- `print_pass` must be backed by a real native Chrome print-preview capture for that case. A terminal screenshot, browser page screenshot, or Computer Use error screen must be marked NOT PROVEN / FAIL, never PASS.
- Browser/print evidence JSON must record what was actually observed (text/role/state/window title) and the assertions evaluated. Do not generate a PASS JSON by copying expected values from the test matrix.
- When Computer Use or browser tooling fails, report the affected evidence as blocked/not proven; never infer success from API output.

At the end of the run:

1. remove disposable caches/intermediate files that are not evidence;
2. scan the artifact tree for secrets and identifiable production SQL/data;
3. package the complete run directory into a single ZIP under `data/`, using the same run name;
4. verify the ZIP can be opened and contains the expected manifest;
5. report the ZIP path as the hand-off artifact for independent review.

The contents of `data/` are intentionally git-ignored (except repository documentation/placeholders). Never commit E2E evidence, Live model output, screenshots, or ZIP bundles unless the user explicitly requests it. Do not delete or modify `data/sql_archive/`, which is application runtime data.

## Commit & Pull Request Guidelines

### Commit message 規則（強制）

- 本專案的**每一個 commit message** 都必須使用臺灣繁體中文語義撰寫。
- commit subject 與 body 都必須使用臺灣繁體中文語義撰寫；必要的技術名詞、
  檔名、命令、API 名稱與標準縮寫可以保留原文，但整體敘述不得改成英文語義。
- 每個 commit message 都必須詳細說明下列三個部分：
  1. **意圖**：這次變更要解決什麼問題，以及為什麼需要它。
  2. **做了什麼**：實際修改的程式、測試、設定或文件，以及重要的行為邊界。
  3. **下一步建議**：後續驗證、review、部署前檢查或已知限制。
- 建議使用以下格式，並依變更內容補充驗證結果與限制：

  ```text
  <臺灣繁體中文摘要>

  意圖：
  ...

  做了什麼：
  ...

  下一步建議：
  ...

  驗證與限制：
  ...
  ```

- commit 前必須檢查 commit message 是否符合本規則；不得以縮短訊息、
  只寫英文 conventional prefix，或只列檔名來取代必要說明。
- 這項規則適用於 feature、fix、refactor、test、docs、chore 以及後續
  所有其他類型的 commit。

Pull requests should explain the user-visible outcome, list verification commands and results, link relevant issues, and include screenshots for UI changes. Call out configuration, privacy, or deployment impacts explicitly.

## Security & Configuration

Copy from `.env.example` or `.env.mac.example`; never commit `.env`, API keys, identifiable case data, or production SQL. The application must not connect to Oracle or claim measured execution plans, indexes, scans, or performance gains without evidence.

Current owner decisions (2026-09-20): Balanced cloud privacy is closed as-is; SQL Archive retention stays as-is; R008 is disabled because important tables are reminders only (R007 remains); the existing 改善指數 weights/algorithm are final; Ollama 11434 firewall hardening is owner-managed infrastructure, not an application backlog item. See `docs/document-status.md` before treating an older PRD/Handoff/report as current requirements.

### SQL Developer Execution-Plan Evidence

SQLCheck may now receive execution-plan text explicitly supplied from the **test environment**. Treat this as a separate evidence channel, not as permission to become a production DBA tool.

- Prefer SQL Developer **Autotrace (F6)** when the test environment permits actual execution; F10 Explain Plan remains useful but is estimated evidence.
- The application does not connect to Oracle. It only parses text/CSV the reviewer pasted or uploaded.
- Raw execution-plan text must not be written to `data/sql_archive/` and must not be sent to the cloud LLM. The deterministic plan parser owns plan facts.
- A test-machine plan never proves the production plan. Always label its source as test evidence.
- `TABLE ACCESS FULL`, HASH JOIN, SORT, etc. are observable plan facts, not automatic defects.
- Execution-plan evidence does **not** change center compliance or the existing 改善指數 unless the owner separately reopens that governance decision.
- Runtime statistics such as A-Rows, Starts, Buffers and Autotrace statistics may be compared when actually supplied, but never fabricate missing values or post-change improvements.
