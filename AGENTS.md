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
