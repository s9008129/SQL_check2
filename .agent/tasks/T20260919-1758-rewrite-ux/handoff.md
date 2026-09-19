# Handoff — SQLCheck rewrite UX semantics refinement

## TASK

- TASK_ID: `T20260919-1758-rewrite-ux`
- STATUS: `READY_FOR_IMPLEMENTATION`
- PLAN_PATH: `.agent/tasks/T20260919-1758-rewrite-ux/plan.md`
- PLAN_REVISION: `1`
- PLAN_SHA256: `57456557f168766779b0d8cf7a29e7eb798e6044796c70b3455fe644bc7436b5`
- REVIEW_REQUIRED: `YES`
- REVIEW_REPORT: `.agent/tasks/T20260919-1758-rewrite-ux/review/attempt-01/review_report.md`
- REVIEWED_PLAN_REVISION: `1`
- REVIEWED_PLAN_SHA256: `57456557f168766779b0d8cf7a29e7eb798e6044796c70b3455fe644bc7436b5`
- INDEPENDENT_ACCEPTANCE_REQUIRED: `YES`
- E2E_REQUIRED: `NO`
- ACCEPTANCE_MODE: `manual UI/print acceptance + full project validation + PR CI`
- Fresh Implementer required: `YES`
- Planner/Reviewer transcript required: `NO`

## GOAL_ANCHOR

Make deterministic rewrite fragments render once from the new authoritative payload, preserve legacy fallback only for absent fields, and make rewrite/compliance states unambiguous in browser and PDF. Prove the requested copy, three-state dashboard, print behavior, and fallback semantics with regression tests and full validation. Preserve backend rule/compliance/improvement authority, safety guards, and the existing two-rule rewrite whitelist.

## CRITICAL_PATH

1. Verify this handoff/hash and the clean product baseline.
2. Fix `SqlCompare` source selection and `App` optional-field pass-through.
3. Implement requested verified/advice/info and diff copy, visible explanation lines, and hero copy.
4. Map all center-rule presentation surfaces to three visible states; simplify `ComplianceTable` to item/result and hide `NA`.
5. Add focused regressions and run full backend/frontend validation.
6. Run the two supplied SQL acceptance scenarios at the strongest available local level, then commit/push/open PR and observe CI.

## SEMANTIC_INVARIANTS

- `verified_rewrites !== undefined` means a new backend payload: render only those deterministic verified fragments, including an intentionally empty list. Never merge legacy AI verified/corrected fragments into that list.
- `verified_rewrites === undefined` means an old backend payload: allow existing AI `verified`/`corrected` fragment fallback, while continuing to suppress unverified SQL.
- Frontend status mapping is presentation-only: PASS→符合, NOTICE/REVIEW→建議, BLOCK→不符合, NA hidden. Do not change backend `RuleStatus`, compliance calculation, or improvement score.
- Deterministic authority remains `rule_engine.py` → `rewrite_rules.py` → knowledge catalog → AI. Do not add whitelist rules or loosen safety/revalidation.
- AI/prompt/optional-field failure degrades locally and must not block deterministic compliance results or the rest of the page.

## BEST_EFFORT_DO_NOT_GATE

- Prompt wording reduces AI explanation duplication but cannot gate deterministic fragment rendering.
- PR CI is delivery evidence; unavailable GitHub auth/workflow must be reported as an environment/delivery blocker, never fabricated as pass.
- Live model wording may be unavailable locally; use the strongest deterministic/manual UI evidence and label the limitation.

## DEFERRED_NOT_THIS_TASK

- New deterministic rewrite patterns, backend rule/status/compliance/score changes, LLM/provider changes, archive/deployment/config changes, R008 business matrix, and any concrete `不可採用` state.

## REPO_ANCHOR

- Project root: `/Users/hsiaojohnny/dev/SQL_check2`
- Branch: `feature/rewrite-ux-semantics-v3`
- Anchor HEAD: `23a2af748887750102b7db748620e3dba211ebb1`
- Relevant dirty state: product worktree clean; only `.agent/tasks/T20260919-1758-rewrite-ux/` planning/review artifacts are untracked.
- Drift since plan/review: none; plan hash and reviewed hash match.

## CURRENT_STATE_DELTA

Starting from `origin/main` `11e6f1cb…`, `bce4f` was cherry-picked as commit `23a2af7…`. Focused baseline before this implementation is frontend 42 tests passed and selected backend tests 250 passed. No product file has been edited after the cherry-pick.

## MUST_READ_PLAN

Before first product edit, read plan sections: Goal contract, Must not break, Critical path, Criticality/dependency matrix, Global gates/rationale, Verification gates, and Stop/escalation conditions. Also use the reviewed snapshot/report for the approved Revision 1 boundary.

## SETTLED_DO_NOT_REOPEN

- Plan Revision 1 / review attempt 01: deterministic payload presence is the source-of-truth boundary; no whitespace-only dedupe architecture.
- Backend authority and whitelist: remain unchanged; only R005 SUBSTR equality→canonical LIKE and R006 same-column OR→IN are verified.
- Compliance semantics: backend statuses/calculation stay unchanged; only frontend presentation maps them to three states.
- No merge/deploy; commit, push, PR, and CI observation are required delivery steps.

## REVERIFY_ON_START

- Confirm `git status`, branch, HEAD, and plan/review hash before product mutation.
- Reconfirm current symbols/strings in `App.tsx`, `SqlCompare.tsx`, `ComplianceTable.tsx`, `SummaryCards.tsx`, `ResultOverview.tsx`, `SqlDiffView.tsx`, prompt, and tests before editing if files drift.

## TRIGGERED_POLICIES

