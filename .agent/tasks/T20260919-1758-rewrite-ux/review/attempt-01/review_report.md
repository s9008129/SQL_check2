# Plan Review Report

## REVIEW_METADATA

- TASK_ID: `T20260919-1758-rewrite-ux`
- REVIEW_ATTEMPT: `01`
- REVIEWED_PLAN_REVISION: `1`
- REVIEWED_PLAN_SHA256: `57456557f168766779b0d8cf7a29e7eb798e6044796c70b3455fe644bc7436b5`
- PLAN_SNAPSHOT_PATH: `.agent/tasks/T20260919-1758-rewrite-ux/review/attempt-01/plan_snapshot.md`
- Repository anchor observed: `feature/rewrite-ux-semantics-v3` at `23a2af748887750102b7db748620e3dba211ebb1`, based on `origin/main` `11e6f1cb5ae93fdb8827c3aea6fe109b87512fe1` plus cherry-picked `bce4f`.
- Reviewer runtime/model: Codex session, read-only review pass; no subagent API is exposed in this runtime.

## OWNER_VERDICT

The plan matches the requested outcome: eliminate duplicate deterministic/AI fragments, make verified status actionable, and reduce the center-rule dashboard to three visible states without moving authority into the frontend. Essential work is the presence-sensitive fragment boundary, visible copy, table/count mapping, print preservation, and regression/full validation. Prompt wording and PR CI are supporting evidence. No new global blocker is proposed; `verified_rewrites` only controls the local fragment presentation and legacy absence degrades locally. The simplest safe design is to remove `mergeSegments`, centralize frontend presentation mapping, and leave backend rule/rewrite/safety logic untouched. The largest remaining risk is a UI surface accidentally showing the backend's old `REVIEW`/`NOTICE` labels; the plan explicitly includes the hero, conclusion overview, summary card, and table to prevent that drift.

## GOAL_BASELINE

From the current user request, the primary goal is a focused UX/correctness refinement on top of the bce4 deterministic rewrite implementation. New backend payloads must treat `verified_rewrites` as the deterministic fragment source of truth, while old payloads without the field retain AI fallback. The page and PDF must visibly distinguish verified, advice-only, and informational content; the compare panel must say `查詢結果不變`, explain the result once, and label the right fragment `改後寫法`. The center-rule dashboard must present only `符合`/`建議`/`不符合`, hide `NA` rows, simplify rows, and use the requested counts. Backend formal rules, compliance/improvement calculations, safety guards, and the two-item deterministic whitelist must not change. Full tests, push, PR, and CI evidence are required; no merge/deploy.

## GOAL_ALIGNMENT

- The primary outcome and success evidence directly cover the four requested goals and the explicit print/PDF acceptance surface.
- The plan preserves the authority chain: backend rule engine and rewrite verifier remain authoritative; frontend only selects already-safe fragments and maps statuses for presentation.
- The plan does not turn prompt wording or GitHub CI into a product gate that could block the core UI behavior without evidence-based rationale.

## NECESSITY_AND_TRACEABILITY

- Presence-sensitive `verified_rewrites`: directly traces to the observed duplicate and the required `undefined` versus `[]` compatibility contract; CORE.
- Visible evidence/status copy: directly traces to ambiguous adoption wording and the PDF requirement; CORE.
- Three-state table/count mapping: directly traces to the requested dashboard mental model; CORE.
- Print selectors and full-SQL/copy preservation: directly traces to the production/PDF bug surface; CORE.
- Prompt rule: directly traces to AI explanation duplication; SUPPORTING because deterministic UI remains authoritative.
- Full validation/PR CI: directly traces to the requested delivery evidence; SUPPORTING repository health.
- No unnecessary dependency, schema, state, or whitelist work is present.

## GATE_AND_VETO_AUDIT

- The plan introduces no global veto. `verified_rewrites` presence gates only which fragment source is rendered, not the result page, compliance, AI, or full rewrite panel.
- `undefined` fallback is justified by old backend compatibility; `[]` intentionally means the new backend checked and found no deterministic rewrite. Both paths are local and testable.
- Existing server-side safety/revalidation remains the only authority for concrete SQL. No frontend state can promote an unverified or rejected fragment.

## COUPLING_AND_FAILURE_CONTAINMENT

