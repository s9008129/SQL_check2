# SQLCheck rewrite UX semantics refinement

TASK_ID: T20260919-1758-rewrite-ux
PLAN_REVISION: 1
TASK_CLASS: STANDARD
REVIEW_REQUIRED: YES
INDEPENDENT_ACCEPTANCE_REQUIRED: YES
E2E_REQUIRED: NO

## Baseline and branch provenance

- Baseline main SHA: `11e6f1cb5ae93fdb8827c3aea6fe109b87512fe1`
- `bce4f6104eaba78790cffbc925c520f15a4ceb37` was not an ancestor of `origin/main`.
- Cherry-pick required: YES.
- Resulting starting SHA: `23a2af748887750102b7db748620e3dba211ebb1`
- Implementation branch: `feature/rewrite-ux-semantics-v3`
- Focused pre-change baseline: frontend 42 tests passed; backend selected regression set 250 passed.

## Goal contract

### Primary outcome

Make the result page and printed report show one authoritative deterministic rewrite, unambiguous rewrite evidence, and a simple three-state center-rule dashboard, while retaining legacy-payload compatibility and all existing SQL safety/authority boundaries.

### Success evidence

- New payloads with `verified_rewrites` present render only server-derived deterministic fragments; `undefined` retains legacy AI verified/corrected fallback; `[]` renders no manufactured deterministic fragment.
- Verified, advice-only, and informational labels plus their visible explanations match the requested Traditional Chinese copy in browser and print.
- `ComplianceTable` renders only `檢核項目` + `結果`, maps PASS/NOTICE/REVIEW/BLOCK to `符合`/`建議`/`不符合`, hides NA, and uses the requested aggregate counts.
- All center-rule status surfaces that currently expose backend labels (hero pill, conclusion overview, summary card, and compliance table) use the same presentation vocabulary without changing the backend status or calculation.
- Regression tests prove the source-of-truth/fallback boundary, copy, table mapping, print selectors, prompt instruction, and existing deterministic rewrite guards.
- Full project validation is observed: backend pytest, Ruff, frontend tests, TypeScript check, and production Vite build. PR CI is observed after push where GitHub workflows are available.

### Must not break

- `rule_engine.py` remains the authority for formal center-rule status and compliance calculation; no backend RuleStatus or compliance/improvement semantics change.
- `rewrite_rules.py` remains limited to the existing verified forms: same-column equality OR -> IN and SUBSTR equality -> canonical LIKE. TRUNC/NVL/TO_CHAR/leading-wildcard/cross-column-OR/DISTINCT/JOIN structural changes remain advice-only.
- Existing AI safety guards continue suppressing unsafe/rejected concrete SQL; unverified advice remains non-copyable.
- AI availability/degradation, archive format, provider configuration, `rules.yaml`, important-tables configuration, R008 business matrix, deployment scripts, and full-SQL/copy print hiding remain unchanged.
- API evidence/note fields remain available even though the dashboard presentation no longer renders their generic text.

### Non-goals

- Expanding the deterministic rewrite whitelist.
- Changing backend compliance, improvement-score, rule-engine, prompt safety boundaries, LLM providers, archive format, or deployment behavior beyond the requested wording instruction.
- Adding a new concrete unsafe SQL state such as `不可採用`.

## Critical path

1. Preserve the bce4 deterministic rewrite implementation on this branch.
2. Change `SqlCompare` to branch on optional-field presence: deterministic-only fragments when `verifiedRewrites !== undefined`; legacy AI fallback only when it is `undefined`. Pass `result.verified_rewrites` through `App` without `?? []`.
3. Apply the requested evidence/status copy and visible explanations, including diff heading/label and hero copy; use the three-state presentation mapping on all center-rule status surfaces without changing backend status meaning.
4. Replace the compliance dashboard row with a two-column status presentation and centralized frontend mapping/count text; keep `NA` hidden and evidence/note in the API.
5. Update print assertions/styles only as needed so all new visible meaning prints and full SQL/copy controls remain hidden.
6. Add/update focused regressions, including the prompt non-duplication rule, then run full validation and inspect the final diff.
7. Perform the two supplied acceptance SQL checks at the strongest available local API/UI level, commit with the requested detailed message, push the branch, open a PR to `main` if `gh` is authenticated, and observe CI.

## Criticality / dependency matrix

