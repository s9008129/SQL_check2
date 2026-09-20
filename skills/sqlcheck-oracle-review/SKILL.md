---
name: sqlcheck-oracle-review
description: Governance rules for how SQLCheck (Taiwan local-tax Oracle SQL review tool) reasons about SQL optimization knowledge — when a rewrite may be treated as proven, when it must stay advice-only, and what SQLCheck must never claim about indexes, execution plans, or Oracle statistics it cannot see. Load this before proposing or reasoning about ANY SQL rewrite/optimization change in this repository.
version: 1
---

# SQLCheck Oracle Review — SQLCheck Oracle Knowledge v1

SQLCheck is Oracle-focused, but it is **not an Oracle DBA tool**. It reviews
one submitted SQL statement's text; it has no database connection, no
execution plan, no index metadata, no statistics. Everything in this skill
exists to stop a coding agent (or the AI advice pipeline this Handoff.md
describes) from pretending otherwise.

## The one file that matters: the Pattern Catalog

`backend/app/knowledge/pattern_catalog.yaml` is the single machine-readable
source of truth for SQL optimization pattern knowledge — what a pattern is,
its classification, why, and what it may/may not claim. This SKILL.md and its
`references/` explain **how to use** that catalog; they do not duplicate its
content. If you find yourself copying pattern rationale out of the catalog
into prose here, stop — link the pattern id instead.

Read `references/project-boundaries.md` first — it states the authority order
and the compliance/optimization boundary. Then:

- Deciding whether a rewrite can be shown as verified → `references/safe-rewrites.md`
- Explaining an ADVICE_ONLY direction → `references/advice-only-patterns.md`
- Checking what the model/agent must never say → `references/forbidden-claims.md`
- The Detect→Classify→...→Learn workflow → `references/methodology.md`

## Five things to hold in your head

1. **SQLCheck 是 Oracle-focused，但不是 Oracle DBA 工具。** No CREATE INDEX
   and no invented plan/index/runtime claims. When a reviewer explicitly
   supplies a SQL Developer execution plan from the test environment, the
   deterministic plan parser may state facts visible in that evidence
   (operation, predicate, E-Rows/A-Rows, buffers, etc.), but it still must not
   infer the production plan or promise "this will be faster" — see
   `references/forbidden-claims.md`.
2. **`pattern_catalog.yaml` 才是 optimization pattern 的 Source of Truth.**
   Not this SKILL.md, not `docs/sql-optimization-skill-applicability.md`
   — those explain and index it, they don't replace it.
3. **Compliance rules ≠ optimization knowledge.** `backend/app/config/rules.yaml`
   / `important_tables.yaml` (fed by 正式中心規範) decide BLOCK/NOTICE/PASS.
   Generic SQL-optimization opinions — including everything in the external
   `github/awesome-copilot` sql-optimization skill — never upgrade a pattern
   into a compliance finding. "SELECT * is bad practice" does not make
   SELECT * "不符合中心規範."
4. **Deterministic Python authority beats the LLM.** Order:
   正式中心規範 > `rule_engine.py` > `rewrite_rules.py` > this catalog > Gemma.
   Gemma is never the compliance authority and never the semantic-equivalence
   authority — it explains and drafts; deterministic code verifies.
5. **When in doubt about equivalence, classify down, not up.** A rewrite
   moves from ADVICE_ONLY to VERIFIED_REWRITE only when
   `backend/app/services/rewrite_rules.py` proves it without an unchecked
   precondition (with its own positive/negative/boundary tests) — never by
   adding an entry to the catalog alone, never because an external skill
   calls it safe, and never merely because a runtime rule already derives
   it. A proven rewrite must also produce SQL Oracle can execute (e.g. at
   most 1000 expressions in one IN list). If the runtime ever certifies more
   than governance does, the catalog records a `runtime_gap` (none is open
   since the 2026-09-18 Runtime Correctness fix; tests probe the runtime to
   keep it that way).

## Runtime boundary (read before touching Pattern Context)

Pattern Selector and Compact Context now form one deliberately narrow runtime
path:

1. `pattern_selector.py` maps existing deterministic facts to:
   - `exact`: a specific detector matched this catalog entry.
   - `family_signal`: only a broader family signal matched; the specific
     pattern is **not confirmed**.
2. `context_adapter.py` may inject only a bounded number of `exact` entries
   into Gemma as static `model_guidance_zh_tw`.
3. `family_signal` and `OUT_OF_SCOPE` never enter model context.
4. Context is filtered to the representative statement actually sent to
   Gemma, ordered VERIFIED_REWRITE → ADVICE_ONLY → INFORMATIONAL, and bounded
   by both top-N and character budget.
5. Selector/context failures are fail-open for AI availability, but they never
   change compliance, improvement score/potential, rewrite verification,
   candidate gating, API schema, UI, or Ollama settings.

The model still cannot promote ADVICE_ONLY to verified, and the server still
re-validates every candidate rewrite. See `references/project-boundaries.md`
for the exact authority and runtime boundaries.