- The plan avoids coupling AI availability to deterministic fragments: pending/unavailable AI can still show deterministic rewrites when the field exists.
- Empty deterministic results hide only the fragment block; they do not globally suppress compliance or other advice.
- Legacy fallback is isolated to the absent-field path, preventing old AI advice from re-entering a new authoritative list.

## DESIGN_ECONOMY

- Removing `mergeSegments` is smaller and more reliable than building a semantic whitespace/comma normalizer; it fixes the architecture at the contract boundary.
- A shared presentation/count helper is justified because hero, overview, summary, and table must not drift between `NOTICE` and `REVIEW` wording.
- No new package, service, persistence, backend field, or deployment mechanism is needed.

## CRITICAL_PATH_AND_PRIORITY

The sequence starts with the P0 fragment-source boundary, then the user-visible semantics, then table/print, then regression/full verification and delivery. Supporting prompt/CI evidence does not delay proving the core fragment and dashboard behavior. This ordering is proportionate.

## REQUIREMENT_FIDELITY

The plan preserves all explicit non-goals: no whitelist expansion, no backend RuleStatus conversion, no compliance/improvement score changes, no provider/archive/deployment changes, and no `不可採用` UI state. It includes the requested copy and the four presence/fallback cases, the required table/summary/print tests, and the provided acceptance SQL cases.

## GROUNDING_AND_DRIFT

Repository evidence supports the load-bearing claims: `App.tsx` currently collapses the optional field with `?? []`; `SqlCompare.tsx` currently merges deterministic and AI fragments; `ComplianceTable.tsx` renders evidence/note and old counts; `SummaryCards.tsx` renders `提醒`/`需確認`; `SqlDiffView.tsx` contains the old right label; and the prompt has no UI-owned verified-explanation rule. The starting branch includes bce4 and the focused baseline is green (frontend 42, selected backend 250).

## ARCHITECTURE_AND_CONTRACTS

The plan treats the optional `verified_rewrites` response field as a compatibility contract rather than changing the backend schema. It explicitly preserves legacy absence fallback and gives new empty arrays distinct meaning. Backend API evidence remains intact; only presentation is simplified. Frontend status labels are presentation-only and do not rewrite `ComplianceStatus` or `RuleStatus`.

## DATA_SECURITY_RELIABILITY

No sensitive data flow, provider, archive, or persistence change is planned. Existing unverified/rejected SQL suppression remains in place. The prompt addition reduces duplicated verification claims and does not loosen the existing “do not guess SQL” or revalidation rules.

## IMPLEMENTATION_SEQUENCE

The proposed implementation order is executable and has focused tests at each boundary. Handoff must preserve the reviewed revision/hash before product edits. If implementation evidence requires a backend semantic change, the stated escalation/replan condition applies.

## TESTABILITY_AND_ACCEPTANCE

The plan identifies deterministic unit/component assertions for every specified state and fallback, plus full project-standard checks. The manual SQL cases can prove deterministic rewrite discovery and rule statuses locally; live AI wording may depend on provider availability and must be reported as scoped evidence rather than fabricated. Print CSS tests and, where available, browser/PDF inspection cover the explicitly requested print behavior.

## SCOPE_AND_COMPLEXITY

Scope is limited to existing frontend components, one prompt file, regression tests, task artifacts, and delivery metadata. There is no dependency or migration risk. The task remains STANDARD because it is coordinated and contract-sensitive but does not change persistent data, security boundaries, or backend decision authority.

## FINDINGS

No BLOCKER or MAJOR finding. No plan revision is required.

## REQUIRED_PLAN_CHANGES

None for Revision 1.

## RESIDUAL_MINOR_NOTES

- The reviewer runtime is the same Codex session because no independent subagent/runtime API is available; the review used a fresh read-only pass and a plan snapshot, but it is not model-family independent.
- `E2E_REQUIRED` is `NO` by plan choice; the required manual acceptance and print evidence still need to be run and labeled accurately. If a real browser journey becomes necessary to prove the contract, execute it as independent acceptance rather than calling unit tests E2E.

FINAL_STATUS: PLAN_APPROVED
NEXT_ACTION: Stage 03 Handoff for `PLAN_REVISION=1` and the recorded plan hash.