| Element | Goal/decision contribution | Criticality | Influence/weight | Global veto? | Missing/failure behavior | Rationale |
|---|---|---|---|---|---|---|
| `verified_rewrites` presence boundary | Prevents duplicate/mis-authoritative deterministic fragments | CORE | N/A | No | `undefined` uses legacy fallback; `[]` stays empty and only hides fragment panel locally | New backend contract is the source of truth; old payloads remain usable |
| Verified/advice/info copy | Makes adoption meaning understandable in browser/PDF | CORE | N/A | No | Local text regression if absent; SQL safety remains backend/frontend guarded | User explicitly needs actionable status wording |
| Compliance three-state presentation | Reduces dashboard cognitive load without changing judgment | CORE | N/A | No | Local presentation falls back to existing status tone; backend status unchanged | User requested presentation-only mapping |
| Print behavior | Ensures printed report has the same critical meaning and no extra duplicate page | CORE | N/A | No | Browser/UI behavior remains independently testable; print check remains required verification | PDF is an explicit production bug surface |
| Existing backend deterministic/safety tests | Protects authority and whitelist invariants | CORE / MUST_NOT_BREAK | N/A | No | Any regression requires repair before closure | The refinement must not broaden or weaken rewrite authority |
| Prompt wording guard | Prevents AI explanation from repeating UI-owned verification copy | SUPPORTING | N/A | No | Model wording can degrade locally; UI still owns the status line | Important for duplicate copy but not a gate on deterministic result rendering |
| Full validation + PR CI | Repository health and delivery evidence | SUPPORTING | N/A | No | Report exact pending/environment status; do not claim pass without evidence | User explicitly requests full validation and a PR |

## Global gates and rationale

- No new global veto is introduced. The optional-field check is local to the fragment presentation. A missing/empty deterministic list must not block the rest of the result page; this preserves AI-unavailable and legacy degradation behavior.
- Existing server-side rewrite validation remains the only authority for concrete verified SQL. Frontend changes only choose which already-safe payload fragments to render.

## Complexity budget

- Remove `mergeSegments` rather than add semantic whitespace normalization; this eliminates the duplicate class by honoring the payload contract.
- Add at most one shared frontend status/count mapping helper and one visible evidence-line style; both centralize requested copy and avoid inconsistent component-local translations.
- Add no dependencies, no backend schema changes, and no new persistent state.

## Verification gates planned

| CHECK_ID | GOAL_CRITICALITY | EVIDENCE_ROLE | CLOSURE_GATE | BASELINE_REQUIRED | FAILURE_CLASSIFICATION_RULE | WAIVER_ALLOWED | WAIVER_AUTHORITY |
|---|---|---|---|---|---|---|---|
| CORE-FRAGMENT | CORE | OUTCOME + MUST_NOT_BREAK | HARD_CLEAN | YES | New/changed fragment-source behavior failure is TASK_REGRESSION | NO | NONE |
| CORE-UX-COPY | CORE | OUTCOME | HARD_CLEAN | YES | Required visible copy/state mismatch is TASK_REGRESSION | NO | NONE |
| CORE-COMPLIANCE | CORE | OUTCOME + MUST_NOT_BREAK | HARD_CLEAN | YES | Status mapping/count/NA presentation mismatch is TASK_REGRESSION; backend semantic changes are out of scope | NO | NONE |
| CORE-PRINT | CORE | OUTCOME + MUST_NOT_BREAK | HARD_CLEAN | YES | New copy hidden or old full-SQL/copy behavior regresses is TASK_REGRESSION | NO | NONE |
| BACKEND-REGRESSION | CORE | MUST_NOT_BREAK | HARD_CLEAN | YES | Existing deterministic/safety test regression is TASK_REGRESSION | NO | NONE |
| FRONTEND-HEALTH | SUPPORTING | REPOSITORY_HEALTH | HARD_CLEAN | YES | New failure in full frontend test/type/build check is TASK_REGRESSION; unrelated baseline failures disclosed | NO | NONE |
| BACKEND-HEALTH | SUPPORTING | REPOSITORY_HEALTH | HARD_CLEAN | YES | New failure in full pytest/Ruff is TASK_REGRESSION; unrelated baseline failures disclosed | NO | NONE |
| PR-CI | SUPPORTING | REPOSITORY_HEALTH | NON_GATING | NO | Missing GitHub auth/workflow is ENVIRONMENT blocker, not fabricated as pass | YES | Project owner only |
| MANUAL-ACCEPTANCE | CORE | OUTCOME | HARD_CLEAN | NO | Supplied UX SQL behavior must be observed; unavailable live model is scoped environment limitation with strongest deterministic evidence recorded | NO | NONE |

## Stop / escalation conditions

- Stop and replan if implementing the UI requires changing backend compliance calculation, RuleStatus meaning, rewrite whitelist, AI safety guard, or optional-field semantics beyond the approved boundary.
- Stop and escalate if the current payload shape/evidence shows `verified_rewrites` is not a reliable present-vs-undefined contract and a safe compatibility rule cannot be established from repository evidence.
- Do not merge or deploy. If GitHub auth/CI is unavailable, report the exact delivery blocker and preserve the pushed branch/commit.
