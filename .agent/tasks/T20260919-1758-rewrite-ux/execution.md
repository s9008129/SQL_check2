# Stage 04 Execution Record

## IDENTITY
- TASK_ID: T20260919-1758-rewrite-ux
- PLAN_REVISION: 1
- PLAN_SHA256: 57456557f168766779b0d8cf7a29e7eb798e6044796c70b3455fe644bc7436b5
- HANDOFF: .agent/tasks/T20260919-1758-rewrite-ux/handoff.md
- HANDOFF_SHA256: 197f3f740930fc3122207793ae588a9fcb7aa26a984b295919393c34f00c2ee7
- REVIEW: .agent/tasks/T20260919-1758-rewrite-ux/review/attempt-01/review_report.md
- REVIEW_GATE: PLAN_APPROVED
- BRANCH: feature/rewrite-ux-semantics-v3
- STARTING_SHA: 23a2af748887750102b7db748620e3dba211ebb1
- RECORDED_AT: 2026-09-19T18:20:28+08:00

## GOAL_ANCHOR
Deliver the focused SQLCheck rewrite UX/correctness refinement: deterministic
rewrite fragments are authoritative for new payloads, rewrite state is explicit
and visible, the compliance dashboard has exactly three user-facing result
states, and regression coverage plus CI delivery are ready without changing
formal rule authority or the rewrite whitelist.

## IMPLEMENTATION_WAVES
1. **Deterministic fragment authority**
   - Passed `verified_rewrites` through `App.tsx` without collapsing `undefined`
     into `[]`.
   - `SqlCompare` now treats any defined list, including `[]`, as the new
     backend deterministic source of truth; only an undefined field uses the
     legacy AI verified/corrected fallback.
   - Removed raw-string `mergeSegments()` deduplication as the primary design.
2. **Rewrite/advice copy and diff presentation**
   - Added visible verified explanation, explicit verified/review/info badges,
     `查詢結果不變`, and the concise `改後寫法` label.
   - Updated hero copy and prompt guidance so AI does not duplicate deterministic
     verification wording.
3. **Compliance presentation**
   - Added presentation-only PASS/NOTICE+REVIEW/BLOCK mapping to 符合/建議/不符合;
     NA rows are hidden.
   - Replaced evidence-heavy rows and old count vocabulary with the simple
     item/result table and three-state summary counts.
4. **Regression coverage and print behavior**
   - Added frontend tests for source-of-truth fallback semantics, copy, counts,
     row mapping, and print CSS; added the backend prompt non-duplication test.
   - Preserved API evidence/note fields and existing full SQL/copy print hiding.

## SEMANTIC_INVARIANTS_CHECKED
- No changes to `rule_engine.py`, `rewrite_rules.py`, `rules.yaml`, compliance
  calculation, improvement score calculation, provider integration, archive
  format, important-table configuration, deployment scripts, or R008 matrix.
- Deterministic whitelist remains limited to same-column equality OR -> IN and
  SUBSTR equality -> canonical LIKE.
- Unsafe/unverified concrete SQL remains suppressed by existing guards.
- Backend `RuleStatus` remains unchanged; REVIEW is only presented as yellow
  建議 in the dashboard.

## VALIDATION_EVIDENCE
- Frontend full suite: `npm test -- --run` -> 12 files, 88 tests passed.
- Frontend production build: `npm run build` -> TypeScript/Vite exit 0; Vite
  emitted only the existing large-chunk warning.
- Backend full suite with canonical macOS temporary directory:
  `TMPDIR=$(mktemp -d /private/tmp/sqlcheck-pytest.XXXXXX) uv run pytest -q`
  -> 555 passed in 14.43s.
- Ruff: `uv run ruff check app tests` -> All checks passed.
- `git diff --check` -> passed.
- Backend manual API cases executed through `/api/analyze`:
  - UX-STATE-01 -> PASS, R006 NOTICE, one `or_eq_to_in` verified rewrite.
  - UX-STATE-02 -> BLOCK, R004/R006 NOTICE, `verified_rewrites=[]`, no concrete
    unsafe rewrite in the stubbed advice response.
- Browser acceptance executed through CUA-controlled Chrome + Vite frontend:
  - UX-STATE-01 visibly showed one fragment, `可使用此改寫`, both visible
    verification lines, `查詢結果不變`, `原寫法`, `改後寫法`, R006 建議.
  - UX-STATE-02 visibly showed `需先確認再改`, `1 項不符合 · 2 項建議`, COST
    不符合, R004/R006 建議, and simple compliance rows without generic evidence.

## ENVIRONMENT_NOTE
The default macOS command `uv run pytest -q` first exposed two pre-existing
`backend/tests/test_main.py` path-comparison failures caused by `/var` versus
`/private/var` temporary-directory normalization. The same full suite passed
555/555 when run with an explicit `/private/tmp` TMPDIR. Product files and
those static-path tests were not changed. The local FastAPI root route also
selects the tracked empty `backend/static/.gitkeep` before `frontend/dist`, so
browser acceptance used the Vite frontend proxy; this is an environment/local
static selection issue outside this UX change.

## STATUS
PRIMARY_OUTCOME_STATUS: ACHIEVED
IMPLEMENTATION_STATUS: COMPLETE
CORE_ACCEPTANCE_STATUS: PASS
REQUIRED_VERIFICATION_STATUS: PASS (canonical macOS full-suite invocation)
INDEPENDENT_ACCEPTANCE_STATUS: PENDING_STAGE_05_RECORD
TASK_CLOSURE_STATUS: READY_FOR_INDEPENDENT_ACCEPTANCE
NEXT_ACTION: Write the append-only Stage 05 acceptance report, then perform final diff review and GitHub delivery.