- `/Users/hsiaojohnny/.codex/policies/goal-alignment-design-economy.md`
- `/Users/hsiaojohnny/.codex/policies/workflow-routing.md`
- `/Users/hsiaojohnny/.codex/policies/testing-verification.md`
- `/Users/hsiaojohnny/.codex/policies/ui-accessibility.md`
- `/Users/hsiaojohnny/.codex/policies/dependencies-contracts.md`
- `/Users/hsiaojohnny/.codex/policies/git-change-hygiene.md`

## FIRST_ACTION

Run the mutable-precondition check, then edit only the fragment source-of-truth boundary (`App.tsx` pass-through and `SqlCompare.tsx` presence branch) and its focused regression tests before moving to copy/table waves.

## IMPLEMENTATION_WAVES

- Wave 1 — `CORE-FRAGMENT`: presence-sensitive deterministic/legacy fragment selection; no merge normalization.
- Wave 2 — `CORE-UX-COPY`: verified/advice/info badges, visible explanations, compare badge/labels, hero copy, and all center-rule status surfaces.
- Wave 3 — `CORE-COMPLIANCE`: simple item/result table, status/count mapping, `NA` hiding, no evidence/note/resolved annotation.
- Wave 4 — `CORE-PRINT` + `SUPPORTING-PROMPT`: preserve visible copy in print, hide full SQL/copy controls, add prompt anti-duplication instruction.
- Wave 5 — `BACKEND-REGRESSION` + `FRONTEND-HEALTH` + `BACKEND-HEALTH`: focused then full tests, Ruff, TypeScript, production build, final diff review.
- Wave 6 — `MANUAL-ACCEPTANCE` + delivery: supplied SQL cases, commit, push, PR, CI observation; no merge/deploy.

## ACCEPTANCE_CONTRACT

| CHECK_ID | COMMAND/SCENARIO | GOAL_CRITICALITY | EVIDENCE_ROLE | CLOSURE_GATE | BASELINE_RULE | FAILURE_ROUTING | WAIVER_ALLOWED | WAIVER_AUTHORITY |
|---|---|---|---|---|---|---|---|---|
| CORE-FRAGMENT | Frontend `SqlCompare` tests for formatted duplicate, comma whitespace, undefined fallback, and empty-array suppression | CORE | OUTCOME + MUST_NOT_BREAK | HARD_CLEAN | Baseline delta from focused 42-test suite | Task regression → repair; semantic change → replan | NO | NONE |
| CORE-UX-COPY | Component tests for exact badges/lines/labels/old-text absence and hero/overview vocabulary | CORE | OUTCOME | HARD_CLEAN | Baseline delta | Task regression → repair | NO | NONE |
| CORE-COMPLIANCE | `ComplianceTable` component tests for PASS/NOTICE/REVIEW/BLOCK/NA, row simplification, counts; summary tests | CORE | OUTCOME + MUST_NOT_BREAK | HARD_CLEAN | Baseline delta | Task regression → repair | NO | NONE |
| CORE-PRINT | Print CSS test plus browser/print inspection if available; verify new visible text and existing hidden full SQL/copy selectors | CORE | OUTCOME + MUST_NOT_BREAK | HARD_CLEAN | Existing print test baseline | Task regression → repair | NO | NONE |
| BACKEND-REGRESSION | `uv run pytest -q` and prompt assertion; deterministic whitelist/safety tests must remain green | CORE | MUST_NOT_BREAK | HARD_CLEAN | Full baseline delta | Task regression → repair; backend semantic change → replan | NO | NONE |
| FRONTEND-HEALTH | `npm test -- --run`, `npm run build` (includes TypeScript) | SUPPORTING | REPOSITORY_HEALTH | HARD_CLEAN | Full baseline delta | New failure → repair/classify | NO | NONE |
| BACKEND-HEALTH | `uv run pytest -q`, `uv run ruff check app tests` | SUPPORTING | REPOSITORY_HEALTH | HARD_CLEAN | Full baseline delta | New failure → repair/classify | NO | NONE |
| MANUAL-ACCEPTANCE | UX-STATE-01 and UX-STATE-02 supplied SQL with strongest local API/UI/print evidence | CORE | OUTCOME | HARD_CLEAN | N/A | Product mismatch → repair; unavailable live model → scoped environment blocker with deterministic evidence | NO | NONE |
| PR-CI | Open PR to `main`; inspect configured GitHub Actions | SUPPORTING | REPOSITORY_HEALTH | NON_GATING | N/A | Auth/workflow unavailable → report scoped environment blocker | YES | Project owner only |

Expected status routing must preserve orthogonal implementation, CORE acceptance, required verification, independent acceptance, and task closure fields in the Stage 04/05 artifacts. Required artifact: `.agent/tasks/T20260919-1758-rewrite-ux/execution.md`; if independent acceptance is run, preserve Stage 04 snapshot and write an append-only `e2e/attempt-N/` artifact.

## STOP_AND_ESCALATE_IF

- Any change to backend compliance/RuleStatus/improvement calculation, rewrite whitelist, AI safety/revalidation, or the approved optional-field fallback meaning is required.
- Repository evidence contradicts the presence-sensitive `verified_rewrites` contract or makes safe old/new compatibility impossible.
- A test/acceptance failure shows the user goal or approved architecture is wrong rather than a bounded implementation defect.
- A supporting field/source is being promoted into a global blocker without an explicit safety/correctness rationale.

## HISTORICAL_TASK_DEPENDENCIES

NONE. The bce4 behavior is present on the current branch as the starting commit, not an external task artifact dependency.

TASK_ID: `T20260919-1758-rewrite-ux`
HANDOFF_PATH: `.agent/tasks/T20260919-1758-rewrite-ux/handoff.md`
PLAN_REVISION: `1`
STATUS: `READY_FOR_IMPLEMENTATION`
NEXT_STAGE: `04_IMPLEMENT`
